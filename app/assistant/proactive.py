"""ProactiveEngine — the propose-then-confirm loop (M14, ASSISTANT.md §5).

FIND (signal sources) → REASON (M9 LLM, optional) → CLASSIFY (risk.py,
deterministic — never the model) → DEDUP (idempotency_key) → EMIT (ProposalStore)
→ SURFACE (controller) → CONFIRM → EXECUTE (only past audit.assert_approved) →
AUDIT.

M14 sources: stale/overdue work threads + manual `propose`. M14 executors are
reversible only (todo_add, thread_resume_nudge); send/remote/calendar executors
arrive in later milestones — but the risk table and the assert_approved gate are
fully built now, so `never_auto` can never auto-run regardless of config/model.

Threading: scan() may run on a worker thread (it does LLM I/O); all store
mutations and executors run on the MAIN thread (the controller marshals). The
approve/skip/snooze entry points are called on the main thread (panel / IPC).
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from assistant import risk
from assistant.audit_store import NotApproved
from assistant.thread_store import ThreadStore
from llm_client import LLMClient, LLMError, StreamHandle


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _idem(kind, source_ref):
    return hashlib.sha1(f"{kind}:{source_ref}".encode("utf-8")).hexdigest()[:16]


def _extract_json(text):
    """Pull the first JSON value out of an LLM reply (tolerates code fences /
    prose around it). Returns the parsed value or None."""
    if not text:
        return None
    text = text.strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except ValueError:
                continue
    return None


class ProactiveEngine:
    def __init__(self, config, proposals, threads, audit,
                 on_proposal=None, on_executed=None):
        self.config = config
        self.proposals = proposals
        self.threads = threads
        self.audit = audit
        self.client = LLMClient(config)
        self.on_proposal = on_proposal    # surface(proposal) — main thread
        self.on_executed = on_executed    # refresh(proposal) — main thread
        self.on_remote_dispatch = None    # M16: set by controller; (prop)->ref

    # == discovery (worker thread OK) ========================================

    def scan(self):
        """One proactive cycle. Returns the list of newly emitted proposals."""
        emitted = []
        if not bool(self.config.get("assistant_proactive_enabled")):
            print("proactive: disabled (assistant_proactive_enabled=False)",
                  flush=True)
            return emitted
        for thread in self._stale_threads():
            prop = self._emit_resume_nudge(thread)
            if prop is not None:
                emitted.append(prop)
        print(f"proactive scan: {len(emitted)} new proposal(s)", flush=True)
        return emitted

    def propose_manual(self, text):
        """User free text -> proposal(s). LLM classifies into todo_add items;
        falls back to a single todo_add when the LLM is unavailable. Always
        returns at least one proposal so the manual entry never silently fails."""
        items = self._llm_propose(text)
        created = []
        for item in items:
            kind = str(item.get("kind") or "todo_add")
            if not risk.known_kind(kind):
                kind = "todo_add"
            prop = self._emit(
                kind=kind,
                title=str(item.get("title") or text)[:200],
                rationale=str(item.get("rationale") or ""),
                source="manual",
                source_ref=f"manual:{_now_iso()}",
                payload={"action": "none", "args": {}},
            )
            if prop is not None:
                created.append(prop)
        if not created:  # LLM empty/failed -> guarantee one proposal
            prop = self._emit(
                kind="todo_add", title=text[:200], rationale="",
                source="manual", source_ref=f"manual:{_now_iso()}",
                payload={"action": "none", "args": {}},
            )
            if prop is not None:
                created.append(prop)
        return created

    def propose(self, kind, title, rationale, *, source="manual",
                source_ref=None, payload=None):
        """Public: create a proposal of `kind` (classified + gated like any
        other). Used for explicit actions, e.g. remote delegation."""
        return self._emit(
            kind=kind, title=title, rationale=rationale, source=source,
            source_ref=source_ref or f"{source}:{_now_iso()}",
            payload=payload or {})

    # == emit + classify + dedup =============================================

    def _emit(self, kind, title, rationale, source, source_ref,
              thread_id=None, payload=None):
        idem = _idem(kind, source_ref)
        existing = self.proposals.find_active_by_idempotency(idem)
        if existing is not None:
            print(f"proactive: dedup {kind} ({source_ref}) -> {existing['id']}",
                  flush=True)
            return None
        klass = risk.risk_of(kind)  # DETERMINISTIC — model never sets this
        prop = self.proposals.create(
            kind=kind, risk=klass, title=title, rationale=rationale,
            source=source, source_ref=source_ref, thread_id=thread_id,
            payload=payload or {}, idempotency_key=idem,
        )
        if self._should_auto_execute(prop):
            self.approve(prop["id"], by="auto_policy", gesture="auto_policy")
        elif self.on_proposal is not None:
            self.on_proposal(prop)
        return self.proposals.get(prop["id"])  # latest state (may be executed)

    def _should_auto_execute(self, prop):
        """Auto-run ONLY when the trust dial is auto_safe AND the kind is both
        risk=auto AND on the whitelist. A never_auto kind can never pass even if
        wrongly whitelisted — the risk gate is checked here, deterministically."""
        if str(self.config.get("assistant_autonomy")) != "auto_safe":
            return False
        kind = prop.get("kind")
        if risk.risk_of(kind) != risk.AUTO:
            return False
        return kind in (self.config.get("assistant_auto_safe_kinds") or [])

    # == confirm-then-execute (main thread) ==================================

    def approve(self, pid, by="user", gesture="panel_approve",
                edited_payload=None):
        prop = self.proposals.get(pid)
        if prop is None or prop.get("status") in ("executed", "skipped"):
            return prop
        to_status = "edited" if edited_payload is not None else "approved"
        self.audit.record(pid, prop.get("status"), to_status, by, gesture)
        fields = {"approval": {"by": by, "ts": _now_iso(),
                               "gesture": gesture,
                               "edited": edited_payload is not None}}
        if edited_payload is not None:
            fields["payload"] = edited_payload
        self.proposals.mark_decided(pid, to_status, **fields)
        return self.execute(pid)

    def skip(self, pid, by="user"):
        prop = self.proposals.get(pid)
        if prop is None:
            return None
        self.audit.record(pid, prop.get("status"), "skipped", by, "skip")
        return self.proposals.mark_decided(pid, "skipped")

    def snooze(self, pid, hours=None):
        prop = self.proposals.get(pid)
        if prop is None:
            return None
        hours = float(hours or self.config.get("assistant_nudge_cooldown_hours"))
        until = (datetime.now(timezone.utc)
                 + timedelta(hours=hours)).isoformat(timespec="seconds")
        self.audit.record(pid, prop.get("status"), "snoozed", by="user",
                          gesture="snooze", note=until)
        return self.proposals.update(pid, status="snoozed", snoozed_until=until)

    def execute(self, pid):
        """Run a proposal's side effect — ONLY past the structural gate. Any
        kind without an M14 executor (send/remote/calendar) fails cleanly."""
        prop = self.proposals.get(pid)
        if prop is None:
            return None
        try:
            self.audit.assert_approved(pid)  # the single structural bottleneck
        except NotApproved as exc:
            print(f"proactive: BLOCKED execute {pid} — {exc}", flush=True)
            return self.proposals.mark_decided(pid, "failed", error=str(exc))
        kind = prop.get("kind")
        try:
            result_ref = self._run_executor(prop)
        except Exception as exc:  # an executor failure must not crash the app
            print(f"proactive: executor {kind} failed: {exc!r}", flush=True)
            done = self.proposals.mark_decided(pid, "failed", error=repr(exc))
        else:
            self.audit.record(pid, prop.get("status"), "executed", by="system",
                              gesture="execute")
            done = self.proposals.mark_decided(pid, "executed",
                                               result_ref=result_ref)
        if self.on_executed is not None:
            self.on_executed(done)
        return done

    def _run_executor(self, prop):
        kind = prop.get("kind")
        payload = prop.get("payload") or {}
        if kind == "todo_add":
            thread = self.threads.create(
                title=prop.get("title") or "(todo)",
                source="proposal",
                where_was_i=str(payload.get("args", {}).get("where_was_i", "")),
                next_action=str(payload.get("args", {}).get("next_action", "")),
            )
            return thread["id"]
        if kind == "thread_resume_nudge":
            tid = prop.get("thread_id")
            if tid:
                self.threads.touch(tid)  # un-stale; resume gesture
                self.threads.add_activity(tid, "resume", "사용자가 재개")
                self._open_links(self.threads.get(tid))
            return tid
        if kind == "remote_dispatch" and self.on_remote_dispatch is not None:
            return self.on_remote_dispatch(prop)  # M16 — runs past assert_approved
        # No executor for this kind yet (reply_draft/send_*/calendar_*/…).
        raise NotImplementedError(f"executor for kind '{kind}' arrives later")

    @staticmethod
    def _open_links(thread):
        links = [str(x) for x in ((thread or {}).get("links") or [])
                 if str(x).startswith(("http://", "https://", "file://"))]
        if not links:
            return

        def _open():  # AppKit must run on the main thread
            try:
                from AppKit import NSWorkspace
                from Foundation import NSURL
                ws = NSWorkspace.sharedWorkspace()
                for link in links:
                    ws.openURL_(NSURL.URLWithString_(link))
            except Exception as exc:
                print(f"proactive: open_links skipped ({exc!r})", flush=True)

        from PyObjCTools import AppHelper
        AppHelper.callAfter(_open)

    # == signal sources ======================================================

    def _stale_threads(self):
        """Active threads idle past the threshold (or overdue), ranked, capped
        at nudge_max_per_cycle, outside quiet hours, past cooldown."""
        if self._in_quiet_hours():
            return []
        stale_h = float(self.config.get("assistant_thread_stale_hours"))
        candidates = []
        for thread in self.threads.active():
            overdue = self._is_overdue(thread)
            if not overdue and ThreadStore.idle_hours(thread) < stale_h:
                continue
            if self._recently_nudged(thread["id"]):
                continue
            candidates.append((overdue, thread))
        # rank: overdue first, then most idle
        candidates.sort(
            key=lambda c: (c[0], ThreadStore.idle_hours(c[1])), reverse=True)
        cap = int(self.config.get("assistant_nudge_max_per_cycle"))
        return [t for _o, t in candidates[:max(cap, 0)]]

    def _emit_resume_nudge(self, thread):
        summary = self._llm_resume(thread)
        where = summary.get("where_was_i") or thread.get("where_was_i") or ""
        nxt = summary.get("next_action") or thread.get("next_action") or ""
        if summary:  # refresh the carried summary (internal, doesn't un-stale)
            self.threads.touch(thread["id"], bump=False,
                               where_was_i=where, next_action=nxt)
        title = f"이어서: {thread.get('title', '')}".strip()
        rationale = nxt or where or "오래 멈춰 있는 작업이에요."
        return self._emit(
            kind="thread_resume_nudge", title=title, rationale=rationale,
            source="stale_thread", source_ref=thread["id"],
            thread_id=thread["id"],
            payload={"action": "none",
                     "args": {"where_was_i": where, "next_action": nxt}},
        )

    def _recently_nudged(self, tid):
        cooldown = float(self.config.get("assistant_nudge_cooldown_hours"))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=cooldown)
        for prop in self.proposals.all():
            if (prop.get("thread_id") == tid
                    and prop.get("kind") == "thread_resume_nudge"):
                try:
                    ts = datetime.fromisoformat(prop.get("ts"))
                except (ValueError, TypeError):
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    return True
        return False

    @staticmethod
    def _is_overdue(thread):
        due = thread.get("due_ts")
        if not due:
            return False
        try:
            d = datetime.fromisoformat(due)
        except ValueError:
            return False
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d < datetime.now(timezone.utc)

    def _in_quiet_hours(self):
        window = self.config.get("assistant_quiet_hours") or []
        if len(window) != 2:
            return False
        start, end = int(window[0]), int(window[1])
        hour = datetime.now().astimezone().hour
        if start == end:
            return False
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end  # wraps midnight

    # == LLM (worker thread) =================================================

    def _llm_resume(self, thread):
        ctx = json.dumps({
            "title": thread.get("title"),
            "where_was_i": thread.get("where_was_i"),
            "next_action": thread.get("next_action"),
            "links": thread.get("links"),
            "activity": (thread.get("activity") or [])[-6:],
            "idle_hours": round(ThreadStore.idle_hours(thread), 1),
        }, ensure_ascii=False)
        system = str(self.config.get("assistant_resume_system"))
        user = str(self.config.get("assistant_resume_user")).replace(
            "<<CONTEXT>>", ctx)
        data = self._llm_json(system, user)
        return data if isinstance(data, dict) else {}

    def _llm_propose(self, text):
        system = str(self.config.get("assistant_propose_system"))
        user = str(self.config.get("assistant_digest_user")).replace(
            "<<DIGEST>>", str(text))
        data = self._llm_json(system, user)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        return []

    def _llm_json(self, system, user):
        model = str(self.config.get("assistant_model")) or None
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        buf = []
        try:
            for chunk in self.client.stream_chat(
                messages, StreamHandle(), model=model):
                buf.append(chunk)
        except LLMError as exc:
            print(f"proactive: LLM unavailable ({exc}) — fallback", flush=True)
            return None
        return _extract_json("".join(buf))

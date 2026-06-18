"""gmail_triage.py — turn an inbox poll into reply-draft proposals (M17, §6.4).

`GmailTriager` builds a header+snippet **digest** of the new messages, asks the
M9 LLM to pick the 1–2 that genuinely need the user to reply, and to draft a
reply for each (in the email's own language). It then enriches each pick with
the fields needed to actually create the draft (recipient, Re: subject, thread
id, In-Reply-To). All of this runs on a worker thread.

`GmailExecutor` is the thin side-effect wrapper the ProactiveEngine calls past
`audit.assert_approved`: `create_draft` (the confirm step → a reversible Gmail
DRAFT) and `send_draft` (the second, explicit user gesture → actually send).

Privacy: triage uses the active provider by default; set `gmail_force_local_llm`
to pin it to the local MLX server (the digest then never leaves the machine).
"""

import json

from llm_client import LLMClient, LLMError, StreamHandle

from assistant.gmail_client import GmailClient, _addr


def _extract_json_array(text):
    """Pull the first JSON array out of an LLM reply (tolerates fences/prose)."""
    if not text:
        return None
    text = text.strip()
    i, j = text.find("["), text.rfind("]")
    if 0 <= i < j:
        try:
            return json.loads(text[i:j + 1])
        except ValueError:
            return None
    return None


class _ForceLocalConfig:
    """A config view that pins active_provider() to the first is_local provider,
    delegating everything else. Used to keep Gmail triage on the local server
    without mutating the shared ConfigStore (which other requests read)."""

    def __init__(self, config):
        self._config = config

    def active_provider(self):
        providers = [p for p in (self._config.get("providers") or [])
                     if isinstance(p, dict)]
        local = next((p for p in providers if p.get("is_local")), None)
        return dict(local) if local else self._config.active_provider()

    def __getattr__(self, name):
        return getattr(self._config, name)


def _resub(subject):
    s = str(subject or "").strip()
    return s if s.lower().startswith("re:") else f"Re: {s}" if s else "Re:"


class GmailTriager:
    def __init__(self, config):
        self.config = config
        triage_cfg = (_ForceLocalConfig(config)
                      if bool(config.get("gmail_force_local_llm")) else config)
        self.client = GmailClient(config)
        self.llm = LLMClient(triage_cfg)

    def triage(self, metas):
        """metas: list of get_meta() dicts. Returns a list of enriched picks
        ready for reply_draft proposals: {msg_id, thread_id, to, subject,
        in_reply_to, title, rationale, draft}. [] when nothing needs a reply or
        the LLM is unavailable (fail quiet — never raise into the daemon)."""
        metas = [m for m in metas if m and not m.get("error")]
        if not metas:
            return []
        by_id = {m["id"]: m for m in metas}
        picks = self._llm_pick(self._digest(metas))
        out = []
        for pick in picks:
            mid = str(pick.get("msg_id") or "")
            meta = by_id.get(mid)
            if meta is None or not str(pick.get("draft") or "").strip():
                continue
            out.append({
                "msg_id": mid,
                "thread_id": meta.get("thread_id"),
                "to": _addr(meta.get("from")),
                "subject": _resub(meta.get("subject")),
                "in_reply_to": meta.get("message_id_header"),
                "title": str(pick.get("title")
                             or meta.get("subject") or "")[:160],
                "rationale": str(pick.get("rationale") or "")[:300],
                "draft": str(pick.get("draft")),
            })
            if len(out) >= 2:   # MVP cut: at most two reply drafts per poll
                break
        return out

    def _digest(self, metas):
        cap = int(self.config.get("assistant_digest_max_chars"))
        lines = []
        for m in metas:
            lines.append(
                f"[{m.get('id')}] From: {m.get('from', '')} | "
                f"Subject: {m.get('subject', '')} | "
                f"Preview: {m.get('snippet', '')[:200]}")
        return "\n".join(lines)[:cap]

    def revise(self, draft, instruction, subject=""):
        """Rewrite `draft` per a free-text `instruction` (panel Edit&Approve).
        Uses the same privacy-aware LLM as triage. Returns the new body, or None
        if the LLM is unavailable / empty (caller keeps the old draft)."""
        instruction = str(instruction or "").strip()
        if not instruction:
            return None
        system = str(self.config.get("gmail_revise_system"))
        user = (str(self.config.get("gmail_revise_user"))
                .replace("<<SUBJECT>>", str(subject or ""))
                .replace("<<DRAFT>>", str(draft or ""))
                .replace("<<INSTRUCTION>>", instruction))
        model = str(self.config.get("assistant_model")) or None
        buf = []
        try:
            for chunk in self.llm.stream_chat(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
                    StreamHandle(), model=model):
                buf.append(chunk)
        except LLMError as exc:
            print(f"gmail revise: LLM unavailable ({exc})", flush=True)
            return None
        text = "".join(buf).strip()
        return text or None

    def _llm_pick(self, digest):
        system = str(self.config.get("gmail_triage_system"))
        user = str(self.config.get("gmail_triage_user")).replace(
            "<<DIGEST>>", digest)
        model = str(self.config.get("assistant_model")) or None
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        buf = []
        try:
            for chunk in self.llm.stream_chat(
                    messages, StreamHandle(), model=model):
                buf.append(chunk)
        except LLMError as exc:
            print(f"gmail triage: LLM unavailable ({exc})", flush=True)
            return []
        data = _extract_json_array("".join(buf))
        return [d for d in data if isinstance(d, dict)] if isinstance(
            data, list) else []


class GmailExecutor:
    """Side-effect wrapper called by the engine PAST assert_approved."""

    def __init__(self, config):
        self.client = GmailClient(config)

    def create_draft(self, args):
        res = self.client.create_draft(
            to=args.get("to", ""), subject=args.get("subject", ""),
            body=args.get("draft", ""), thread_id=args.get("thread_id"),
            in_reply_to=args.get("in_reply_to"))
        if res.get("error"):
            raise RuntimeError(f"draft 생성 실패: {res['error']}")
        return res["draft_id"]

    def send_draft(self, args):
        draft_id = args.get("draft_id")
        if not draft_id:
            raise RuntimeError("draft_id 없음")
        res = self.client.send_draft(draft_id)
        if res.get("error"):
            raise RuntimeError(f"전송 실패: {res['error']}")
        return res.get("sent_id") or draft_id


def _main():
    """Smoke test from app/: `python -m assistant.gmail_triage`."""
    from config import ConfigStore

    config = ConfigStore()
    triager = GmailTriager(config)
    res = triager.client.list_query(config.get("gmail_query_filter"), 10)
    metas = [triager.client.get_meta(mid) for mid in (res.get("ids") or [])]
    picks = triager.triage(metas)
    print(json.dumps(picks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _main()

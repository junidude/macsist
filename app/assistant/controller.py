"""AssistantController — main-thread glue for the assistant subsystem.

M13: read-only kanban cockpit (HermesBridge + AssistantMonitor -> badge + 작업
tab). M14: the propose-then-confirm loop — ThreadStore / ProposalStore /
AuditStore, the ProactiveEngine, the ProposalPanel, and the ProactiveMonitor.
Hotkey callbacks and IPC handlers route here; everything that touches AppKit or
the stores' UI callbacks runs on the main thread (workers marshal via callAfter).
"""

import threading

from PyObjCTools import AppHelper

from assistant.audit_store import AuditStore
from assistant.delivery import Deliverer
from assistant.hermes_bridge import HermesBridge
from assistant.monitor import (
    AssistantMonitor,
    ProactiveMonitor,
    RemoteJobMonitor,
)
from assistant.gmail_monitor import GmailMonitor
from assistant.gmail_triage import GmailTriager
from assistant.proactive import ProactiveEngine
from assistant.proposal_store import ProposalStore
from assistant.remote_exec import RemoteAgentExecutor, RemoteJobStore
from assistant.thread_store import ThreadStore
from i18n import t
from text_capture import capture_selected_text


class AssistantController:
    def __init__(self, config, status_item, main_window):
        self.config = config
        self.status_item = status_item     # StatusItemController (menu bar)
        self.main_window = main_window     # MainWindowController
        # M13 cockpit
        self.bridge = HermesBridge(config)
        self.kanban_monitor = AssistantMonitor(
            config, self.bridge, on_change=self._onBoardChanged)
        # M14 stores + engine
        self.threads = ThreadStore(config)
        self.proposals = ProposalStore(config)
        self.audit = AuditStore(config)
        self.engine = ProactiveEngine(
            config, self.proposals, self.threads, self.audit,
            on_proposal=self._proposalEmitted,
            on_executed=self._proposalChanged,
        )
        self.proactive_monitor = ProactiveMonitor(config, self.engine)
        self.deliverer = Deliverer(config)  # M15: Telegram (away/quiet hours)
        # M16: remote agent delegation (SSH → tmux codex/claude)
        self.remote = RemoteAgentExecutor(config)
        self.remote_jobs = RemoteJobStore(config)
        self.remote_monitor = RemoteJobMonitor(
            config, self.remote, self.remote_jobs, on_done=self._onRemoteDone)
        self.engine.on_remote_dispatch = self._dispatchRemote
        main_window.on_assistant_remote = self.delegate_remote
        # M17: Gmail — poll inbox → triage → reply_draft proposals (OFF by default)
        self.gmail_triager = GmailTriager(config)
        self.gmail_monitor = GmailMonitor(config, on_gmail=self._onGmail)
        # the draft/send network calls run off the main thread (panel click)
        self.engine.on_gmail_draft = self._draftGmail
        self.engine.on_gmail_send = self._sendGmail
        # lazy panel (built on first surface) — avoids touching AppKit if unused
        self._panel = None
        # let the window read the board + stores directly
        main_window.assistant_bridge = self.bridge
        main_window.assistant_threads = self.threads
        main_window.assistant_proposals = self.proposals
        main_window.on_assistant_approve = self.approve
        main_window.on_assistant_skip = self.skip
        main_window.on_assistant_snooze = self.snooze
        main_window.on_assistant_propose = self.handlePropose_
        main_window.on_assistant_new_thread = self.new_thread
        main_window.on_assistant_scan = self.handleScan
        self.proposals.on_changed = lambda: AppHelper.callAfter(self._refresh)

    def start(self):
        self.kanban_monitor.start()
        self.proactive_monitor.start()
        self.remote_monitor.start()
        self.gmail_monitor.start()
        self._refresh()

    # == board / badge (main thread) =========================================

    def _onBoardChanged(self):
        self.main_window.refreshAssistantIfVisible()
        self._refreshBadge()

    def _refresh(self):
        self.main_window.refreshAssistantIfVisible()
        self._refreshBadge()

    def _refreshBadge(self):
        try:
            count = len(self.proposals.pending())
        except Exception as exc:
            print(f"assistant: badge read error {exc!r}", flush=True)
            count = 0
        self.status_item.updateAssistantBadge_(count)

    # == engine callbacks (called from worker -> marshal to main) ============

    def _proposalEmitted(self, prop):
        AppHelper.callAfter(self._surface, prop)

    def _proposalChanged(self, prop):
        AppHelper.callAfter(self._refresh)

    def _surface(self, prop):
        """Main thread: show the proposal in the floating panel + refresh, and
        (M15) push to Telegram when the user is away / in quiet hours."""
        self._refresh()
        try:
            self._panel_controller().presentProposal_(prop)
        except Exception as exc:  # surfacing must never crash the loop
            print(f"assistant: panel present error {exc!r}", flush=True)
        if self.deliverer.should_telegram():
            text = f"{t('assistant.tg_proposal_prefix')} {prop.get('title') or ''}"
            if prop.get("rationale"):
                text += f"\n{prop['rationale']}"
            self.deliverer.send_telegram(text)

    def _panel_controller(self):
        if self._panel is None:
            from assistant.proposal_panel import ProposalPanelController
            self._panel = ProposalPanelController.alloc().initWithConfig_owner_(
                self.config, self)
        return self._panel

    # == confirm-then-execute entry points (main thread) =====================

    def approve(self, pid, edited_payload=None):
        self.engine.approve(pid, by="user", gesture="panel_approve",
                            edited_payload=edited_payload)
        self._refresh()

    def skip(self, pid):
        self.engine.skip(pid)
        self._refresh()

    def snooze(self, pid, hours=None):
        self.engine.snooze(pid, hours)
        self._refresh()

    # == IPC handlers (main thread, from _RemoteCommandRelay) ================

    def handlePropose_(self, text):
        text = (text or "").strip()
        if not text:
            return
        # propose_manual does LLM I/O -> run off the main thread
        threading.Thread(
            target=self.engine.propose_manual, args=(text,),
            name="assistant-propose", daemon=True,
        ).start()

    def handleApprove_(self, pid):
        if pid:
            self.approve(pid)

    def handleScan(self):
        self.proactive_monitor.poke()

    def new_thread(self, text):
        """Create a work thread directly from the tab's input (no LLM)."""
        text = (text or "").strip()
        if not text:
            return
        title = text.splitlines()[0][:120]
        self.threads.create(title=title, source="manual", where_was_i=text[:500])
        self._refresh()

    # == remote delegation (M16) =============================================

    def delegate_remote(self, text):
        """⌘⇧D / 원격 button: propose running `text` on the remote agent. It's a
        risk=confirm proposal → user approves → dispatched past assert_approved."""
        text = (text or "").strip()
        if not text:
            return
        if not bool(self.config.get("remote_enabled")):
            print("delegate_remote: disabled (remote_enabled=False)", flush=True)
            return
        host = self.remote.host() or {}
        self.engine.propose(
            kind="remote_dispatch",
            title=t("assistant.remote_delegate_title").format(text=text[:60]),
            rationale=t("assistant.remote_run_on").format(
                alias=host.get("alias", "?"), agent=host.get("agent", "codex")),
            payload={"action": "run_remote",
                     "args": {"prompt": text, "alias": host.get("alias"),
                              "agent": host.get("agent", "codex")}},
        )
        self._refresh()

    def _dispatchRemote(self, prop):
        """Engine executor (past assert_approved): kick off the remote job on a
        worker thread so the SSH handshake never blocks the main thread."""
        args = (prop.get("payload") or {}).get("args") or {}
        threading.Thread(target=self._dispatchWorker, args=(args,),
                        daemon=True, name="remote-dispatch").start()
        return "dispatching"

    def _dispatchWorker(self, args):
        job = self.remote.dispatch(args.get("prompt", ""), args.get("alias"),
                                  args.get("agent"))
        AppHelper.callAfter(self._dispatchDone, job)

    def _dispatchDone(self, job):
        self.remote_jobs.put(job)
        self.remote_monitor.poke()
        if job.get("error"):
            print(f"remote: dispatch error {job.get('id')}: {job['error']}",
                  flush=True)
        else:
            print(f"remote: registered {job.get('id')} running", flush=True)
        self._refresh()

    def _onRemoteDone(self, job, result):
        """Main thread: a remote job finished — file the result as a thread and
        notify (Telegram when away)."""
        status = job.get("status")
        mark = t("assistant.done") if status == "done" else t("assistant.failed")
        self.threads.create(
            title=t("assistant.remote_result_title").format(
                mark=mark, prompt=job.get("prompt", "")[:50]),
            source="remote",
            where_was_i=(result or "")[:800],
            next_action=t("assistant.remote_next"),
        )
        self._refresh()
        if self.deliverer.should_telegram():
            self.deliverer.send_telegram(
                t("assistant.tg_remote").format(
                    mark=mark, prompt=job.get("prompt", "")[:60],
                    result=(result or "")[:500]))

    # == Gmail (M17) =========================================================

    def _onGmail(self, metas):
        """Main thread: a batch of new messages arrived — triage on a worker
        thread (LLM I/O) so the poll callback never blocks the main thread."""
        threading.Thread(target=self._triageWorker, args=(metas,),
                        daemon=True, name="gmail-triage").start()

    def _triageWorker(self, metas):
        try:
            picks = self.gmail_triager.triage(metas)
        except Exception as exc:  # triage must never crash the daemon
            print(f"gmail: triage error {exc!r}", flush=True)
            return
        AppHelper.callAfter(self._gmailProposals, picks)

    def _gmailProposals(self, picks):
        """Main thread: create reply_draft proposals (each surfaces via the
        panel + Telegram-when-away, like any other proposal)."""
        if picks:
            self.engine.triage_to_proposals(picks)
        self._refresh()

    def _draftGmail(self, prop):
        """Engine hook (past assert_approved): create the Gmail DRAFT on a worker
        thread so the panel-approve click never blocks on the network."""
        args = (prop.get("payload") or {}).get("args") or {}
        threading.Thread(target=self._draftWorker, args=(prop, args),
                        daemon=True, name="gmail-draft").start()
        return "drafting"

    def _draftWorker(self, prop, args):
        draft_id = err = None
        try:
            draft_id = self.engine.gmail.create_draft(args)
        except Exception as exc:
            err = str(exc)
        AppHelper.callAfter(self._draftDone, prop, draft_id, err)

    def _draftDone(self, prop, draft_id, err):
        if err or not draft_id:
            self.proposals.mark_decided(prop["id"], "failed",
                                        error=err or t("assistant.err_draft_create"))
        else:
            # carry the real draft id + surface the 2nd-gesture send card
            self.proposals.update(prop["id"], result_ref=draft_id)
            self.engine.emit_send_reply(prop, draft_id)
        self._refresh()

    def _sendGmail(self, prop):
        """Engine hook (past assert_approved, never_auto): send the DRAFT on a
        worker thread. Only ever reached via the explicit '지금 보내기' gesture."""
        args = (prop.get("payload") or {}).get("args") or {}
        threading.Thread(target=self._sendWorker, args=(prop, args),
                        daemon=True, name="gmail-send").start()
        return "sending"

    def _sendWorker(self, prop, args):
        sent_id = err = None
        try:
            sent_id = self.engine.gmail.send_draft(args)
        except Exception as exc:
            err = str(exc)
        AppHelper.callAfter(self._sendDone, prop, sent_id, err)

    def _sendDone(self, prop, sent_id, err):
        if err or not sent_id:
            self.proposals.mark_decided(prop["id"], "failed",
                                        error=err or t("assistant.err_send"))
        else:
            self.proposals.update(prop["id"], result_ref=sent_id)
            print(f"gmail: sent {sent_id}", flush=True)
            # leave a persistent trace in the 비서 window (like a remote job)
            args = (prop.get("payload") or {}).get("args") or {}
            subject = str(args.get("subject") or "")
            self.threads.create(
                title=f"{t('assistant.mail_sent_title')}: {subject}".strip(),
                source="gmail",
                where_was_i=(f"{t('assistant.mail_to')} {args.get('to', '')}\n\n"
                             f"{args.get('draft', '')}")[:800],
                next_action=t("assistant.mail_followup"),
                status="done",
            )
            if self.deliverer.should_telegram():
                self.deliverer.send_telegram(
                    f"📧 [{t('assistant.mail_sent_title')}] {subject}\n"
                    f"{t('assistant.mail_to')} {args.get('to', '')}")
        self._refresh()

    def reviseDraft(self, pid, instruction):
        """Panel Edit&Approve: revise a reply_draft/send_reply's body per a
        free-text instruction on a worker thread (LLM), then re-present the card
        for re-confirmation. Returns nothing — the panel updates async."""
        prop = self.proposals.get(pid)
        if prop is None or str(prop.get("kind")) not in ("reply_draft",
                                                         "send_reply"):
            return
        threading.Thread(target=self._reviseWorker, args=(pid, instruction),
                        daemon=True, name="gmail-revise").start()

    def _reviseWorker(self, pid, instruction):
        prop = self.proposals.get(pid)
        args = (prop.get("payload") or {}).get("args") or {}
        new_draft = self.gmail_triager.revise(
            args.get("draft", ""), instruction, args.get("subject", ""))
        AppHelper.callAfter(self._reviseDone, pid, new_draft)

    def _reviseDone(self, pid, new_draft):
        prop = self.proposals.get(pid)
        if prop is not None and new_draft:
            payload = dict(prop.get("payload") or {})
            args = dict(payload.get("args") or {})
            args["draft"] = new_draft
            payload["args"] = args
            self.proposals.update(pid, payload=payload)
            prop = self.proposals.get(pid)
        # re-present the (possibly updated) card for another look
        try:
            self._panel_controller().presentRevised_(prop)
        except Exception as exc:
            print(f"assistant: revise re-present error {exc!r}", flush=True)
        self._refresh()

    def syncGmail(self):
        """`macsist gmail sync`: run one inbox poll now."""
        self.gmail_monitor.poke()

    def connectGmail(self):
        """`macsist gmail connect`: run the OAuth flow on a worker thread (it
        opens a browser + blocks on the loopback redirect)."""
        threading.Thread(target=self._gmailConnectWorker, daemon=True,
                        name="gmail-oauth").start()

    def _gmailConnectWorker(self):
        from assistant import gmail_oauth
        try:
            addr = gmail_oauth.connect(self.config)
            print(f"gmail: connected ({addr})", flush=True)
        except Exception as exc:
            print(f"gmail: connect failed {exc!r}", flush=True)
        AppHelper.callAfter(self._refresh)

    def showInbox(self):
        self.main_window.showAssistant()

    # == hotkeys (called on the pynput listener thread) ======================

    def captureTaskHotkey(self):
        """⌘⇧T: capture the current selection into a new work thread."""
        threading.Thread(target=self._captureTask, daemon=True).start()

    def _captureTask(self):
        try:
            text = capture_selected_text(self.config)
        except Exception as exc:
            print(f"assistant: capture failed {exc!r}", flush=True)
            return
        text = (text or "").strip()
        if not text:
            print("assistant: capture-task got empty selection", flush=True)
            return
        title = text.splitlines()[0][:120]
        AppHelper.callAfter(self._createThreadFromCapture, title, text)

    def _createThreadFromCapture(self, title, text):
        thread = self.threads.create(
            title=title, source="capture", where_was_i=text[:500])
        print(f"assistant: captured thread {thread['id']}", flush=True)
        self._refresh()
        self.main_window.showAssistant()

    def openInboxHotkey(self):
        """⌘⇧I: open the assistant inbox/threads."""
        AppHelper.callAfter(self.main_window.showAssistant)

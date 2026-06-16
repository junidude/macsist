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
from assistant.proactive import ProactiveEngine
from assistant.proposal_store import ProposalStore
from assistant.remote_exec import RemoteAgentExecutor, RemoteJobStore
from assistant.thread_store import ThreadStore
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
            text = f"🤖 [비서 제안] {prop.get('title') or ''}"
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
            title=f"원격 위임: {text[:60]}",
            rationale=f"{host.get('alias', '?')} · {host.get('agent', 'codex')} 에서 실행",
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
        mark = "완료" if status == "done" else "실패"
        self.threads.create(
            title=f"원격 {mark}: {job.get('prompt', '')[:50]}",
            source="remote",
            where_was_i=(result or "")[:800],
            next_action="결과 확인 후 반영",
        )
        self._refresh()
        if self.deliverer.should_telegram():
            self.deliverer.send_telegram(
                f"🤖 [원격 {mark}] {job.get('prompt', '')[:60]}\n"
                f"{(result or '')[:500]}")

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

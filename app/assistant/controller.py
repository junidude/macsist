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
from assistant.hermes_bridge import HermesBridge
from assistant.monitor import AssistantMonitor, ProactiveMonitor
from assistant.proactive import ProactiveEngine
from assistant.proposal_store import ProposalStore
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
        # lazy panel (built on first surface) — avoids touching AppKit if unused
        self._panel = None
        # let the window read the board + stores directly
        main_window.assistant_bridge = self.bridge
        main_window.assistant_threads = self.threads
        main_window.assistant_proposals = self.proposals
        main_window.on_assistant_approve = self.approve
        main_window.on_assistant_skip = self.skip
        main_window.on_assistant_snooze = self.snooze
        self.proposals.on_changed = lambda: AppHelper.callAfter(self._refresh)

    def start(self):
        self.kanban_monitor.start()
        self.proactive_monitor.start()
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
        """Main thread: show the proposal in the floating panel + refresh."""
        self._refresh()
        try:
            self._panel_controller().presentProposal_(prop)
        except Exception as exc:  # surfacing must never crash the loop
            print(f"assistant: panel present error {exc!r}", flush=True)

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

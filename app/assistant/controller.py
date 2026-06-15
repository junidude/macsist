"""AssistantController — main-thread glue for the assistant subsystem (M13).

Thin in M13: owns the HermesBridge and the AssistantMonitor, and on every board
change refreshes the menu-bar badge and the 작업 tab. Constructed in main.py as
a module-level controller (outlives main()), alongside _explain / _health.
Expanded in M14 with the proactive engine, proposal panel, and thread stores.
"""

from assistant.hermes_bridge import HermesBridge
from assistant.monitor import AssistantMonitor


class AssistantController:
    def __init__(self, config, status_item, main_window):
        self.config = config
        self.status_item = status_item   # StatusItemController (menu bar)
        self.main_window = main_window   # MainWindowController
        self.bridge = HermesBridge(config)
        self.monitor = AssistantMonitor(config, self.bridge,
                                        on_change=self._onBoardChanged)
        # let the 작업 tab read the board directly when the user opens it,
        # even with the live monitor disabled
        main_window.assistant_bridge = self.bridge

    def start(self):
        self.monitor.start()
        # one immediate refresh so a tab opened before the first tick is current
        self._onBoardChanged()

    def _onBoardChanged(self):
        """Main thread (monitor marshals via callAfter). Refresh the cockpit."""
        try:
            count = self.bridge.open_task_count()
        except Exception as exc:  # a board read must never crash the app
            print(f"assistant: board read error {exc!r}", flush=True)
            count = 0
        self.status_item.updateAssistantBadge_(count)
        self.main_window.refreshAssistantIfVisible()

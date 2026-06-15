"""AssistantMonitor — background poller for kanban board changes (M13).

A clone of health.ServerHealthMonitor: one daemon thread, a threading.Event
sleep with poke(), and every change marshalled to the main thread via
AppHelper.callAfter. Change detection diffs task_events by its AUTOINCREMENT id
(the monotonic anchor); a new event fires on_change() so the menu-bar badge and
the 작업 tab refresh. Never touches AppKit off the main thread.

Gated by `assistant_enabled` (the cockpit master switch). When off, the tab
still reads the board on demand — only the live polling/badge is skipped.
"""

import threading

from PyObjCTools import AppHelper


class AssistantMonitor:
    def __init__(self, config, bridge, on_change=None):
        self.config = config
        self.bridge = bridge
        self.on_change = on_change  # called on the MAIN thread, no args
        self._wake = threading.Event()
        self._thread = None
        self._cursor = 0

    def start(self):
        if not bool(self.config.get("assistant_enabled")):
            print("assistant monitor: disabled (assistant_enabled=False)",
                  flush=True)
            return
        self._cursor = self.bridge.max_event_id()
        self._thread = threading.Thread(
            target=self._loop, name="assistant-monitor", daemon=True
        )
        self._thread.start()
        print(f"assistant monitor started cursor={self._cursor}", flush=True)

    def poke(self):
        """Re-poll now (e.g. right after Macsist writes via the hermes CLI)."""
        self._wake.set()

    def _loop(self):
        self._emit()  # populate badge/tab immediately at startup
        while True:
            self._wake.wait(
                timeout=float(self.config.get("assistant_tick_interval"))
            )
            self._wake.clear()
            events, max_id = self.bridge.events_since(self._cursor)
            if events:
                self._cursor = max_id
                print(f"assistant: {len(events)} kanban event(s) -> id {max_id}",
                      flush=True)
                self._emit()

    def _emit(self):
        if self.on_change is not None:
            AppHelper.callAfter(self.on_change)


class ProactiveMonitor:
    """Wakes every assistant_proactive_interval and runs one engine.scan() on a
    worker thread (off-main LLM). scan() itself no-ops when proactivity is off,
    so this thread is cheap when disabled. poke() runs a cycle now (`macsist
    scan`). Stores are lock-guarded; the engine marshals UI callbacks to main.
    """

    def __init__(self, config, engine):
        self.config = config
        self.engine = engine
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if not bool(self.config.get("assistant_enabled")):
            return
        self._thread = threading.Thread(
            target=self._loop, name="assistant-proactive", daemon=True
        )
        self._thread.start()
        print("proactive monitor started", flush=True)

    def poke(self):
        self._wake.set()

    def _loop(self):
        while True:
            self._wake.wait(
                timeout=float(self.config.get("assistant_proactive_interval"))
            )
            self._wake.clear()
            try:
                self.engine.scan()
            except Exception as exc:  # never let the daemon thread die
                print(f"proactive monitor: scan error {exc!r}", flush=True)

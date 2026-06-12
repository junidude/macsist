"""ServerHealthMonitor — background /health polling for the menu bar (M5).

States: "unknown" (startup) → "ok" | "loading" | "down".
  ok      — proxy answered {"status": "ok"} (all expected backends ready)
  loading — proxy answered {"status": "loading"} (a backend is still loading
            its model; the supervisor guarantees "proxy up + backend
            unreachable" can only mean that)
  down    — the proxy itself is unreachable

Threading: one daemon thread, created once at startup. State changes are
marshalled to the main thread via AppHelper.callAfter before on_change fires
(the menu bar is AppKit). poke() wakes the loop early — called after a request
fails so the menu bar doesn't lag a full poll interval behind the panel.
"""

import threading

import httpx
from PyObjCTools import AppHelper


class ServerHealthMonitor:
    def __init__(self, config, on_change=None):
        self.config = config
        self.on_change = on_change  # called on the MAIN thread with the state
        self._state = "unknown"
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None

    @property
    def state(self):
        with self._lock:
            return self._state

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, name="health-monitor", daemon=True
        )
        self._thread.start()

    def poke(self):
        """Re-poll now (e.g. right after a request error)."""
        self._wake.set()

    def _loop(self):
        while True:
            state = self._poll_once()
            changed = False
            with self._lock:
                if state != self._state:
                    self._state = state
                    changed = True
            if changed:
                print(f"server state -> {state}", flush=True)
                if self.on_change is not None:
                    AppHelper.callAfter(self.on_change, state)
            self._wake.wait(timeout=float(self.config.get("health_poll_interval")))
            self._wake.clear()

    def _poll_once(self):
        # read config each poll so a server URL change applies live
        base_url = str(self.config.get("server_base_url")).rstrip("/")
        timeout = float(self.config.get("health_poll_timeout"))
        try:
            resp = httpx.get(f"{base_url}/health", timeout=timeout)
        except httpx.HTTPError:
            return "down"
        if resp.status_code != 200:
            return "down"
        try:
            status = resp.json().get("status")
        except ValueError:
            return "down"
        return "ok" if status == "ok" else "loading"

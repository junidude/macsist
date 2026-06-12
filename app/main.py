"""HotkeyExplain entry point.

Accessory activation policy = LSUIElement equivalent: no Dock icon, menu bar only.
"""

import os
import sys

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSWorkspace
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
from Foundation import NSObject, NSTimer, NSURL
from PyObjCTools import AppHelper

from explain_controller import URL_PANE_ACCESSIBILITY

from config import ConfigStore
from explain_controller import ExplainController
from health import ServerHealthMonitor
from history_store import HistoryStore
from menubar import StatusItemController
from result_panel import ResultPanelController

# Keep module-level references so the controllers outlive main().
_controller = None
_explain = None
_health = None
_ax_waiter = None


class _AXGrantWaiter(NSObject):
    """Poll AXIsProcessTrusted after the startup prompt (M5 onboarding).

    An Accessory app gets no meaningful focus events, so a 2-second timer is
    the "re-check on focus" mechanism. The grant only reaches pynput's event
    tap in a fresh process (SPEC §7.8), and without it the hotkeys are dead
    anyway — so on detection we exec-relaunch in place (same PID, launchd
    KeepAlive unaffected; works for dev runs too)."""

    def check_(self, timer):
        if not AXIsProcessTrusted():
            return
        timer.invalidate()
        print("Accessibility granted — relaunching to attach the event tap.",
              flush=True)
        os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    global _controller, _explain, _health, _ax_waiter
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    if not AXIsProcessTrusted():
        # Without Accessibility the hotkey tap receives nothing, so the user
        # could never reach the in-panel permission message — prompt up front
        # (registers this python in System Settings), open the exact pane,
        # and wait for the grant: _AXGrantWaiter relaunches us when it lands.
        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        NSWorkspace.sharedWorkspace().openURL_(
            NSURL.URLWithString_(URL_PANE_ACCESSIBILITY)
        )
        _ax_waiter = _AXGrantWaiter.alloc().init()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.0, _ax_waiter, "check:", None, True
        )
        print("Accessibility not granted — system prompt + settings pane "
              "shown; will auto-relaunch once granted.", flush=True)
    config = ConfigStore()
    history = HistoryStore(config)
    _controller = StatusItemController.alloc().initWithConfig_history_(
        config, history
    )
    panel = ResultPanelController.alloc().initWithConfig_(config)
    _health = ServerHealthMonitor(config, on_change=_controller.setServerState_)
    _explain = ExplainController(config, panel, health_monitor=_health,
                                 history=history)
    _health.start()
    _explain.start()
    main_window = _controller.main_window
    main_window.settings.on_saved = _explain.reloadHotkeys
    main_window.settings.on_record_changed = _explain.pauseHotkeys_
    main_window.on_reask = _explain.resubmit_text
    print("HotkeyExplain started (menu bar). Config:", str(config.get("server_base_url")))
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()

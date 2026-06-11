"""HotkeyExplain entry point.

Accessory activation policy = LSUIElement equivalent: no Dock icon, menu bar only.
"""

from AppKit import NSApplication, NSApplicationActivationPolicyAccessory
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
from PyObjCTools import AppHelper

from config import ConfigStore
from explain_controller import ExplainController
from menubar import StatusItemController
from result_panel import ResultPanelController

# Keep module-level references so the controllers outlive main().
_controller = None
_explain = None


def main():
    global _controller, _explain
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    if not AXIsProcessTrusted():
        # Without Accessibility the hotkey tap receives nothing, so the user
        # could never reach the in-panel permission message — prompt up front.
        # (Registers this python in System Settings; restart after granting.)
        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
        print("Accessibility not granted — system prompt shown; "
              "grant and restart the app.", flush=True)
    config = ConfigStore()
    _controller = StatusItemController.alloc().initWithConfig_(config)
    panel = ResultPanelController.alloc().initWithConfig_(config)
    _explain = ExplainController(config, panel)
    _explain.start()
    settings = _controller.settings_controller
    settings.on_saved = _explain.reloadHotkeys
    settings.on_record_changed = _explain.pauseHotkeys_
    print("HotkeyExplain started (menu bar). Config:", str(config.get("server_base_url")))
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()

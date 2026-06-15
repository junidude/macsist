"""Macsist entry point.

Accessory activation policy = LSUIElement equivalent: no Dock icon, menu bar only.
"""

import os
import sys

import objc

import i18n

from AppKit import (
    NSAppearance,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSColorSpace,
    NSWorkspace,
)
from ApplicationServices import AXIsProcessTrusted, AXIsProcessTrustedWithOptions
from Foundation import (
    NSDistributedNotificationCenter,
    NSObject,
    NSTimer,
    NSURL,
)
from Quartz import CGPreflightScreenCaptureAccess
from PyObjCTools import AppHelper

from explain_controller import URL_PANE_ACCESSIBILITY

from assistant.controller import AssistantController
from config import ConfigStore, asset_dir
from explain_controller import ExplainController
from health import ServerHealthMonitor
from history_store import HistoryStore
from menubar import StatusItemController
from result_panel import ResultPanelController

# Keep module-level references so the controllers outlive main().
_controller = None
_explain = None
_health = None
_assistant = None
_ax_waiter = None
_ui_auditor = None
_remote_relay = None


class _RemoteCommandRelay(NSObject):
    """`macsist settings|history` (M10) posts distributed notifications; the
    observer is registered on the main thread/runloop, so delivery is
    main-thread — safe to drive AppKit directly. The `remote:` lines are the
    greppable verification hook (app.log)."""

    def initWithMainWindow_(self, main_window):
        self = objc.super(_RemoteCommandRelay, self).init()
        if self is None:
            return None
        self._main_window = main_window
        return self

    def remoteShowSettings_(self, note):
        print("remote: showSettings", flush=True)
        self._main_window.showSettings()

    def remoteShowHistory_(self, note):
        print("remote: showHistory", flush=True)
        self._main_window.showHistory()

    def remoteAssistantShowTasks_(self, note):
        print("remote: assistant.showTasks", flush=True)
        self._main_window.showAssistant()


class _UIAuditor(NSObject):
    """HE_DEBUG_UI_AUDIT=<sec>: repeating structured dump of the panel and
    main-window chrome (M8) — this bundle-less app cannot be screenshot, so
    glass/fade/light-dark verification greps these lines."""

    def audit_(self, timer):
        try:
            self._auditPanel()
            self._auditMainWindow()
        except Exception as exc:  # an audit must never crash the app
            print(f"ui-audit error: {exc!r}", flush=True)

    def _resolvedSeparatorRGBA_(self, view):
        holder = {}

        def _resolve():
            holder["c"] = NSColor.separatorColor().colorUsingColorSpace_(
                NSColorSpace.sRGBColorSpace()
            )

        view.effectiveAppearance().performAsCurrentDrawingAppearance_(_resolve)
        c = holder["c"]
        return (
            f"{c.redComponent():.3f},{c.greenComponent():.3f},"
            f"{c.blueComponent():.3f},{c.alphaComponent():.3f}"
        )

    def _auditPanel(self):
        rp = _explain.panel
        if rp.panel is None:
            print("ui-audit panel: not built", flush=True)
            return
        from result_panel import _HairlineEffectView

        backdrop = rp._backdrop
        cls = type(backdrop).__name__
        if not isinstance(backdrop, _HairlineEffectView):
            # glass path (hasattr cornerRadius is useless — NSView has a
            # private accessor of the same name that returns 0)
            radius = float(backdrop.cornerRadius())
            border = "n/a"
            curve = "glass"
        else:
            layer = backdrop.layer()
            radius = float(layer.cornerRadius())
            border = (
                f"{float(layer.borderWidth()):g}px "
                f"rgba({self._resolvedSeparatorRGBA_(backdrop)})"
            )
            curve = str(layer.cornerCurve())
        f = rp.panel.frame()
        print(
            f"ui-audit panel: backdrop={cls} radius={radius:g} "
            f"border={border} curve={curve} "
            f"alpha={float(rp.panel.alphaValue()):.2f} "
            f"visible={bool(rp.panel.isVisible())} "
            f"key={bool(rp.panel.isKeyWindow())} "
            f"frame=({f.origin.x:.0f},{f.origin.y:.0f},"
            f"{f.size.width:.0f},{f.size.height:.0f}) "
            f"appearance={rp.panel.effectiveAppearance().name()}",
            flush=True,
        )

    def _auditMainWindow(self):
        mw = _controller.main_window
        if mw.window is None:
            print("ui-audit window: not built", flush=True)
            return
        toolbar = mw.window.toolbar()
        items = (
            ",".join(str(i.itemIdentifier()) for i in toolbar.items())
            if toolbar is not None else "none"
        )
        from AppKit import NSVisualEffectView

        sidebar = getattr(mw, "sidebar_effect", None)
        if sidebar is None:
            sidebar_desc = "none"
        elif isinstance(sidebar, NSVisualEffectView):
            sidebar_desc = (
                f"{type(sidebar).__name__} material={int(sidebar.material())}"
            )
        else:  # glass island
            sidebar_desc = (
                f"{type(sidebar).__name__} "
                f"radius={float(sidebar.cornerRadius()):g}"
            )
        print(
            f"ui-audit window: toolbar=[{items}] "
            f"toolbarStyle={int(mw.window.toolbarStyle())} "
            f"sidebar={sidebar_desc} "
            f"tabType={int(mw.tab_view.tabViewType())} "
            f"visible={bool(mw.window.isVisible())} "
            f"appearance={mw.window.effectiveAppearance().name()}",
            flush=True,
        )


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
        # In the bundle (M12), sys.executable is the embedded CLI interpreter
        # (Contents/MacOS/python), NOT the app stub — exec'ing it would lose
        # the bundle identity. The py2app launcher exports EXECUTABLEPATH
        # (Contents/MacOS/Macsist); exec-in-place keeps the PID, so launchd
        # KeepAlive is unaffected either way.
        exe = os.environ.get("EXECUTABLEPATH")
        if exe:
            os.execv(exe, [exe])
        else:  # dev run (app/run.sh)
            os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    global _controller, _explain, _health, _assistant
    global _ax_waiter, _ui_auditor, _remote_relay
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    # Machine-readable TCC probe for install.sh / `macsist doctor` (M10):
    # shell-side AXIsProcessTrusted checks attribute to the terminal, not this
    # binary, so the app reports its own grant state on every (re)start.
    # CGPreflightScreenCaptureAccess never prompts.
    print(
        f"TCC: accessibility={bool(AXIsProcessTrusted())} "
        f"screen_recording={bool(CGPreflightScreenCaptureAccess())}",
        flush=True,
    )
    # Dock icon (user asset) — shown while the History window has the app in
    # Regular policy; a bundle-less python process has no Info.plist icon.
    icns = asset_dir() / "macsist.icns"
    if icns.exists():
        from AppKit import NSImage
        icon = NSImage.alloc().initWithContentsOfFile_(str(icns))
        if icon is not None:
            app.setApplicationIconImage_(icon)
            print("dock icon set:", icns.name, flush=True)
    # M8 verification: pin the appearance so light/dark runs are reproducible
    forced = os.environ.get("HE_DEBUG_FORCE_APPEARANCE")
    if forced in ("light", "dark"):
        app.setAppearance_(NSAppearance.appearanceNamed_(
            NSAppearanceNameDarkAqua if forced == "dark"
            else NSAppearanceNameAqua
        ))
        print(f"HE_DEBUG_FORCE_APPEARANCE={forced}", flush=True)
    # HE_DEBUG_SKIP_AX_PROMPT: the installer's foreground smoke run uses
    # HE_DEBUG_FAKE_TEXT (no capture, no TCC) — don't pop the system
    # Accessibility dialog in the terminal's name during it.
    if (not AXIsProcessTrusted()
            and not os.environ.get("HE_DEBUG_SKIP_AX_PROMPT")):
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
    # M11: resolve the UI/output language BEFORE any controller builds labels
    i18n.set_language(str(config.get("language")))
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

    def _settings_saved():
        _explain.reloadHotkeys()
        panel.markDirty()  # panel size/font/glass apply on the next session
        new_lang = str(config.get("language"))
        if new_lang != i18n.current_language():
            # M11 live language switch: menubar relabels synchronously; the
            # window rebuild is deferred — the Save action lives inside the
            # very hierarchy rebuildContent tears down.
            i18n.set_language(new_lang)
            _controller.relabel()
            AppHelper.callAfter(main_window.rebuildContent)

    main_window.settings.on_saved = _settings_saved
    main_window.settings.on_record_changed = _explain.pauseHotkeys_
    main_window.on_reask = _explain.resubmit_text
    main_window.on_reask_image = _explain.resubmit_image
    _explain.on_open_history = main_window.toggleHistory
    # M13: assistant subsystem — read-only kanban cockpit + menu-bar badge.
    # Constructed after the menu bar/window exist; wires the board monitor to
    # the badge + 작업 tab. The proactive engine arrives in M14.
    _assistant = AssistantController(config, _controller, main_window)
    _assistant.start()
    # M10: `macsist settings|history` IPC (distributed notifications).
    _remote_relay = _RemoteCommandRelay.alloc().initWithMainWindow_(main_window)
    dist_center = NSDistributedNotificationCenter.defaultCenter()
    dist_center.addObserver_selector_name_object_(
        _remote_relay, "remoteShowSettings:", "com.macsist.showSettings", None
    )
    dist_center.addObserver_selector_name_object_(
        _remote_relay, "remoteShowHistory:", "com.macsist.showHistory", None
    )
    dist_center.addObserver_selector_name_object_(
        _remote_relay, "remoteAssistantShowTasks:",
        "com.macsist.assistant.showTasks", None
    )
    # M11 hook: switch the language like a Settings save would, at given
    # times — live-switch verification. Format: "<sec>:<code>[,<sec>:<code>…]"
    switches = os.environ.get("HE_DEBUG_SET_LANGUAGE")
    if switches:
        def switch_language(code):
            config.set("language", code)
            config.save()
            _settings_saved()

        import threading as _threading
        for item in switches.split(","):
            delay, _, code = item.partition(":")
            timer = _threading.Timer(
                float(delay),
                lambda code=code: AppHelper.callAfter(switch_language, code),
            )
            timer.daemon = True
            timer.start()
        print(f"HE_DEBUG_SET_LANGUAGE: {switches}", flush=True)
    audit = os.environ.get("HE_DEBUG_UI_AUDIT")
    if audit:
        _ui_auditor = _UIAuditor.alloc().init()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            float(audit), _ui_auditor, "audit:", None, True
        )
        print(f"HE_DEBUG_UI_AUDIT: every {audit}s", flush=True)
    # M13: first run of a downloaded .app — guide the user to pick a backend
    # (external API / local). No-op once onboarded; install.sh marks it done.
    AppHelper.callAfter(main_window.runOnboardingIfNeeded)
    provider = config.active_provider()
    print(
        "Macsist started (menu bar). Provider:",
        f"{provider['name']} ({provider['base_url']})",
    )
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()

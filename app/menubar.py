"""StatusItemController — menu bar status item and menu."""

import objc
from AppKit import (
    NSImage,
    NSMenu,
    NSMenuItem,
    NSObject,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSMakeSize

from config import asset_dir
from i18n import current_language, t
from main_window import MainWindowController

# server state → (SF Symbol, title fallback, status-line i18n key)
_SERVER_STATES = {
    "unknown": ("text.bubble", "M", "menubar.server_unknown"),
    "ok":      ("text.bubble", "M", "menubar.server_ok"),
    "loading": ("ellipsis.bubble", "M…", "menubar.server_loading"),
    "down":    ("exclamationmark.bubble", "M!", "menubar.server_down"),
}

_MENUBAR_ICON_PATH = asset_dir() / "macsist-menubarTemplate.pdf"


def _load_menubar_icon():
    """The custom Macsist template icon (user asset) — shown while the
    server is healthy; alert states keep their SF-Symbol bubbles so the
    at-a-glance state survives (M5 AC)."""
    if not _MENUBAR_ICON_PATH.exists():
        return None
    icon = NSImage.alloc().initWithContentsOfFile_(str(_MENUBAR_ICON_PATH))
    if icon is None:
        return None
    icon.setSize_(NSMakeSize(18.0, 18.0))
    icon.setTemplate_(True)  # adapts to light/dark menu bars
    return icon


class StatusItemController(NSObject):
    def initWithConfig_history_(self, config, history):
        self = objc.super(StatusItemController, self).init()
        if self is None:
            return None
        self.config = config
        self.main_window = MainWindowController.alloc().initWithConfig_history_(
            config, history
        )

        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )

        menu = NSMenu.alloc().init()
        self.server_status_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "", None, ""
        )
        self.server_status_item.setEnabled_(False)
        menu.addItem_(self.server_status_item)
        menu.addItem_(NSMenuItem.separatorItem())
        self.history_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            t("menubar.history"), "openHistory:", "h"
        )
        self.history_item.setTarget_(self)
        menu.addItem_(self.history_item)
        self.settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            t("menubar.settings"), "openSettings:", ","
        )
        self.settings_item.setTarget_(self)
        menu.addItem_(self.settings_item)
        # 비서 (M13): read-only cockpit submenu + open-count badge on the parent
        menu.addItem_(NSMenuItem.separatorItem())
        self._assistant_badge = 0
        self.assistant_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            t("menubar.assistant"), None, ""
        )
        assistant_menu = NSMenu.alloc().init()
        self.assistant_inbox_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            t("menubar.assistant_inbox"), "openAssistant:", ""
        )
        self.assistant_inbox_item.setTarget_(self)
        assistant_menu.addItem_(self.assistant_inbox_item)
        self.assistant_tasks_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            t("menubar.assistant_tasks"), "openAssistant:", ""
        )
        self.assistant_tasks_item.setTarget_(self)
        assistant_menu.addItem_(self.assistant_tasks_item)
        self.assistant_item.setSubmenu_(assistant_menu)
        menu.addItem_(self.assistant_item)
        menu.addItem_(NSMenuItem.separatorItem())
        self.quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            t("menubar.quit"), "terminate:", "q"
        )
        menu.addItem_(self.quit_item)
        self.status_item.setMenu_(menu)
        self._server_state = "unknown"
        self.setServerState_("unknown")

        import os
        if os.environ.get("HE_DEBUG_FRAME"):
            from Foundation import NSTimer
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, self, "debugLogFrame:", None, False
            )
        if os.environ.get("HE_DEBUG_OPEN_MENU"):
            from Foundation import NSTimer
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                15.0, self, "debugOpenMenu:", None, True
            )
        open_settings = os.environ.get("HE_DEBUG_OPEN_SETTINGS")
        if open_settings:
            from Foundation import NSTimer
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                float(open_settings), self, "openSettings:", None, False
            )
        open_history = os.environ.get("HE_DEBUG_OPEN_HISTORY")
        if open_history:
            from Foundation import NSTimer
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                float(open_history), self, "openHistory:", None, False
            )
        return self

    def debugOpenMenu_(self, timer):
        self.status_item.button().performClick_(None)

    def debugLogFrame_(self, timer):
        from AppKit import NSScreen
        print(
            "status item frame:", self.status_item.button().window().frame(),
            "| screen:", NSScreen.mainScreen().frame(),
            flush=True,
        )

    def relabel(self):
        """Re-resolve every menu title after a language change (M11)."""
        self.history_item.setTitle_(t("menubar.history"))
        self.settings_item.setTitle_(t("menubar.settings"))
        self.assistant_inbox_item.setTitle_(t("menubar.assistant_inbox"))
        self.assistant_tasks_item.setTitle_(t("menubar.assistant_tasks"))
        self.updateAssistantBadge_(self._assistant_badge)
        self.quit_item.setTitle_(t("menubar.quit"))
        self.setServerState_(self._server_state)
        print(f"menubar relabeled lang={current_language()}", flush=True)

    def setServerState_(self, state):
        """Main thread (health monitor marshals through callAfter)."""
        self._server_state = state
        symbol, fallback, status_key = _SERVER_STATES.get(
            state, _SERVER_STATES["unknown"]
        )
        self.server_status_item.setTitle_(t(status_key))
        # healthy → the custom Macsist icon; loading/down keep the SF-Symbol
        # alert bubbles so the state is visible at a glance (M5 AC)
        icon = None
        if state in ("ok", "unknown"):
            icon = _load_menubar_icon()
        if icon is None:
            icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, "Macsist"
            )
            if icon is not None:
                icon.setTemplate_(True)
        button = self.status_item.button()
        if icon is not None:
            button.setImage_(icon)
            button.setTitle_("")
        else:
            button.setImage_(None)
            button.setTitle_(fallback)

    def updateAssistantBadge_(self, count):
        """Main thread (AssistantMonitor marshals via callAfter). Show the
        open-task count on the 비서 menu — M13 mirrors the kanban board; M14
        will count pending confirm/never_auto proposals instead."""
        self._assistant_badge = int(count)
        title = t("menubar.assistant")
        if self._assistant_badge > 0:
            title = f"{title} ({self._assistant_badge})"
        self.assistant_item.setTitle_(title)

    def openSettings_(self, sender):
        self.main_window.showSettings()

    def openHistory_(self, sender):
        self.main_window.showHistory()

    def openAssistant_(self, sender):
        self.main_window.showAssistant()

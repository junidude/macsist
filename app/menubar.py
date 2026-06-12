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

from main_window import MainWindowController

# server state → (SF Symbol, title fallback, status-line text)
_SERVER_STATES = {
    "unknown": ("text.bubble", "M", "서버: 확인 중…"),
    "ok":      ("text.bubble", "M", "서버: 정상"),
    "loading": ("ellipsis.bubble", "M…", "서버: 모델 로딩 중…"),
    "down":    ("exclamationmark.bubble", "M!", "서버: 연결 안 됨"),
}


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
        history_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "History…", "openHistory:", "h"
        )
        history_item.setTarget_(self)
        menu.addItem_(history_item)
        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings…", "openSettings:", ","
        )
        settings_item.setTarget_(self)
        menu.addItem_(settings_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit Macsist", "terminate:", "q"
            )
        )
        self.status_item.setMenu_(menu)
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

    def setServerState_(self, state):
        """Main thread (health monitor marshals through callAfter)."""
        symbol, fallback, status_line = _SERVER_STATES.get(
            state, _SERVER_STATES["unknown"]
        )
        self.server_status_item.setTitle_(status_line)
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            symbol, "Macsist"
        )
        button = self.status_item.button()
        if icon is not None:
            icon.setTemplate_(True)
            button.setImage_(icon)
            button.setTitle_("")
        else:
            button.setImage_(None)
            button.setTitle_(fallback)

    def openSettings_(self, sender):
        self.main_window.showSettings()

    def openHistory_(self, sender):
        self.main_window.showHistory()

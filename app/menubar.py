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

from settings_window import SettingsWindowController


class StatusItemController(NSObject):
    def initWithConfig_(self, config):
        self = objc.super(StatusItemController, self).init()
        if self is None:
            return None
        self.config = config
        self.settings_controller = SettingsWindowController.alloc().initWithConfig_(config)

        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "text.bubble", "HotkeyExplain"
        )
        if icon is not None:
            icon.setTemplate_(True)
            self.status_item.button().setImage_(icon)
        else:
            self.status_item.button().setTitle_("HE")

        menu = NSMenu.alloc().init()
        settings_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Settings…", "openSettings:", ","
        )
        settings_item.setTarget_(self)
        menu.addItem_(settings_item)
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(
            NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Quit HotkeyExplain", "terminate:", "q"
            )
        )
        self.status_item.setMenu_(menu)

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

    def openSettings_(self, sender):
        self.settings_controller.show()

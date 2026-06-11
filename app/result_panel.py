"""ResultPanel — non-activating floating panel that streams the explanation.

Hard rule: must never steal focus from the source app. The NonactivatingPanel
mask alone is not enough — such a panel can still become key when clicked — so
the subclass refuses key/main outright and the panel is only ever shown with
orderFrontRegardless().

All methods are main-thread only (callers marshal via AppHelper.callAfter).
"""

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSEventTypeKeyDown,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSObject,
    NSPanel,
    NSScreen,
    NSTextView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import (
    NSAttributedString,
    NSMakePoint,
    NSMakeRange,
    NSMakeRect,
    NSMakeSize,
    NSPointInRect,
)

_ESC_KEYCODE = 53
_PADDING = 10.0


class _NonActivatingPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


class ResultPanelController(NSObject):
    def initWithConfig_(self, config):
        self = objc.super(ResultPanelController, self).init()
        if self is None:
            return None
        self.config = config
        self.panel = None
        self.text_view = None
        self.on_dismiss = None  # set by ExplainController: cancels the stream
        self._placeholder = False
        self._global_monitor = None
        self._local_monitor = None
        self._text_attrs = None
        self._message_attrs = None
        return self

    # -- public API (main thread) ------------------------------------------

    def beginSessionAt_(self, cursor_tl):
        """Clear, reposition near the cursor, show a streaming placeholder."""
        self._presentAt_(cursor_tl)
        self._setText_attrs_("…", self._message_attrs)
        self._placeholder = True

    def appendChunk_(self, chunk):
        if self._placeholder:
            self._setText_attrs_("", self._text_attrs)
            self._placeholder = False
        storage = self.text_view.textStorage()
        storage.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                chunk, self._text_attrs
            )
        )
        self.text_view.scrollRangeToVisible_(NSMakeRange(storage.length(), 0))

    def showThinking_(self, char_count):
        """Quiet placeholder update while a thinking model reasons (no log
        spam — this fires per reasoning token). First content chunk replaces it."""
        if self._placeholder:
            self._setText_attrs_(f"생각 중… ({char_count}자)", self._message_attrs)

    def showMessageAt_text_(self, cursor_tl, message):
        """One-line status (empty selection, missing permission, LLM error)."""
        self._presentAt_(cursor_tl)
        self.showErrorText_(message)

    def showErrorText_(self, message):
        self._setText_attrs_(message, self._message_attrs)
        self._placeholder = False
        print("panel message:", message, flush=True)

    def finishStream(self):
        print(
            "stream finished, panel text:",
            repr(str(self.text_view.string())[:120]),
            flush=True,
        )

    def dismiss(self):
        """User-initiated dismiss (Esc / click-away) — also stops the stream."""
        self._remove_monitors()
        if self.panel is not None and self.panel.isVisible():
            self.panel.orderOut_(None)
            print("panel dismissed", flush=True)
        if self.on_dismiss is not None:
            self.on_dismiss()

    # -- panel construction --------------------------------------------------

    def _buildPanel(self):
        width = float(self.config.get("panel_width"))
        height = float(self.config.get("panel_height"))
        panel = _NonActivatingPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        panel.setLevel_(NSFloatingWindowLevel)
        # Panels default to hidesOnDeactivate=True and an Accessory app
        # deactivates constantly — without this the panel vanishes immediately.
        panel.setHidesOnDeactivate_(False)
        panel.setReleasedWhenClosed_(False)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setHasShadow_(True)

        effect = NSVisualEffectView.alloc().initWithFrame_(
            NSMakeRect(0, 0, width, height)
        )
        effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
        effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        effect.setState_(NSVisualEffectStateActive)
        effect.setWantsLayer_(True)
        effect.layer().setCornerRadius_(10.0)
        effect.layer().setMasksToBounds_(True)
        panel.setContentView_(effect)

        scroll = NSTextView.scrollableTextView()
        scroll.setFrame_(
            NSMakeRect(
                _PADDING, _PADDING, width - 2 * _PADDING, height - 2 * _PADDING
            )
        )
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        scroll.setDrawsBackground_(False)
        effect.addSubview_(scroll)

        text_view = scroll.documentView()
        text_view.setEditable_(False)
        text_view.setSelectable_(True)
        text_view.setDrawsBackground_(False)
        text_view.setTextContainerInset_(NSMakeSize(4, 4))

        self._text_attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
            NSForegroundColorAttributeName: NSColor.labelColor(),
        }
        self._message_attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(13.0),
            NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
        }
        self.panel = panel
        self.text_view = text_view

    # -- presentation ---------------------------------------------------------

    def _presentAt_(self, cursor_tl):
        """cursor_tl: (x, y) in CG top-left-origin global coords (from the
        pynput thread via CGEventGetLocation). Reuses the single panel instance
        — a new panel per request would leak monitors and risk PyObjC lifetime
        bugs. Deliberately does NOT route through dismiss(): dismiss() cancels
        the in-flight stream, which would kill the request being presented."""
        if self.panel is None:
            self._buildPanel()
        x, y_tl = cursor_tl
        # AppKit's global coordinate space is bottom-left-origin, flipped
        # against the primary screen (screens()[0]), not the cursor's screen.
        primary = NSScreen.screens()[0]
        y = primary.frame().size.height - y_tl
        point = NSMakePoint(x, y)

        screen = self._screenForPoint_(point)
        vf = screen.visibleFrame()
        offset = float(self.config.get("panel_cursor_offset"))
        size = self.panel.frame().size
        ox = x + offset
        oy = y - offset - size.height  # panel top sits just below the cursor
        ox = max(vf.origin.x, min(ox, vf.origin.x + vf.size.width - size.width))
        oy = max(vf.origin.y, min(oy, vf.origin.y + vf.size.height - size.height))
        self.panel.setFrameOrigin_(NSMakePoint(ox, oy))
        self.panel.orderFrontRegardless()  # never makeKeyAndOrderFront
        self._install_monitors()
        print(
            f"panel shown at ({ox:.0f},{oy:.0f}) "
            f"size=({size.width:.0f}x{size.height:.0f})",
            flush=True,
        )

    def _screenForPoint_(self, point):
        for screen in NSScreen.screens():
            if NSPointInRect(point, screen.frame()):
                return screen
        return NSScreen.mainScreen()

    def _setText_attrs_(self, text, attrs):
        self.text_view.textStorage().setAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        )

    # -- dismiss monitors -----------------------------------------------------
    # The panel is never key, so it receives no keyDown directly; global+local
    # NSEvent monitors are the standard idiom for a never-key window. The
    # global keyDown monitor needs Accessibility (already required for AX
    # capture) and cannot consume the event — Esc also reaches the front app
    # (accepted for M2).

    def _install_monitors(self):
        import os
        if os.environ.get("HE_DEBUG_KEEP_PANEL"):
            return  # verification: panel stays up while the user keeps clicking
        if self._global_monitor is not None:
            return
        mask = (
            NSEventMaskKeyDown
            | NSEventMaskLeftMouseDown
            | NSEventMaskRightMouseDown
        )
        self._global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            mask, self._handleGlobalEvent_
        )
        self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            mask, self._handleLocalEvent_
        )

    def _remove_monitors(self):
        if self._global_monitor is not None:
            NSEvent.removeMonitor_(self._global_monitor)
            self._global_monitor = None
        if self._local_monitor is not None:
            NSEvent.removeMonitor_(self._local_monitor)
            self._local_monitor = None

    def _handleGlobalEvent_(self, event):
        self._maybeDismissForEvent_(event)

    def _handleLocalEvent_(self, event):
        self._maybeDismissForEvent_(event)
        return event  # pass the event through

    def _maybeDismissForEvent_(self, event):
        if event.type() == NSEventTypeKeyDown:
            if event.keyCode() == _ESC_KEYCODE:
                self.dismiss()
            return
        # mouse: ignore clicks inside the panel itself
        if not NSPointInRect(NSEvent.mouseLocation(), self.panel.frame()):
            self.dismiss()

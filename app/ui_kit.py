"""Shared M8 UI pieces: pill buttons (Codex-style) and a flipped container.

Lives in its own module so both MainWindowController and
SettingsPaneController can use them (main_window imports settings_window,
so settings_window must not import main_window back).
"""

import objc
from AppKit import (
    NSApplication,
    NSBox,
    NSBoxCustom,
    NSButton,
    NSColor,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSFocusRingTypeNone,
    NSFont,
    NSSecureTextField,
    NSTextField,
    NSTrackingActiveAlways,
    NSTrackingArea,
    NSTrackingInVisibleRect,
    NSTrackingMouseEnteredAndExited,
    NSView,
)
from Foundation import NSMakeRect, NSMakeSize

FONT_BODY = 15.0  # 13 × 1.15 (M8 scale-up)
FONT_UI = 14.0  # buttons, switch labels, row titles
FONT_SMALL = 12.0  # captions, descriptions


# Standard editing key equivalents (⌘A select-all, ⌘C/⌘V/⌘X copy/paste/cut,
# ⌘Z/⇧⌘Z undo/redo) for text fields. These are the Edit-menu-driven actions;
# navigation/selection (arrows, ⌥/⌘+arrows, ⇧-selection) already work via the
# text system's default key bindings. An Accessory app has no Edit menu to
# provide the menu actions, and NSMenu key equivalents match by *character*
# anyway — which breaks under the Korean 2-set layout (⌘C reports 'ㅊ', hard
# rule #1). So we match by virtual keycode and drive the actions down the
# responder chain ourselves. keyCodes are kVK_ANSI_* : A=0, C=8, V=9, X=7, Z=6.
_EDIT_ACTION_BY_KEYCODE = {0: "selectAll:", 8: "copy:", 9: "paste:", 7: "cut:"}
_KEYCODE_Z = 6


def _focused_undo_manager(window):
    responder = window.firstResponder()
    manager = responder.undoManager() if responder is not None else None
    # NSTextField's field editor registers edits with the window's manager;
    # a standalone NSTextView (settings prompt areas) owns its own.
    return manager if manager is not None else window.undoManager()


def handle_edit_key_equivalent(window, event):
    """Route ⌘A/⌘C/⌘V/⌘X/⌘Z/⇧⌘Z to the window's focused text field. Returns
    True if consumed. Call first from a window/panel's performKeyEquivalent_."""
    flags = event.modifierFlags()
    if not (flags & NSEventModifierFlagCommand):
        return False
    # leave ⌥/⌃ combos alone — only the bare ⌘ (+⇧ for redo) shortcuts here
    if flags & (NSEventModifierFlagOption | NSEventModifierFlagControl):
        return False
    code = event.keyCode()
    action = _EDIT_ACTION_BY_KEYCODE.get(code)
    if action is not None:
        # target nil → starts at the firstResponder (the field editor)
        return bool(NSApplication.sharedApplication().sendAction_to_from_(
            action, None, window))
    if code == _KEYCODE_Z:
        manager = _focused_undo_manager(window)
        if manager is None:
            return False
        if flags & NSEventModifierFlagShift:
            if manager.canRedo():
                manager.redo()
        elif manager.canUndo():
            manager.undo()
        return True
    return False


class FlippedView(NSView):
    """Top-down container (chat transcripts, settings cards)."""

    def isFlipped(self):
        return True


class PillButton(NSButton):
    """Borderless rounded pill button with a hover tint (Codex-style, user
    feedback). Fill is re-resolved on hover and appearance changes."""

    _hover = False
    _tracking = None

    def updateTrackingAreas(self):
        objc.super(PillButton, self).updateTrackingAreas()
        if self._tracking is not None:
            self.removeTrackingArea_(self._tracking)
        self._tracking = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
            self.bounds(),
            NSTrackingMouseEnteredAndExited
            | NSTrackingActiveAlways
            | NSTrackingInVisibleRect,
            self, None,
        )
        self.addTrackingArea_(self._tracking)

    def mouseEntered_(self, event):
        self._hover = True
        self.refreshFill()

    def mouseExited_(self, event):
        self._hover = False
        self.refreshFill()

    def viewDidChangeEffectiveAppearance(self):
        objc.super(PillButton, self).viewDidChangeEffectiveAppearance()
        self.refreshFill()

    def refreshFill(self):
        def _apply():
            alpha = 0.16 if self._hover else 0.07
            self.layer().setBackgroundColor_(
                NSColor.labelColor().colorWithAlphaComponent_(alpha).CGColor()
            )
        self.effectiveAppearance().performAsCurrentDrawingAppearance_(_apply)


def make_round_field(frame, font_size=14.0, secure=False):
    """ChatGPT-style input: borderless text field on a rounded gray box.
    Returns (box, field) — add the box to the view tree, talk to the field.
    NSBox re-resolves its semantic fill on appearance changes.
    secure=True swaps in NSSecureTextField (M9 API-key entry)."""
    box = NSBox.alloc().initWithFrame_(frame)
    box.setBoxType_(NSBoxCustom)
    box.setTitlePosition_(0)
    box.setBorderWidth_(0.0)
    box.setCornerRadius_(9.0)
    box.setContentViewMargins_(NSMakeSize(0, 0))
    box.setFillColor_(NSColor.labelColor().colorWithAlphaComponent_(0.06))
    field_h = font_size + 6.0
    field_class = NSSecureTextField if secure else NSTextField
    field = field_class.alloc().initWithFrame_(
        NSMakeRect(10, (frame.size.height - field_h) / 2.0,
                   frame.size.width - 20, field_h)
    )
    field.setBezeled_(False)
    field.setBordered_(False)
    field.setDrawsBackground_(False)
    field.setFocusRingType_(NSFocusRingTypeNone)
    field.setFont_(NSFont.systemFontOfSize_(font_size))
    box.contentView().addSubview_(field)
    return box, field


def make_pill(title, target, action, frame):
    button = PillButton.alloc().initWithFrame_(frame)
    button.setTitle_(title)
    button.setTarget_(target)
    button.setAction_(action)
    button.setBordered_(False)
    button.setWantsLayer_(True)
    button.layer().setCornerRadius_(frame.size.height / 2.0)
    button.layer().setMasksToBounds_(True)
    button.setFont_(NSFont.systemFontOfSize_(FONT_UI))
    button.refreshFill()
    return button

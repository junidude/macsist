"""Shared M8 UI pieces: pill buttons (Codex-style) and a flipped container.

Lives in its own module so both MainWindowController and
SettingsPaneController can use them (main_window imports settings_window,
so settings_window must not import main_window back).
"""

import objc
from AppKit import (
    NSBox,
    NSBoxCustom,
    NSButton,
    NSColor,
    NSFocusRingTypeNone,
    NSFont,
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


def make_round_field(frame, font_size=14.0):
    """ChatGPT-style input: borderless text field on a rounded gray box.
    Returns (box, field) — add the box to the view tree, talk to the field.
    NSBox re-resolves its semantic fill on appearance changes."""
    box = NSBox.alloc().initWithFrame_(frame)
    box.setBoxType_(NSBoxCustom)
    box.setTitlePosition_(0)
    box.setBorderWidth_(0.0)
    box.setCornerRadius_(9.0)
    box.setContentViewMargins_(NSMakeSize(0, 0))
    box.setFillColor_(NSColor.labelColor().colorWithAlphaComponent_(0.06))
    field_h = font_size + 6.0
    field = NSTextField.alloc().initWithFrame_(
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

"""ProposalPanelController — the confirm surface for proposals (M14, M17 redesign).

A non-activating floating **glass** card (result_panel rules: canBecomeKeyWindow
False, setHidesOnDeactivate_(False), orderFrontRegardless — NEVER steals focus,
the app never activates). It uses the same Liquid-Glass backdrop as the result
panel so it reads as part of the app, not a stark white box.

The card shows everything needed to decide:
  · a risk-colored, vertically-centred badge + source
  · the title (primary) and the rationale (secondary)
  · for mail proposals (reply_draft / send_reply): the **recipient + subject +
    the actual draft body** in a scrollable text view — you can't confirm a send
    you can't read.
Pill buttons (승인 / 지금 보내기 = accent · 건너뛰기 / 나중에 = subtle). Sizes to
its content; advances to the next pending proposal after an action, or hides.
"""

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezelStyleRegularSquare,
    NSBox,
    NSBoxCustom,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSMakeSize,
    NSMutableParagraphStyle,
    NSPanel,
    NSParagraphStyleAttributeName,
    NSScreen,
    NSScrollView,
    NSTextAlignmentCenter,
    NSTextField,
    NSTextView,
    NSView,
    NSViewHeightSizable,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSAttributedString, NSMakeRect, NSObject
from ui_kit import PillButton, handle_edit_key_equivalent, make_round_field

from assistant import risk
from i18n import t

try:
    _Glass = objc.lookUpClass("NSGlassEffectView")
except objc.error:
    _Glass = None

_W = 460.0
_PAD = 22.0
_BODY_H = 188.0          # visible height of the scrollable draft body
_MAIL_KINDS = ("reply_draft", "send_reply")
_RISK_COLOR = {
    risk.AUTO: (0.20, 0.66, 0.33),
    risk.CONFIRM: (0.95, 0.62, 0.11),
    risk.NEVER_AUTO: (0.90, 0.28, 0.28),
}
_RISK_LABEL_KEY = {
    risk.AUTO: "assistant.risk_auto",
    risk.CONFIRM: "assistant.risk_confirm",
    risk.NEVER_AUTO: "assistant.risk_never",
}


def _pill(target, title, action, x, y, w, h, fill, text_color):
    """A hover-tinted rounded pill (ui_kit.PillButton) with a fixed fill for the
    accent action; subtle buttons inherit PillButton's label-tint hover."""
    b = PillButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    b.setBordered_(False)
    b.setBezelStyle_(NSBezelStyleRegularSquare)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(h / 2.0)
    b.layer().setMasksToBounds_(True)
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSTextAlignmentCenter)
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {
            NSForegroundColorAttributeName: text_color,
            NSFontAttributeName: NSFont.systemFontOfSize_(14.0),
            NSParagraphStyleAttributeName: para,
        }))
    b.setTarget_(target)
    b.setAction_(action)
    if fill is not None:                       # accent: fixed fill, no hover tint
        b.layer().setBackgroundColor_(fill.CGColor())
    else:
        b.refreshFill()                        # subtle: label-tint + hover
    return b


def _badge(klass, x, top_y):
    """Risk badge as a colored rounded box with a vertically-centred label
    (a bare NSTextField top-aligns the glyphs — hence the box+label)."""
    r, g, b = _RISK_COLOR.get(klass, _RISK_COLOR[risk.NEVER_AUTO])
    text = t(_RISK_LABEL_KEY.get(klass, "assistant.risk_never"))
    w, h = 78.0, 22.0
    box = NSBox.alloc().initWithFrame_(NSMakeRect(x, top_y, w, h))
    box.setBoxType_(NSBoxCustom)
    box.setTitlePosition_(0)
    box.setBorderWidth_(0.0)
    box.setCornerRadius_(h / 2.0)
    box.setContentViewMargins_(NSMakeSize(0, 0))
    box.setFillColor_(NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0))
    label = NSTextField.labelWithString_(text)
    label.setFont_(NSFont.boldSystemFontOfSize_(11.0))
    label.setTextColor_(NSColor.whiteColor())
    label.setAlignment_(NSTextAlignmentCenter)
    label.setFrame_(NSMakeRect(0, (h - 15) / 2.0, w, 15))
    box.contentView().addSubview_(label)
    return box


def _body_view(text, x, y, w, height):
    """A read-only, scrollable draft body on a subtle rounded panel so the user
    can actually read what will be sent before confirming. Module-level — an
    NSObject method with this many args trips PyObjC selector arity."""
    box = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, height))
    box.setBoxType_(NSBoxCustom)
    box.setTitlePosition_(0)
    box.setBorderWidth_(0.0)
    box.setCornerRadius_(12.0)
    box.setContentViewMargins_(NSMakeSize(0, 0))
    box.setFillColor_(NSColor.labelColor().colorWithAlphaComponent_(0.05))

    scroll = NSScrollView.alloc().initWithFrame_(
        NSMakeRect(4, 4, w - 8, height - 8))
    scroll.setDrawsBackground_(False)
    scroll.setHasVerticalScroller_(True)
    scroll.setAutohidesScrollers_(True)
    tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, w - 8, height - 8))
    tv.setString_(text)
    tv.setEditable_(False)
    tv.setSelectable_(True)
    tv.setDrawsBackground_(False)
    tv.setFont_(NSFont.systemFontOfSize_(13.5))
    tv.setTextColor_(NSColor.labelColor())
    tv.setTextContainerInset_(NSMakeSize(10, 8))
    scroll.setDocumentView_(tv)
    box.contentView().addSubview_(scroll)
    return box


def _mail_fields(prop):
    """(meta, body) for a mail proposal, else (None, None)."""
    if str(prop.get("kind")) not in _MAIL_KINDS:
        return None, None
    args = (prop.get("payload") or {}).get("args") or {}
    to = str(args.get("to") or "")
    subject = str(args.get("subject") or "")
    body = str(args.get("draft") or "")
    meta = (f"{t('assistant.mail_to')}  {to}      "
            f"{t('assistant.mail_subject')}  {subject}")
    return meta, body


class _NAPanel(NSPanel):
    _allow_key = False  # set True only while a mail card's revise field is live

    def canBecomeKeyWindow(self):
        return bool(self._allow_key)

    def canBecomeMainWindow(self):
        return False

    def performKeyEquivalent_(self, event):
        # while the revise field is focused the panel is key, so ⌘A/C/V/X/Z land
        # here with no Edit menu to dispatch them (ui_kit handles it).
        if handle_edit_key_equivalent(self, event):
            return True
        return objc.super(_NAPanel, self).performKeyEquivalent_(event)


class ProposalPanelController(NSObject):
    def initWithConfig_owner_(self, config, owner):
        self = objc.super(ProposalPanelController, self).init()
        if self is None:
            return None
        self.config = config
        self.owner = owner          # AssistantController
        self.panel = None
        self.host = None
        self.pid = None
        self.revise_field = None
        self.revise_button = None
        return self

    # -- build ---------------------------------------------------------------

    def _ensurePanel(self):
        """Build the single reused panel once. Rebuilding per-present leaked a
        window each time (it stayed on screen) — the panel is reused and only
        resized/repopulated on each present."""
        if self.panel is not None:
            return
        rect = NSMakeRect(0, 0, _W, 240)
        self.panel = _NAPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskNonactivatingPanel | NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered, False,
        )
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(True)
        self.panel.setMovableByWindowBackground_(True)

        radius = float(self.config.get("panel_corner_radius"))
        if _Glass is not None and bool(self.config.get("glass_enabled")):
            glass = _Glass.alloc().initWithFrame_(rect)
            glass.setCornerRadius_(radius)
            glass.setStyle_(
                1 if str(self.config.get("glass_style")) == "clear" else 0)
            host = NSView.alloc().initWithFrame_(rect)
            host.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            glass.setContentView_(host)
            self.panel.setContentView_(glass)
        else:
            backdrop = NSVisualEffectView.alloc().initWithFrame_(rect)
            backdrop.setMaterial_(NSVisualEffectMaterialHUDWindow)
            backdrop.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            backdrop.setState_(NSVisualEffectStateActive)
            backdrop.setWantsLayer_(True)
            backdrop.layer().setCornerRadius_(radius)
            backdrop.layer().setMasksToBounds_(True)
            self.panel.setContentView_(backdrop)
            host = backdrop
        self.host = host

    # -- present -------------------------------------------------------------

    def presentProposal_(self, prop):
        if not prop:
            return
        self.pid = prop.get("id")
        rationale = str(prop.get("rationale") or "").strip()
        meta, body = _mail_fields(prop)
        has_body = bool(body)

        # ---- compute height from the pieces (bottom-left origin) ----
        h = _PAD                               # bottom inset
        h += 36 + 16                           # buttons + gap
        if has_body:
            h += 34 + 14                        # AI-revise input row + gap
            h += _BODY_H + 10                   # scrollable draft body + gap
            h += 18 + 8                         # meta line (to/subject) + gap
        h += (40 if rationale else 0) + (8 if rationale else 0)  # rationale
        h += 48 + 12                           # title + gap
        h += 24 + _PAD                         # header (badge/source) + top inset

        # reuse the single panel; resize it to fit this card's height
        self._ensurePanel()
        self.revise_field = None
        self.revise_button = None
        self._dropKey()                        # clean focus state for this card
        screen = NSScreen.mainScreen()
        if screen is not None:
            vf = screen.visibleFrame()
            x = vf.origin.x + (vf.size.width - _W) / 2.0
            y = vf.origin.y + vf.size.height - h - 60
            self.panel.setFrame_display_(NSMakeRect(x, y, _W, h), True)
        else:
            self.panel.setContentSize_(NSMakeSize(_W, h))

        # clear the previous card's content before drawing this one
        for sub in list(self.host.subviews()):
            sub.removeFromSuperview()
        iw = _W - 2 * _PAD
        klass = str(prop.get("risk") or risk.NEVER_AUTO)

        # cursor walks DOWN from the top (we have absolute height now)
        top = h - _PAD - 24
        self.host.addSubview_(_badge(klass, _PAD, top))
        src = NSTextField.labelWithString_(str(prop.get("source") or ""))
        src.setFont_(NSFont.systemFontOfSize_(11.5))
        src.setTextColor_(NSColor.tertiaryLabelColor())
        src.setFrame_(NSMakeRect(_PAD + 88, top + 3, iw - 88, 16))
        self.host.addSubview_(src)

        title = NSTextField.wrappingLabelWithString_(str(prop.get("title") or ""))
        title.setFont_(NSFont.boldSystemFontOfSize_(17.0))
        title.setTextColor_(NSColor.labelColor())
        title.setFrame_(NSMakeRect(_PAD, top - 12 - 48, iw, 48))
        self.host.addSubview_(title)

        cursor = top - 12 - 48 - 8
        if rationale:
            rat = NSTextField.wrappingLabelWithString_(rationale)
            rat.setFont_(NSFont.systemFontOfSize_(13.0))
            rat.setTextColor_(NSColor.secondaryLabelColor())
            rat.setFrame_(NSMakeRect(_PAD, cursor - 40, iw, 40))
            self.host.addSubview_(rat)
            cursor -= 40 + 8

        if has_body:
            ml = NSTextField.labelWithString_(meta)
            ml.setFont_(NSFont.systemFontOfSize_(12.0))
            ml.setTextColor_(NSColor.tertiaryLabelColor())
            ml.setLineBreakMode_(0)            # clip; subject can be long
            ml.setFrame_(NSMakeRect(_PAD, cursor - 18, iw, 16))
            self.host.addSubview_(ml)
            cursor -= 18 + 8
            self.host.addSubview_(
                _body_view(body, _PAD, cursor - _BODY_H, iw, _BODY_H))
            cursor -= _BODY_H + 14
            # ---- AI revise row: instruction field + "AI 수정" button ----
            ry = cursor - 34
            fbox, field = make_round_field(
                NSMakeRect(_PAD, ry, iw - 112, 34), 13.0)
            field.setTarget_(self)
            field.setAction_("reviseSubmit:")
            field.setPlaceholderString_(t("assistant.revise_placeholder"))
            self.host.addSubview_(fbox)
            self.revise_field = field
            rbtn = _pill(self, t("assistant.revise_button"), "reviseSubmit:",
                        _PAD + iw - 104, ry, 104, 34, None, NSColor.labelColor())
            self.host.addSubview_(rbtn)
            self.revise_button = rbtn

        # ---- buttons ----
        bw = (iw - 16) / 3.0
        accent = NSColor.controlAccentColor()
        kind = str(prop.get("kind"))
        if kind == "send_reply":
            approve_label = t("assistant.send_now")       # the 2nd-gesture send
        elif kind == "calendar_alert":
            approve_label = t("assistant.acknowledge")    # informational: dismiss
        else:
            approve_label = t("assistant.approve")
        self.host.addSubview_(_pill(
            self, approve_label, "approveClicked:",
            _PAD, _PAD, bw, 36, accent, NSColor.whiteColor()))
        self.host.addSubview_(_pill(
            self, t("assistant.skip"), "skipClicked:",
            _PAD + bw + 8, _PAD, bw, 36, None, NSColor.labelColor()))
        self.host.addSubview_(_pill(
            self, t("assistant.snooze"), "snoozeClicked:",
            _PAD + 2 * (bw + 8), _PAD, bw, 36, None, NSColor.labelColor()))

        # mail cards may become key (only) when the user clicks the revise field
        self.panel._allow_key = has_body
        self.panel.orderFrontRegardless()  # never makeKeyAndOrderFront

    def presentRevised_(self, prop):
        """Re-show a card after an AI revision (controller calls this)."""
        self.presentProposal_(prop)

    # -- focus gate (M6: key only while the revise field is live) -------------

    def _dropKey(self):
        if self.panel is None:
            return
        self.panel.makeFirstResponder_(None)
        if self.panel.isKeyWindow():
            # leave the screen list so the window server re-keys the source app
            self.panel.orderOut_(None)
            self.panel.orderFrontRegardless()
        self.panel._allow_key = False

    # -- actions -------------------------------------------------------------

    def reviseSubmit_(self, sender):
        """Send the typed instruction to the AI to rewrite the draft, then the
        controller re-presents the card (presentRevised_)."""
        field = getattr(self, "revise_field", None)
        if field is None or not self.pid:
            return
        text = str(field.stringValue()).strip()
        if not text:
            return
        self._dropKey()                        # hand the keyboard back
        button = getattr(self, "revise_button", None)
        if button is not None:
            button.setEnabled_(False)
        field.setEnabled_(False)
        self.owner.reviseDraft(self.pid, text)

    def approveClicked_(self, sender):
        self._dropKey()
        if self.pid:
            self.owner.approve(self.pid)
        self._advance()

    def skipClicked_(self, sender):
        self._dropKey()
        if self.pid:
            self.owner.skip(self.pid)
        self._advance()

    def snoozeClicked_(self, sender):
        self._dropKey()
        if self.pid:
            self.owner.snooze(self.pid)
        self._advance()

    def _advance(self):
        """Show the next pending proposal, or hide the panel."""
        pending = [p for p in self.owner.proposals.pending()
                   if p.get("id") != self.pid]
        if pending:
            self.presentProposal_(pending[0])
        elif self.panel is not None:
            self.pid = None
            self.panel._allow_key = False
            self.panel.orderOut_(None)

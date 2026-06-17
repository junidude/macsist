"""ProposalPanelController — the confirm surface for proposals (M14).

A non-activating floating glass card (result_panel rules: canBecomeKeyWindow
False, setHidesOnDeactivate_(False), orderFrontRegardless — NEVER steals focus,
the app never activates). Frosted glass with a tint so it reads as a solid card
(not a stark white box), a risk-colored badge, the rationale, and pill buttons
(승인 = accent, 건너뛰기 / 나중에 = subtle). Sizes to its content; advances to
the next pending proposal after an action, or hides.
"""

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSLineBreakByTruncatingTail,
    NSMutableParagraphStyle,
    NSPanel,
    NSParagraphStyleAttributeName,
    NSScreen,
    NSTextAlignmentCenter,
    NSTextField,
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
from Foundation import NSAttributedString, NSMakeRect, NSMakeSize, NSObject

from assistant import risk
from i18n import t

try:
    _Glass = objc.lookUpClass("NSGlassEffectView")
except objc.error:
    _Glass = None

_W = 420.0
_PAD = 20.0
_RISK_COLOR = {
    risk.AUTO: (0.20, 0.65, 0.30),
    risk.CONFIRM: (0.90, 0.58, 0.10),
    risk.NEVER_AUTO: (0.85, 0.25, 0.25),
}


def _pill(target, title, action, x, y, w, h, fill, text_color):
    """A layer-backed rounded pill button (matches the app's pill style).
    Module-level — NSObject methods need selector arity (project memory)."""
    b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    b.setBordered_(False)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(h / 2.0)
    b.layer().setBackgroundColor_(fill.CGColor())
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSTextAlignmentCenter)
    attrs = {
        NSForegroundColorAttributeName: text_color,
        NSFontAttributeName: NSFont.systemFontOfSize_(14.0),
        NSParagraphStyleAttributeName: para,
    }
    b.setAttributedTitle_(
        NSAttributedString.alloc().initWithString_attributes_(title, attrs))
    b.setTarget_(target)
    b.setAction_(action)
    return b


class _NAPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return False

    def canBecomeMainWindow(self):
        return False


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
        return self

    # -- build ---------------------------------------------------------------

    def _build(self):
        rect = NSMakeRect(0, 0, _W, 200)
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
            backdrop = _Glass.alloc().initWithFrame_(rect)
            backdrop.setCornerRadius_(radius)
            # a tint so the card reads as solid frosted glass, not stark white
            backdrop.setTintColor_(
                NSColor.windowBackgroundColor().colorWithAlphaComponent_(0.55))
            host = NSView.alloc().initWithFrame_(rect)
            host.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            backdrop.setContentView_(host)
            self.panel.setContentView_(backdrop)
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
        if self.panel is None:
            self._build()
        self.pid = prop.get("id")

        rationale = str(prop.get("rationale") or "").strip()
        h = 206.0 if rationale else 158.0
        screen = NSScreen.mainScreen()
        if screen is not None:
            vf = screen.visibleFrame()
            x = vf.origin.x + (vf.size.width - _W) / 2.0
            y = vf.origin.y + vf.size.height - h - 60
            self.panel.setFrame_display_(NSMakeRect(x, y, _W, h), True)

        for sub in list(self.host.subviews()):
            sub.removeFromSuperview()
        iw = _W - 2 * _PAD

        klass = str(prop.get("risk") or risk.NEVER_AUTO)
        r, g, b = _RISK_COLOR.get(klass, _RISK_COLOR[risk.NEVER_AUTO])
        badge = NSTextField.labelWithString_(f"  {klass.upper()}  ")
        badge.setFont_(NSFont.boldSystemFontOfSize_(10.0))
        badge.setTextColor_(NSColor.whiteColor())
        badge.setBackgroundColor_(
            NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0))
        badge.setDrawsBackground_(True)
        badge.setBezeled_(False)
        badge.setAlignment_(NSTextAlignmentCenter)
        badge.setWantsLayer_(True)
        badge.layer().setCornerRadius_(9.0)
        badge.layer().setMasksToBounds_(True)
        badge.setFrame_(NSMakeRect(_PAD, h - _PAD - 18, 96, 18))
        self.host.addSubview_(badge)

        src = NSTextField.labelWithString_(str(prop.get("source") or ""))
        src.setFont_(NSFont.systemFontOfSize_(11.0))
        src.setTextColor_(NSColor.tertiaryLabelColor())
        src.setFrame_(NSMakeRect(_PAD + 104, h - _PAD - 17, iw - 104, 16))
        self.host.addSubview_(src)

        title = NSTextField.wrappingLabelWithString_(str(prop.get("title") or ""))
        title.setFont_(NSFont.boldSystemFontOfSize_(16.0))
        title.setFrame_(NSMakeRect(_PAD, h - _PAD - 18 - 8 - 46, iw, 46))
        self.host.addSubview_(title)

        if rationale:
            rat = NSTextField.wrappingLabelWithString_(rationale)
            rat.setFont_(NSFont.systemFontOfSize_(12.5))
            rat.setTextColor_(NSColor.secondaryLabelColor())
            rat.setFrame_(NSMakeRect(_PAD, 66, iw, 40))
            self.host.addSubview_(rat)

        bw = (iw - 16) / 3.0
        accent = NSColor.controlAccentColor()
        subtle = NSColor.labelColor().colorWithAlphaComponent_(0.10)
        # M17: the 2nd-gesture send card relabels 승인 → 지금 보내기 (the explicit
        # send), while the badge stays NEVER_AUTO red (set above from prop.risk).
        approve_label = (t("assistant.send_now")
                         if str(prop.get("kind")) == "send_reply"
                         else t("assistant.approve"))
        self.host.addSubview_(_pill(
            self, approve_label, "approveClicked:",
            _PAD, 18, bw, 34, accent, NSColor.whiteColor()))
        self.host.addSubview_(_pill(
            self, t("assistant.skip"), "skipClicked:",
            _PAD + bw + 8, 18, bw, 34, subtle, NSColor.labelColor()))
        self.host.addSubview_(_pill(
            self, t("assistant.snooze"), "snoozeClicked:",
            _PAD + 2 * (bw + 8), 18, bw, 34, subtle, NSColor.labelColor()))

        self.panel.orderFrontRegardless()  # never makeKeyAndOrderFront

    # -- actions -------------------------------------------------------------

    def approveClicked_(self, sender):
        if self.pid:
            self.owner.approve(self.pid)
        self._advance()

    def skipClicked_(self, sender):
        if self.pid:
            self.owner.skip(self.pid)
        self._advance()

    def snoozeClicked_(self, sender):
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
            self.panel.orderOut_(None)

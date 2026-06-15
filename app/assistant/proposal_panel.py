"""ProposalPanelController — the confirm surface for proposals (M14).

A non-activating floating glass panel (result_panel rules: canBecomeKeyWindow
False, setHidesOnDeactivate_(False), orderFrontRegardless — NEVER steals focus,
the app never activates). Shows one proposal with a risk-colored badge,
rationale, and Approve / Skip / Snooze buttons that route to the controller
(which records the audit approval and runs the executor past assert_approved).
After an action it advances to the next pending proposal or hides.
"""

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSButton,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSPanel,
    NSScreen,
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
from Foundation import NSMakeRect, NSMakeSize, NSObject

from assistant import risk
from i18n import t

try:
    _Glass = objc.lookUpClass("NSGlassEffectView")
except objc.error:
    _Glass = None

_W, _H = 440.0, 232.0
_RISK_COLOR = {
    risk.AUTO: (0.20, 0.65, 0.30),
    risk.CONFIRM: (0.90, 0.60, 0.10),
    risk.NEVER_AUTO: (0.85, 0.25, 0.25),
}


def _action_button(target, title, action, x, w, default=False):
    """Module-level (NOT a method): NSObject-subclass methods need selector
    arity, plain helpers live here (project memory pyobjc-selector-arg-naming)."""
    b = NSButton.alloc().initWithFrame_(NSMakeRect(x, 16, w, 32))
    b.setTitle_(title)
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTarget_(target)
    b.setAction_(action)
    if default:
        b.setKeyEquivalent_("\r")
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
        rect = NSMakeRect(0, 0, _W, _H)
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
        for sub in list(self.host.subviews()):
            sub.removeFromSuperview()
        pad = 20.0
        inner_w = _W - 2 * pad

        klass = str(prop.get("risk") or risk.NEVER_AUTO)
        r, g, b = _RISK_COLOR.get(klass, _RISK_COLOR[risk.NEVER_AUTO])
        badge = NSTextField.labelWithString_(f"  {klass.upper()}  ")
        badge.setFont_(NSFont.boldSystemFontOfSize_(10.0))
        badge.setTextColor_(NSColor.whiteColor())
        badge.setBackgroundColor_(NSColor.colorWithRed_green_blue_alpha_(
            r, g, b, 1.0))
        badge.setDrawsBackground_(True)
        badge.setBezeled_(False)
        badge.setFrame_(NSMakeRect(pad, _H - 40, 110, 18))
        self.host.addSubview_(badge)

        src = NSTextField.labelWithString_(str(prop.get("source") or ""))
        src.setFont_(NSFont.systemFontOfSize_(11.0))
        src.setTextColor_(NSColor.secondaryLabelColor())
        src.setFrame_(NSMakeRect(pad + 118, _H - 39, inner_w - 118, 16))
        self.host.addSubview_(src)

        title = NSTextField.wrappingLabelWithString_(str(prop.get("title") or ""))
        title.setFont_(NSFont.boldSystemFontOfSize_(15.0))
        title.setFrame_(NSMakeRect(pad, _H - 92, inner_w, 44))
        self.host.addSubview_(title)

        rationale = NSTextField.wrappingLabelWithString_(
            str(prop.get("rationale") or ""))
        rationale.setFont_(NSFont.systemFontOfSize_(12.0))
        rationale.setTextColor_(NSColor.secondaryLabelColor())
        rationale.setFrame_(NSMakeRect(pad, 58, inner_w, 70))
        self.host.addSubview_(rationale)

        bw = (inner_w - 16) / 3.0
        self.host.addSubview_(_action_button(
            self, t("assistant.approve"), "approveClicked:", pad, bw,
            default=True))
        self.host.addSubview_(_action_button(
            self, t("assistant.skip"), "skipClicked:", pad + bw + 8, bw))
        self.host.addSubview_(_action_button(
            self, t("assistant.snooze"), "snoozeClicked:", pad + 2 * (bw + 8),
            bw))

        self._position()
        self.panel.orderFrontRegardless()  # never makeKeyAndOrderFront

    def _position(self):
        screen = NSScreen.mainScreen()
        if screen is None:
            return
        vf = screen.visibleFrame()
        x = vf.origin.x + (vf.size.width - _W) / 2.0
        y = vf.origin.y + vf.size.height - _H - 60
        self.panel.setFrame_display_(NSMakeRect(x, y, _W, _H), True)

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
        else:
            self.pid = None
            if self.panel is not None:
                self.panel.orderOut_(None)

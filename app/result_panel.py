"""ResultPanel — non-activating floating panel that streams the explanation.

Hard rule: must never steal focus from the source app. The NonactivatingPanel
mask alone is not enough — such a panel can still become key when clicked — so
the subclass refuses key/main by default and the panel is only ever shown with
orderFrontRegardless().

M6 (follow-up questions) carves out the one Spotlight-style exception: while
the user has clicked into the follow-up input, `canBecomeKeyWindow` returns
True so keystrokes route to the field WITHOUT activating the app — the source
app keeps visual focus the whole time. `_allow_key` is the gate; it is set in
exactly one place (focusInput, on a click in the visible input) and cleared on
unfocus/reset/dismiss.

All methods are main-thread only (callers marshal via AppHelper.callAfter).
"""

import objc
from AppKit import (
    NSApp,
    NSAnimationContext,
    NSBackingStoreBuffered,
    NSBox,
    NSBoxCustom,
    NSColor,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSEventModifierFlagShift,
    NSEventTypeKeyDown,
    NSFloatingWindowLevel,
    NSFocusRingTypeNone,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSObject,
    NSPanel,
    NSScreen,
    NSScrollView,
    NSTextView,
    NSView,
    NSViewHeightSizable,
    NSViewMaxYMargin,
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
from PyObjCTools import AppHelper

# macOS 26 Liquid Glass (M8). lookUpClass only works after AppKit is loaded,
# which the imports above guarantee; older systems fall back to the
# NSVisualEffectView path below.
try:
    _GlassEffectView = objc.lookUpClass("NSGlassEffectView")
except objc.error:
    _GlassEffectView = None

try:
    from Quartz import kCACornerCurveContinuous as _CORNER_CONTINUOUS
except ImportError:
    _CORNER_CONTINUOUS = "continuous"

from i18n import t
from ui_kit import handle_edit_key_equivalent

_ESC_KEYCODE = 53
_PADDING = 14.0  # Spotlight-like airy inset (M8 polish)
_INPUT_HEIGHT = 30.0  # one-line input row
_INPUT_MAX_HEIGHT = 108.0  # ~5 lines; Shift+Enter grows the field up to this
_INPUT_GAP = 6.0


class _NonActivatingPanel(NSPanel):
    _allow_key = False  # instance attr set by the controller (focus gate)

    def canBecomeKeyWindow(self):
        return bool(self._allow_key)

    def canBecomeMainWindow(self):
        return False

    def performKeyEquivalent_(self, event):
        # While the follow-up input is focused the panel is key, so ⌘A/C/V/X/Z
        # land here — no Edit menu exists to dispatch them (ui_kit explains).
        if handle_edit_key_equivalent(self, event):
            return True
        return objc.super(_NonActivatingPanel, self).performKeyEquivalent_(event)


class _HairlineEffectView(NSVisualEffectView):
    """Fallback backdrop: hudWindow material with a 1px separatorColor border.
    Semantic colors resolve to a concrete CGColor at assignment time, so the
    border must be re-resolved whenever the effective appearance flips."""

    def viewDidChangeEffectiveAppearance(self):
        objc.super(_HairlineEffectView, self).viewDidChangeEffectiveAppearance()
        self.refreshBorderColor()

    def refreshBorderColor(self):
        def _apply():
            self.layer().setBorderColor_(NSColor.separatorColor().CGColor())
        self.effectiveAppearance().performAsCurrentDrawingAppearance_(_apply)


class _FollowUpTextView(NSTextView):
    """Chat-style composer. An NSTextView (not NSTextField) so multi-line text
    is TOP-aligned and grows cleanly — a rounded-bezel NSTextField centers its
    text vertically and its field editor scrolls independently, which is what
    made earlier lines drift to the middle / scroll out of view. Draws its own
    placeholder since NSTextView has none."""

    _placeholder = ""

    def acceptsFirstMouse_(self, event):
        # the focusing click also places the caret in one click
        return True

    def drawRect_(self, rect):
        objc.super(_FollowUpTextView, self).drawRect_(rect)
        if self.string() and len(self.string()) > 0:
            return
        if not self._placeholder:
            return
        inset = self.textContainerInset()
        pad = self.textContainer().lineFragmentPadding()
        attrs = {
            NSFontAttributeName: self.font()
            or NSFont.systemFontOfSize_(13.0),
            NSForegroundColorAttributeName: NSColor.placeholderTextColor(),
        }
        NSAttributedString.alloc().initWithString_attributes_(
            self._placeholder, attrs
        ).drawAtPoint_(NSMakePoint(inset.width + pad, inset.height))


class ResultPanelController(NSObject):
    def initWithConfig_(self, config):
        self = objc.super(ResultPanelController, self).init()
        if self is None:
            return None
        self.config = config
        self.panel = None
        self.text_view = None
        self.input_field = None  # the NSTextView (focus + text)
        self.input_box = None  # rounded container (show/hide/geometry/hit-test)
        self.input_scroll = None  # scroll view between the box and the textview
        self.on_dismiss = None  # set by ExplainController: cancels the stream
        self.on_followup = None  # set by ExplainController: submits a follow-up
        self._placeholder = False
        self._ph_start = 0  # placeholder is always the TAIL of the storage
        self._followup_mode = False
        self._expanded = False
        self._input_height = _INPUT_HEIGHT  # grows with Shift+Enter newlines
        self._scroll = None
        self._backdrop = None
        self._fade_gen = 0  # cancels a pending fade-out orderOut on re-show
        self._height_capped = False  # auto-height hit the cap (short-circuit)
        self._needs_rebuild = False  # settings saved → rebuild on next show
        self._global_monitor = None
        self._local_monitor = None
        self._text_attrs = None
        self._message_attrs = None
        self._question_attrs = None
        return self

    # -- public API (main thread) ------------------------------------------

    def beginSessionAt_(self, cursor_tl):
        """Clear, reposition near the cursor, show a streaming placeholder."""
        self.beginSessionAt_centered_(cursor_tl, False)

    def beginSessionAt_centered_(self, anchor_tl, centered):
        """centered=True: the panel's CENTER lands on anchor_tl (region mode —
        the anchor is the captured selection's midpoint, M8 polish)."""
        self._presentAt_centered_(anchor_tl, centered)
        self._setText_attrs_("…", self._message_attrs)
        self._ph_start = 0
        self._placeholder = True

    def appendChunk_(self, chunk):
        if self._placeholder:
            self._replaceTail_attrs_("", self._text_attrs)
            self._placeholder = False
        storage = self.text_view.textStorage()
        storage.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                chunk, self._text_attrs
            )
        )
        self._recomputeHeight()
        self.text_view.scrollRangeToVisible_(NSMakeRange(storage.length(), 0))

    def showThinking_(self, char_count):
        """Quiet placeholder update while a thinking model reasons (no log
        spam — this fires per reasoning token). First content chunk replaces it."""
        if self._placeholder:
            self._replaceTail_attrs_(
                t("panel.thinking").format(n=char_count),
                self._message_attrs
            )

    def showMessageAt_text_(self, cursor_tl, message):
        """One-line status (empty selection, missing permission, LLM error)."""
        self._presentAt_(cursor_tl)
        self.showErrorText_(message)

    def showErrorText_(self, message):
        if self._placeholder:
            # mid-transcript placeholder ("…" / 생각 중) → replace just the tail
            self._replaceTail_attrs_(message, self._message_attrs)
            self._placeholder = False
        elif self._followup_mode:
            # never wipe an accumulated follow-up transcript
            storage = self.text_view.textStorage()
            storage.appendAttributedString_(
                NSAttributedString.alloc().initWithString_attributes_(
                    "\n\n" + message, self._message_attrs
                )
            )
            self.text_view.scrollRangeToVisible_(
                NSMakeRange(storage.length(), 0)
            )
        else:
            self._setText_attrs_(message, self._message_attrs)
        self._recomputeHeight()
        print("panel message:", message, flush=True)

    def finishStream(self):
        print(
            "stream finished, panel text:",
            repr(str(self.text_view.string())[:120]),
            flush=True,
        )

    def showFollowUpInput(self):
        """Reveal the bottom input row (after a finished/errored explain).
        Idempotent — also called after every follow-up answer."""
        if self.input_box is None or not self.input_box.isHidden():
            return
        self._input_height = _INPUT_HEIGHT  # always reappears as one line
        frame = self._scroll.frame()
        bottom = _PADDING + self._input_height + _INPUT_GAP
        top = frame.origin.y + frame.size.height
        self._scroll.setFrame_(
            NSMakeRect(frame.origin.x, bottom, frame.size.width, top - bottom)
        )
        self.input_box.setFrame_(
            NSMakeRect(_PADDING, _PADDING, frame.size.width, _INPUT_HEIGHT)
        )
        self.input_box.setHidden_(False)
        self._recomputeHeight()  # input row adds to the needed height
        print("follow-up input shown", flush=True)

    def beginFollowUp_(self, question):
        """Append the question to the transcript and a tail placeholder for
        the streamed answer; grow the panel on the first follow-up (§5.1)."""
        self._followup_mode = True
        if not self._expanded:
            self._growToExpanded()
        storage = self.text_view.textStorage()
        storage.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                "\n\n❯ " + question + "\n", self._question_attrs
            )
        )
        self._ph_start = storage.length()
        storage.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(
                "…", self._message_attrs
            )
        )
        self._placeholder = True
        self._recomputeHeight()
        self.text_view.scrollRangeToVisible_(NSMakeRange(storage.length(), 0))

    def _submitFollowUp(self):
        # Return (no Shift) in the input field — submit the typed question.
        text = str(self.input_field.string()).strip()
        if not text:
            return
        self.input_field.setString_("")  # keep focus: consecutive questions
        self._setInputHeight_(_INPUT_HEIGHT)  # collapse back to one line
        self.input_field.setNeedsDisplay_(True)  # repaint the placeholder
        if self.on_followup is not None:
            self.on_followup(text)

    # -- follow-up input: Return submits, Shift+Return = newline ---------------

    def textView_doCommandBySelector_(self, textView, selector):
        """NSTextView command hook (delegate). Take over Return: a bare Return
        submits; Shift+Return falls through so the text view inserts a real
        newline. Everything else (arrows, ⌥/⌘ navigation, deletes) is the text
        view's default handling."""
        if selector == "insertNewline:":
            event = NSApp.currentEvent()
            if event is not None and (
                event.modifierFlags() & NSEventModifierFlagShift
            ):
                return False  # let the text view insert the newline itself
            self._submitFollowUp()
            return True
        return False

    def textDidChange_(self, note):
        # typing/pasting/deleting/newlines may change the line count — refit
        self._adjustInputHeight()

    def _adjustInputHeight(self):
        """Size the input row to the text view's content, clamped to
        [_INPUT_HEIGHT, _INPUT_MAX_HEIGHT]; past the cap the text view scrolls
        inside the box."""
        field = self.input_field
        if field is None or self.input_box is None or self.input_box.isHidden():
            return
        lm = field.layoutManager()
        tc = field.textContainer()
        lm.ensureLayoutForTextContainer_(tc)
        used = lm.usedRectForTextContainer_(tc).size.height
        # The line the caret lands on right after Shift+Enter is a *trailing
        # newline* — it lives in the layout manager's extra line fragment,
        # which usedRect does NOT include. Count it so the box grows a full
        # line immediately (otherwise it lags one line behind the content).
        elf = lm.extraLineFragmentRect()
        if elf.size.height > 0:
            used = max(used, elf.origin.y + elf.size.height)
        inset = field.textContainerInset().height
        desired = max(_INPUT_HEIGHT, min(used + 2 * inset, _INPUT_MAX_HEIGHT))
        self._setInputHeight_(desired)

    def _setInputHeight_(self, height):
        """Apply a new input-row height. The panel grows DOWNWARD by the delta
        (top edge fixed, the way it hangs below the cursor) so the input box
        lengthens and the whole popup follows — like a chat composer — while
        the transcript above keeps its height. Only if the panel would run past
        the screen bottom does the transcript give up the remainder."""
        if self.input_box is None or self.input_box.isHidden():
            self._input_height = _INPUT_HEIGHT
            return
        if abs(height - self._input_height) < 0.5:
            return
        panel = self.panel
        frame = panel.frame()
        top = frame.origin.y + frame.size.height  # fixed top edge
        screen = panel.screen() or NSScreen.mainScreen()
        vf = screen.visibleFrame()
        new_h = frame.size.height + (height - self._input_height)
        new_oy = top - new_h
        if new_oy < vf.origin.y:  # clamp at the screen bottom
            new_oy = vf.origin.y
            new_h = top - new_oy
        panel.setFrame_display_(
            NSMakeRect(frame.origin.x, new_oy, frame.size.width, new_h), True
        )
        inner_w = frame.size.width - 2 * _PADDING
        # box bottom-pinned; its scroll/text view autoresize within it
        self.input_box.setFrame_(NSMakeRect(_PADDING, _PADDING, inner_w, height))
        scroll_bottom = _PADDING + height + _INPUT_GAP
        self._scroll.setFrame_(
            NSMakeRect(_PADDING, scroll_bottom, inner_w,
                       max(40.0, new_h - scroll_bottom - _PADDING))
        )
        self._input_height = height
        print(f"input height -> {height:.0f}, panel -> {new_h:.0f}", flush=True)

    def markDirty(self):
        """Settings saved (panel size/font/glass changed): tear the panel
        down at the START of the next session — never mid-stream, the live
        text view may still be receiving chunks."""
        self._needs_rebuild = True
        print("panel marked for rebuild (settings saved)", flush=True)

    def dismiss(self):
        """User-initiated dismiss (Esc / click-away) — also stops the stream.
        M8: fades out over panel_fade_duration, EXCEPT while the panel is key —
        orderOut_ is what hands the keyboard back to the source app, so a
        key-window dismiss must stay instant (never-steal-focus invariant)."""
        self._remove_monitors()
        if self.panel is not None and self.panel.isVisible():
            if self.panel.isKeyWindow():
                self.panel.makeFirstResponder_(None)
                self.panel._allow_key = False
                self.panel.orderOut_(None)  # hands key back to the source app
            else:
                self.panel._allow_key = False
                self._fadeOut()
            print("panel dismissed", flush=True)
        elif self.panel is not None:
            self.panel._allow_key = False
        if self.on_dismiss is not None:
            self.on_dismiss()

    def _fadeOut(self):
        self._fade_gen += 1
        token = self._fade_gen

        def _animate(context):
            context.setDuration_(float(self.config.get("panel_fade_duration")))
            self.panel.animator().setAlphaValue_(0.0)

        def _done():
            if token != self._fade_gen:
                return  # re-shown mid-fade: _presentAt_ already restored alpha
            self.panel.orderOut_(None)
            self.panel.setAlphaValue_(1.0)  # orderOut/orderFront flips elsewhere
            print("panel fade-out done -> orderOut", flush=True)

        NSAnimationContext.runAnimationGroup_completionHandler_(_animate, _done)

    # -- panel construction --------------------------------------------------

    def _buildPanel(self):
        width = float(self.config.get("panel_width"))
        # M8 auto-height: start minimal, grow to fit up to panel_height
        height = float(self.config.get("panel_min_height"))
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
        # defense-in-depth only — the local monitor drives focus explicitly
        panel.setBecomesKeyOnlyIfNeeded_(True)
        # Drag-to-move: grab the panel's background/margins (anywhere that
        # isn't the transcript text or the input field) and reposition it —
        # for when it covers something or sits too low. Works without keying
        # the panel, so the never-steal-focus invariant is untouched.
        panel.setMovableByWindowBackground_(True)

        content_host = self._buildBackdropForPanel_width_height_(
            panel, width, height
        )

        scroll = NSTextView.scrollableTextView()
        scroll.setFrame_(
            NSMakeRect(
                _PADDING, _PADDING, width - 2 * _PADDING, height - 2 * _PADDING
            )
        )
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        scroll.setDrawsBackground_(False)
        content_host.addSubview_(scroll)

        text_view = scroll.documentView()
        text_view.setEditable_(False)
        text_view.setSelectable_(True)
        text_view.setDrawsBackground_(False)
        text_view.setTextContainerInset_(NSMakeSize(4, 4))

        # follow-up input, bottom-pinned, hidden until a session can continue.
        # Rounded box (background, hit-target) → scroll view → NSTextView.
        font_size = float(self.config.get("panel_font_size"))
        box = NSBox.alloc().initWithFrame_(
            NSMakeRect(_PADDING, _PADDING, width - 2 * _PADDING, _INPUT_HEIGHT)
        )
        box.setBoxType_(NSBoxCustom)
        box.setTitlePosition_(0)
        box.setBorderWidth_(1.0)
        box.setCornerRadius_(9.0)
        box.setBorderColor_(NSColor.separatorColor())
        box.setFillColor_(NSColor.labelColor().colorWithAlphaComponent_(0.06))
        box.setContentViewMargins_(NSMakeSize(0, 0))
        box.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        box.setHidden_(True)

        inner = box.contentView().bounds()
        iscroll = NSScrollView.alloc().initWithFrame_(inner)
        iscroll.setDrawsBackground_(False)
        iscroll.setBorderType_(0)  # NSNoBorder
        iscroll.setHasVerticalScroller_(True)
        iscroll.setAutohidesScrollers_(True)
        iscroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        field = _FollowUpTextView.alloc().initWithFrame_(inner)
        field._placeholder = t("panel.followup_placeholder")
        field.setFont_(NSFont.systemFontOfSize_(font_size))
        field.setTextColor_(NSColor.labelColor())
        field.setDrawsBackground_(False)
        field.setRichText_(False)
        field.setFocusRingType_(NSFocusRingTypeNone)
        field.setTextContainerInset_(NSMakeSize(6, 6))
        field.setMinSize_(NSMakeSize(0, 0))
        field.setMaxSize_(NSMakeSize(1.0e7, 1.0e7))
        field.setVerticallyResizable_(True)
        field.setHorizontallyResizable_(False)
        field.textContainer().setWidthTracksTextView_(True)
        field.setAutoresizingMask_(NSViewWidthSizable)
        field.setDelegate_(self)
        iscroll.setDocumentView_(field)
        box.contentView().addSubview_(iscroll)
        content_host.addSubview_(box)

        font_size = float(self.config.get("panel_font_size"))
        self._text_attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(font_size),
            NSForegroundColorAttributeName: NSColor.labelColor(),
        }
        self._message_attrs = {
            NSFontAttributeName: NSFont.systemFontOfSize_(font_size),
            NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
        }
        self._question_attrs = {
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(font_size),
            NSForegroundColorAttributeName: NSColor.labelColor(),
        }
        self.panel = panel
        self.text_view = text_view
        self.input_field = field
        self.input_box = box
        self.input_scroll = iscroll
        self._scroll = scroll

    def _buildBackdropForPanel_width_height_(self, panel, width, height):
        """Liquid Glass backdrop when available (M8), NSVisualEffectView
        otherwise. Returns the view that hosts the panel's content — for the
        glass path that is a plain wrapper handed to setContentView_ (glass
        manages its content view; subviews must not go on the glass directly).
        The 1px hairline is fallback-only: glass draws its own rim highlight."""
        radius = float(self.config.get("panel_corner_radius"))
        use_glass = bool(self.config.get("glass_enabled")) and (
            _GlassEffectView is not None
        )
        frame = NSMakeRect(0, 0, width, height)
        if use_glass:
            glass = _GlassEffectView.alloc().initWithFrame_(frame)
            glass.setCornerRadius_(radius)
            # 1 == NSGlassEffectViewStyleClear (high transparency, user
            # feedback); anything else falls back to 0 (regular/frosted)
            glass.setStyle_(
                1 if str(self.config.get("glass_style")) == "clear" else 0
            )
            wrapper = NSView.alloc().initWithFrame_(frame)
            wrapper.setAutoresizingMask_(
                NSViewWidthSizable | NSViewHeightSizable
            )
            glass.setContentView_(wrapper)
            panel.setContentView_(glass)
            backdrop, content_host = glass, wrapper
        else:
            effect = _HairlineEffectView.alloc().initWithFrame_(frame)
            effect.setMaterial_(NSVisualEffectMaterialHUDWindow)
            effect.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            effect.setState_(NSVisualEffectStateActive)
            effect.setWantsLayer_(True)
            effect.layer().setCornerRadius_(radius)
            effect.layer().setCornerCurve_(_CORNER_CONTINUOUS)
            effect.layer().setMasksToBounds_(True)
            effect.layer().setBorderWidth_(1.0)
            effect.refreshBorderColor()
            panel.setContentView_(effect)
            backdrop, content_host = effect, effect
        self._backdrop = backdrop
        print(
            f"panel backdrop={type(backdrop).__name__} "
            f"radius={radius:g} glass={use_glass}",
            flush=True,
        )
        return content_host

    # -- presentation ---------------------------------------------------------

    def _presentAt_(self, cursor_tl):
        self._presentAt_centered_(cursor_tl, False)

    def _presentAt_centered_(self, cursor_tl, centered):
        """cursor_tl: (x, y) in CG top-left-origin global coords (from the
        pynput thread via CGEventGetLocation). centered=False: panel hangs
        below-right of the point (text cursor); True: panel center lands on
        it (region capture midpoint). Reuses the single panel instance
        — a new panel per request would leak monitors and risk PyObjC lifetime
        bugs. Deliberately does NOT route through dismiss(): dismiss() cancels
        the in-flight stream, which would kill the request being presented."""
        if self.panel is not None and self._needs_rebuild:
            # settings changed: rebuild with the new size/font/backdrop
            self._remove_monitors()
            if self.panel.isVisible():
                self.panel.orderOut_(None)
            self.panel = None
            self.text_view = None
            self.input_field = None
            self.input_box = None
            self.input_scroll = None
            self._scroll = None
            self._backdrop = None
        self._needs_rebuild = False
        if self.panel is None:
            self._buildPanel()
        # visibility check MUST precede _resetSessionUI (it orderOuts when key)
        was_visible = bool(self.panel.isVisible())
        self._fade_gen += 1  # cancel any pending fade-out orderOut
        self.panel.setAlphaValue_(1.0)
        self._resetSessionUI()  # new session: input/key/size back to defaults
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
        if centered:
            ox = x - size.width / 2.0
            oy = y - size.height / 2.0  # panel center on the region center
        else:
            ox = x + offset
            oy = y - offset - size.height  # panel top sits just below the cursor
        ox = max(vf.origin.x, min(ox, vf.origin.x + vf.size.width - size.width))
        oy = max(vf.origin.y, min(oy, vf.origin.y + vf.size.height - size.height))
        self.panel.setFrameOrigin_(NSMakePoint(ox, oy))
        if was_visible:
            self.panel.orderFrontRegardless()  # never makeKeyAndOrderFront
        else:
            self._fadeIn()
        self._install_monitors()
        print(
            f"panel shown at ({ox:.0f},{oy:.0f}) "
            f"size=({size.width:.0f}x{size.height:.0f})",
            flush=True,
        )

    def _fadeIn(self):
        """First presentation: 0 → 1 alpha over panel_fade_duration (M8).
        Only the show path animates — the orderOut/orderFront key-handback
        flips in _unfocusInput/_resetSessionUI must stay instant."""
        self._fade_gen += 1
        token = self._fade_gen
        self.panel.setAlphaValue_(0.0)
        self.panel.orderFrontRegardless()  # never makeKeyAndOrderFront

        def _animate(context):
            context.setDuration_(float(self.config.get("panel_fade_duration")))
            self.panel.animator().setAlphaValue_(1.0)

        def _done():
            if token == self._fade_gen:
                self.panel.setAlphaValue_(1.0)
                print("panel fade-in done", flush=True)

        NSAnimationContext.runAnimationGroup_completionHandler_(_animate, _done)

    def _screenForPoint_(self, point):
        for screen in NSScreen.screens():
            if NSPointInRect(point, screen.frame()):
                return screen
        return NSScreen.mainScreen()

    def _setText_attrs_(self, text, attrs):
        self.text_view.textStorage().setAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        )

    def _replaceTail_attrs_(self, text, attrs):
        """Replace the placeholder tail (from _ph_start to the end)."""
        storage = self.text_view.textStorage()
        storage.replaceCharactersInRange_withAttributedString_(
            NSMakeRange(self._ph_start, storage.length() - self._ph_start),
            NSAttributedString.alloc().initWithString_attributes_(text, attrs),
        )

    # -- follow-up focus / layout (M6) ---------------------------------------

    def focusInput(self):
        """Make the panel key Spotlight-style: keystrokes route to the input
        field but the app is never activated (NonactivatingPanel), so the
        source app keeps visual focus. The ONLY place _allow_key is set."""
        if self.input_box is None or self.input_box.isHidden():
            return
        self.panel._allow_key = True
        self.panel.makeKeyWindow()
        self.panel.makeFirstResponder_(self.input_field)
        print("input focused, key =", bool(self.panel.isKeyWindow()), flush=True)

    def _unfocusInput(self):
        """Leave the field and hand the keyboard back to the source app.
        Flipping canBecomeKeyWindow does nothing to an already-key window —
        it is only consulted at make-key time — so the panel must leave the
        screen list for the window server to re-key the active app (which is
        still the source app: we never activated). Fallback if this ever
        blinks: NSWorkspace.frontmostApplication().activateWithOptions_()."""
        if self.panel is None:
            return
        self.panel.makeFirstResponder_(None)
        self.panel._allow_key = False
        if self.panel.isKeyWindow():
            self.panel.orderOut_(None)
            self.panel.orderFrontRegardless()
        print("input unfocused, key =", bool(self.panel.isKeyWindow()), flush=True)

    def _resetSessionUI(self):
        """New session/presentation: drop key status, hide+clear the input,
        restore default panel/scroll geometry. Must NOT cancel anything
        (_presentAt_ deliberately doesn't route through dismiss())."""
        if self.input_box is None:
            return
        if self.panel.isKeyWindow():
            self.panel.makeFirstResponder_(None)
            self.panel.orderOut_(None)  # _presentAt_ re-shows right after
        self.panel._allow_key = False
        self.input_field.setString_("")
        self.input_box.setHidden_(True)
        width = float(self.config.get("panel_width"))
        height = float(self.config.get("panel_min_height"))
        frame = self.panel.frame()
        if frame.size.width != width or frame.size.height != height:
            self.panel.setFrame_display_(
                NSMakeRect(
                    frame.origin.x,
                    frame.origin.y + frame.size.height - height,  # keep top edge
                    width,
                    height,
                ),
                False,
            )
        self._scroll.setFrame_(
            NSMakeRect(
                _PADDING, _PADDING, width - 2 * _PADDING, height - 2 * _PADDING
            )
        )
        self._followup_mode = False
        self._expanded = False
        self._input_height = _INPUT_HEIGHT
        self._height_capped = False
        self._ph_start = 0

    def _growToExpanded(self):
        """First follow-up: raise the auto-height cap to panel_height_expanded
        (§5.1) — the streamed answer then grows the panel to fit (M8), so this
        never jumps to a mostly-empty tall panel."""
        self._expanded = True
        self._height_capped = False
        cap = float(self.config.get("panel_height_expanded"))
        self._recomputeHeight()
        print(f"panel expanded to cap {cap:.0f}", flush=True)

    def _recomputeHeight(self):
        """Auto-height (M8): grow the panel to fit the transcript — top edge
        fixed (the panel hangs below the cursor), clamped to the screen's
        visible frame, capped at panel_height (panel_height_expanded once a
        follow-up session started). Grow-only; never shrinks mid-session.
        Once the cap is reached this short-circuits, so the per-token layout
        measurement stops for the rest of the stream."""
        if self.panel is None or self._height_capped:
            return
        lm = self.text_view.layoutManager()
        tc = self.text_view.textContainer()
        lm.ensureLayoutForTextContainer_(tc)
        used = lm.usedRectForTextContainer_(tc)
        inset = self.text_view.textContainerInset()
        needed = used.size.height + 2 * inset.height + 2 * _PADDING
        if self.input_box is not None and not self.input_box.isHidden():
            needed += self._input_height + _INPUT_GAP
        cap = float(
            self.config.get(
                "panel_height_expanded" if self._expanded else "panel_height"
            )
        )
        frame = self.panel.frame()
        top = frame.origin.y + frame.size.height
        screen = self.panel.screen() or NSScreen.mainScreen()
        vf = screen.visibleFrame()
        limit = min(cap, top - vf.origin.y)  # top edge genuinely never moves
        if needed >= limit:
            self._height_capped = True
        new_h = min(needed, limit)
        if new_h <= frame.size.height:
            return
        self.panel.setFrame_display_(
            NSMakeRect(frame.origin.x, top - new_h, frame.size.width, new_h),
            True,
        )
        print(f"panel height -> {new_h:.0f}", flush=True)

    def _isInputDescendant_(self, view):
        # the text view / scroller live inside the input box's view tree
        while view is not None:
            if view is self.input_box:
                return True
            view = view.superview()
        return False

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
        # other apps' events: the panel is never key from their perspective.
        # While the input IS focused, our panel is key, so a click in another
        # app or the second Esc lands here → dismiss (orderOut hands key back).
        self._maybeDismissForEvent_(event)

    def _handleLocalEvent_(self, event):
        if event.type() == NSEventTypeKeyDown:
            if (
                event.keyCode() == _ESC_KEYCODE
                and self.panel is not None
                and self.panel.isKeyWindow()
            ):
                editor = self.panel.firstResponder()
                if (
                    editor is not None
                    and hasattr(editor, "hasMarkedText")
                    and editor.hasMarkedText()
                ):
                    return event  # mid-IME composition: Esc cancels the 조합
                # first Esc: clear + leave the field, do NOT dismiss
                self.input_field.setString_("")
                self._setInputHeight_(_INPUT_HEIGHT)  # collapse multi-line input
                self.input_field.setNeedsDisplay_(True)  # repaint placeholder
                self._unfocusInput()
                return None  # swallow — field editor must not also see it
            self._maybeDismissForEvent_(event)
            return event
        # mouse down on our own windows
        if (
            self.panel is not None
            and self.panel.isVisible()
            and event.window() is self.panel
            and NSPointInRect(NSEvent.mouseLocation(), self.panel.frame())
        ):
            hit = self.panel.contentView().hitTest_(event.locationInWindow())
            if (
                self.input_box is not None
                and not self.input_box.isHidden()
                and self._isInputDescendant_(hit)
            ):
                # deterministic focus: don't rely on first-click auto-keying
                self.focusInput()
                return event  # the same click then places the caret
            if self.panel.isKeyWindow():
                # click on the transcript while typing → leave the field;
                # defer the orderOut handback until this click has dispatched
                self.panel.makeFirstResponder_(None)
                AppHelper.callAfter(self._unfocusInput)
            return event  # clicks inside the panel never dismiss (unchanged)
        self._maybeDismissForEvent_(event)
        return event

    def _maybeDismissForEvent_(self, event):
        if event.type() == NSEventTypeKeyDown:
            if event.keyCode() == _ESC_KEYCODE:
                self.dismiss()
            return
        # mouse: ignore clicks inside the panel itself
        if not NSPointInRect(NSEvent.mouseLocation(), self.panel.frame()):
            self.dismiss()

"""MainWindowController — the History/Settings window (M7, M8 glass chrome).

A regular activating window (the never-steal-focus invariant applies only to
the result panel). M8 chatbot redesign (user-directed):

- the window body is a clear Liquid Glass sheet (desktop shows through),
  with a floating glass sidebar island (기록/설정 source list + NSSwitch
  toggles for the history-save settings and 항상 위);
- History pane = AI-chatbot layout: chat transcript in the middle (user
  questions right-aligned, AI answers left-aligned, bubble style) and a
  session list on the right (snippet + datetime cards). A session is one
  original text/region request plus its follow-up records.
- Settings: the SettingsPaneController controls (M0–M6 logic unchanged),
  built into this window's pane via buildInView_.

Owned by StatusItemController (one instance, setReleasedWhenClosed_(False)).
All methods run on the main thread.
"""

import math
import os

import objc
from AppKit import (
    NSAlert,
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBox,
    NSBoxCustom,
    NSButton,
    NSColor,
    NSEventModifierFlagCommand,
    NSFloatingWindowLevel,
    NSFocusRingTypeNone,
    NSFont,
    NSFontAttributeName,
    NSFontWeightMedium,
    NSForegroundColorAttributeName,
    NSMutableParagraphStyle,
    NSParagraphStyleAttributeName,
    NSImage,
    NSImageView,
    NSMakeRect,
    NSNoTabsNoBorder,
    NSNormalWindowLevel,
    NSObject,
    NSPasteboard,
    NSPasteboardTypeString,
    NSScrollView,
    NSSearchToolbarItem,
    NSSwitch,
    NSTableCellView,
    NSTableColumn,
    NSTableView,
    NSTableViewSelectionHighlightStyleNone,
    NSTableViewStyleInset,
    NSTableViewStyleSourceList,
    NSTabView,
    NSTabViewItem,
    NSTextField,
    NSToolbar,
    NSToolbarDisplayModeIconOnly,
    NSToolbarFlexibleSpaceItemIdentifier,
    NSView,
    NSViewHeightSizable,
    NSViewMaxXMargin,
    NSViewMinXMargin,
    NSViewMinYMargin,
    NSViewWidthSizable,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialSidebar,
    NSVisualEffectMaterialUnderWindowBackground,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskFullSizeContentView,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
    NSWindowToolbarStyleUnified,
)
from Foundation import (
    NSAttributedString,
    NSIndexSet,
    NSMakeSize,
    NSMutableAttributedString,
)

from assistant import risk
from config import asset_dir
from i18n import current_language, t
from settings_window import SettingsPaneController, pane_min_size
from ui_kit import (
    FlippedView as _FlippedView,
    handle_edit_key_equivalent as _handle_edit_key_equivalent,
    make_pill as _make_pill,
    make_round_field as _make_round_field,
)

# Liquid Glass (M8) — same guard as result_panel.py. Style 1 == clear
# (NSGlassEffectViewStyleClear): the high-transparency look the user asked
# for; "regular"(0) is the frosted variant.
try:
    _GlassEffectView = objc.lookUpClass("NSGlassEffectView")
except objc.error:
    _GlassEffectView = None
_GLASS_STYLES = {"regular": 0, "clear": 1}

# M8 폴리시 scale-up (user feedback): boxes ×1.3, fonts ×1.15
PADDING = 16
ROW_HEIGHT = 24
CONTENT_WIDTH = 1170.0
CONTENT_HEIGHT = 860.0
WINDOW_RADIUS = 26.0  # big rounded glass sheet — edges show through
SIDEBAR_WIDTH = 210.0
SIDEBAR_INSET = 10.0  # the sidebar floats — gap to the window edges
SIDEBAR_RADIUS = 14.0
SESSIONS_WIDTH = 364.0  # right-hand session list column
ASSIST_COL_W = 860.0  # 비서 탭: readable, centered content column (chat-style)
_GUTTER = 18.0  # 비서 탭 left content gutter — aligns headers/lines with card text
BUBBLE_RADIUS = 14.0
BUBBLE_PAD = 12.0
BUBBLE_GAP = 14.0
CAPTION_H = 18.0
FONT_BODY = 15.0  # 13 × 1.15
FONT_SMALL = 12.0  # captions / session sublines
FONT_UI = 14.0  # buttons, switch labels, session titles
_SEARCH_ITEM_ID = "search"

def _assistant_section(doc, y, width, title, count=None):
    """Module-level (NOT a method): NSObject-subclass methods need selector
    arity (project memory pyobjc-selector-arg-naming). Returns the next y.
    `count` (when given and >0) is appended as a subtle tally, e.g. '비서 제안  3'."""
    from AppKit import NSLineBreakByTruncatingTail
    if count:
        title = f"{title} ({count})"
    label = NSTextField.labelWithString_(title)
    label.setFont_(NSFont.boldSystemFontOfSize_(13.0))
    label.setTextColor_(NSColor.secondaryLabelColor())
    label.setLineBreakMode_(NSLineBreakByTruncatingTail)
    label.setFrame_(NSMakeRect(_GUTTER, y + 10, width - _GUTTER - 8, 18))
    doc.addSubview_(label)
    return y + 36.0


def _assistant_empty(doc, y, width, text):
    from AppKit import NSLineBreakByTruncatingTail
    label = NSTextField.labelWithString_(text)
    label.setFont_(NSFont.systemFontOfSize_(12.0))
    label.setTextColor_(NSColor.tertiaryLabelColor())
    label.setLineBreakMode_(NSLineBreakByTruncatingTail)
    label.setFrame_(NSMakeRect(_GUTTER, y + 2, width - _GUTTER - 8, 18))
    label.setToolTip_(text)
    doc.addSubview_(label)
    return y + 26.0


def _assistant_status(doc, y, width, text, connected):
    """Live connection-state line — primary metadata (secondaryLabel), with a
    state-colored ⌁ dot so it reads as a live indicator, not tutorial copy."""
    from AppKit import NSLineBreakByTruncatingTail
    rgb = (0.16, 0.55, 0.27) if connected else (0.55, 0.58, 0.62)  # _C_GREEN/_C_GRAY
    dot = NSBox.alloc().initWithFrame_(NSMakeRect(_GUTTER, y + 7, 8, 8))
    dot.setBoxType_(NSBoxCustom)
    dot.setTitlePosition_(0)
    dot.setBorderWidth_(0.0)
    dot.setCornerRadius_(4.0)
    dot.setContentViewMargins_(NSMakeSize(0, 0))
    dot.setFillColor_(NSColor.colorWithRed_green_blue_alpha_(*rgb, 1.0))
    doc.addSubview_(dot)
    label = NSTextField.labelWithString_(text)
    label.setFont_(NSFont.systemFontOfSize_(12.0))
    label.setTextColor_(NSColor.secondaryLabelColor())
    label.setLineBreakMode_(NSLineBreakByTruncatingTail)
    label.setFrame_(NSMakeRect(_GUTTER + 14, y + 2, width - _GUTTER - 22, 18))
    label.setToolTip_(text)
    doc.addSubview_(label)
    return y + 26.0


# Shared palette — single source of truth for chip/dot/accent fills. Darkened
# from the first pass so white text clears AA-large contrast on the fills (the
# old bright orange was unreadable at 2.17:1). One place to tweak the theme.
_C_GREEN = (0.16, 0.55, 0.27)
_C_AMBER = (0.80, 0.47, 0.04)
_C_RED = (0.84, 0.23, 0.23)
_C_BLUE = (0.0, 0.42, 0.86)
_C_GRAY = (0.55, 0.58, 0.62)

# Risk class -> (i18n label key, RGB chip color). Mirrors proposal_panel.py so a
# proposal card reads its safety class the same way the floating panel does.
_RISK_LABEL = {
    risk.AUTO: "assistant.risk_auto",
    risk.CONFIRM: "assistant.risk_confirm",
    risk.NEVER_AUTO: "assistant.risk_never",
}
_RISK_RGB = {
    risk.AUTO: _C_GREEN,
    risk.CONFIRM: _C_AMBER,
    risk.NEVER_AUTO: _C_RED,
}
# kinds that carry a deterministic "what happens if I approve" line (i18n
# assistant.effect_<kind>); others render no effect line.
_EFFECT_KINDS = frozenset((
    "todo_add", "reply_draft", "send_reply", "remote_dispatch",
    "calendar_write", "calendar_delete", "send_money",
))
_ACCENT_BLUE = _C_BLUE


def _card_box(y, card_w, card_h):
    """A near-opaque card with a hairline border — reads cleanly over the glass
    window on any desktop (the half-transparent fill was the muddy look)."""
    box = NSBox.alloc().initWithFrame_(NSMakeRect(4, y, card_w, card_h))
    box.setBoxType_(NSBoxCustom)
    box.setTitlePosition_(0)
    box.setBorderType_(1)  # NSLineBorder
    box.setBorderWidth_(1.0)
    box.setBorderColor_(NSColor.separatorColor())
    box.setCornerRadius_(12.0)
    box.setContentViewMargins_(NSMakeSize(0, 0))
    box.setFillColor_(
        NSColor.textBackgroundColor().colorWithAlphaComponent_(0.92))
    return box, box.contentView()


def _accent_button(title, target, action, tag, frame, rgb):
    """A filled, white-label pill for the primary action on a card (승인/이어서).
    Plain NSButton (not PillButton) so the fixed fill isn't reset on hover. The
    NSBezelStyleRegularSquare + centered paragraph style is the same recipe the
    floating proposal panel uses to center white pill titles reliably."""
    from AppKit import NSBezelStyleRegularSquare, NSNoImage

    b = NSButton.alloc().initWithFrame_(frame)
    b.setBezelStyle_(NSBezelStyleRegularSquare)
    b.setBordered_(False)
    b.setImagePosition_(NSNoImage)  # no image slot to push the title sideways
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(frame.size.height / 2.0)
    b.layer().setMasksToBounds_(True)
    r, g, bl = rgb
    b.layer().setBackgroundColor_(
        NSColor.colorWithRed_green_blue_alpha_(r, g, bl, 1.0).CGColor())
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(2)  # NSTextAlignmentCenter
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(
        title, {
            NSForegroundColorAttributeName: NSColor.whiteColor(),
            NSFontAttributeName: NSFont.boldSystemFontOfSize_(13.0),
            NSParagraphStyleAttributeName: para,
        }))
    b.setAlignment_(2)  # cell alignment, applied AFTER the attributed title
    b.setTarget_(target)
    b.setAction_(action)
    b.setTag_(tag)
    return b


# Thread status -> (human i18n label key, dot RGB).
# thread source -> a small provenance glyph on the card title (external sources
# only; manual/capture get none so the title stays clean).
_SOURCE_GLYPH = {
    "remote": "🖥",
    "gmail": "📧",
    "calendar": "📅",
}
_STATUS_META = {
    "active": ("assistant.status_active", _C_GREEN),
    "done": ("assistant.status_done", _C_GRAY),
    "paused": ("assistant.status_paused", _C_AMBER),
    "blocked": ("assistant.status_paused", _C_RED),
}


def _rel_time(hrs):
    """A float hour-count -> a short localized 'when' string (방금 / N시간 전 /
    N일 전). hrs comes from ThreadStore.idle_hours."""
    try:
        hrs = float(hrs)
    except (TypeError, ValueError):
        return ""
    if hrs < 1 / 60.0:
        return t("assistant.just_now")
    if hrs < 1:
        return t("assistant.min_ago").format(m=max(1, round(hrs * 60)))
    if hrs < 24:
        return t("assistant.idle_ago").format(h=round(hrs))
    return t("assistant.days_ago").format(d=round(hrs / 24))


def _subtle_button(title, target, action, tag, frame):
    """A secondary card action — the app's gray hover pill (PillButton)."""
    b = _make_pill(title, target, action, frame)
    b.setTag_(tag)
    return b


def _mode_label(mode):
    key = {"text": "history.mode_text", "region": "history.mode_region",
           "followup": "history.mode_followup"}.get(mode)
    return t(key) if key else str(mode)


def _short_ts(record):
    return str(record.get("ts", ""))[5:16].replace("T", " ")  # "MM-DD HH:MM"


def _build_sessions(records):
    """Group newest-first records into sessions: a text/region record plus
    the follow-up records that came after it (chronological order inside)."""
    sessions = []
    for record in reversed(records):  # oldest → newest
        if record.get("mode") == "followup" and sessions:
            sessions[-1]["records"].append(record)
        else:
            sessions.append({"records": [record]})
    sessions.reverse()  # newest session first
    return sessions


def _session_transcript(session):
    parts = []
    for record in session["records"]:
        parts.append(f"{t('history.transcript_q')}\n{record.get('input', '')}")
        parts.append(f"{t('history.transcript_a')}\n{record.get('response', '')}")
    return "\n\n".join(parts)


class _MainWindow(NSWindow):
    """⌘W closes the window, and ⌘A/C/V/X/Z/⇧⌘Z drive the focused text field.
    An Accessory app has no main menu, so there is no Edit/Close menu item to
    provide these key equivalents — handle them here. Match by keyCode (⌘W is
    kVK_ANSI_W = 13), never by character: under the Korean 2-set layout ⌘W
    reports 'ㅈ' (hard rule #1)."""

    def performKeyEquivalent_(self, event):
        if _handle_edit_key_equivalent(self, event):
            return True
        if (event.modifierFlags() & NSEventModifierFlagCommand
                and event.keyCode() == 13):
            self.performClose_(None)
            return True
        return objc.super(_MainWindow, self).performKeyEquivalent_(event)


class _SidebarController(NSObject):
    """Datasource/delegate for the source-list sidebar (M8). A separate
    object on purpose: MainWindowController already serves the sessions table
    and a shared delegate would make every callback ambiguous. Codex-style
    cells: SF Symbol icon + 15pt label (view-based)."""

    _ITEMS = (  # (key, i18n label key, SF Symbol)
        ("history", "history.nav_history", "clock.arrow.circlepath"),
        ("assistant", "history.nav_assistant", "sparkles"),
        ("settings", "history.nav_settings", "gearshape"),
    )

    def initWithOwner_(self, owner):
        self = objc.super(_SidebarController, self).init()
        if self is None:
            return None
        self.owner = owner
        self.table = None
        return self

    def numberOfRowsInTableView_(self, table):
        return len(self._ITEMS)

    def tableView_viewForTableColumn_row_(self, table, column, row):
        """Codex-style item: rounded pill drawn by the cell itself — the
        system source-list capsule re-tiled the row on selection, which made
        the items wobble a few px (user-reported). Selected = accent pill
        with white icon/label; geometry never changes."""
        _key, label_key, symbol = self._ITEMS[row]
        label = t(label_key)
        selected = row == self.table.selectedRow()
        w = float(column.width()) if column is not None else SIDEBAR_WIDTH - 20
        cell = NSTableCellView.alloc().initWithFrame_(NSMakeRect(0, 0, w, 36))
        pill = NSBox.alloc().initWithFrame_(NSMakeRect(0, 2, w, 32))
        pill.setBoxType_(NSBoxCustom)
        pill.setTitlePosition_(0)
        pill.setBorderWidth_(0.0)
        pill.setCornerRadius_(9.0)
        pill.setContentViewMargins_(NSMakeSize(0, 0))
        pill.setFillColor_(
            NSColor.controlAccentColor() if selected else NSColor.clearColor()
        )
        cell.addSubview_(pill)
        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(10, 5, 22, 22))
        icon.setImage_(
            NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                symbol, label
            )
        )
        icon.setContentTintColor_(
            NSColor.whiteColor() if selected else NSColor.secondaryLabelColor()
        )
        pill.contentView().addSubview_(icon)
        text = NSTextField.labelWithString_(label)
        text.setFont_(NSFont.systemFontOfSize_(15.0))
        text.setTextColor_(
            NSColor.whiteColor() if selected else NSColor.labelColor()
        )
        text.setFrame_(NSMakeRect(40, 6, w - 50, 20))
        pill.contentView().addSubview_(text)
        cell.setImageView_(icon)
        cell.setTextField_(text)
        return cell

    def tableViewSelectionDidChange_(self, notification):
        row = self.table.selectedRow()
        previous = getattr(self, "_last_row", -1)
        self._last_row = row
        from Foundation import NSMutableIndexSet
        index_set = NSMutableIndexSet.indexSet()
        for r in {previous, row}:
            if 0 <= r < len(self._ITEMS):
                index_set.addIndex_(r)
        if index_set.count():
            self.table.reloadDataForRowIndexes_columnIndexes_(
                index_set, NSIndexSet.indexSetWithIndex_(0)
            )
        if 0 <= row < len(self._ITEMS):
            self.owner._sidebarSelected_(self._ITEMS[row][0])

    def selectIdentifier_(self, identifier):
        for i, (key, _label, _symbol) in enumerate(self._ITEMS):
            if key == identifier:
                self.table.selectRowIndexes_byExtendingSelection_(
                    NSIndexSet.indexSetWithIndex_(i), False
                )
                return


class MainWindowController(NSObject):
    def initWithConfig_history_(self, config, history):
        self = objc.super(MainWindowController, self).init()
        if self is None:
            return None
        self.config = config
        self.history = history
        self.settings = SettingsPaneController.alloc().initWithConfig_(config)
        self.on_reask = None  # set by main.py: ExplainController.resubmit_text
        self.on_reask_image = None  # main.py: ExplainController.resubmit_image
        self.window = None
        self.tab_view = None
        self.sidebar = _SidebarController.alloc().initWithOwner_(self)
        self.sidebar_effect = None
        self.search_field = None  # the unified toolbar's search field (M8)
        self.assistant_bridge = None  # HermesBridge, set by AssistantController
        self.assistant_threads = None  # ThreadStore (M14)
        self.assistant_proposals = None  # ProposalStore (M14)
        self.on_assistant_approve = None
        self.on_assistant_skip = None
        self.on_assistant_snooze = None
        self.on_assistant_answer = None      # text -> explain.answer_question
        self.on_assistant_remote = None      # text -> controller.delegate_remote
        self.on_assistant_propose = None     # text -> controller.handlePropose_
        self.on_assistant_new_thread = None  # text -> controller.new_thread
        self.on_assistant_scan = None        # -> controller.handleScan
        self.on_assistant_send = None        # text -> controller.handleSend_ (router)
        self.on_assistant_resume = None      # tid -> controller.resume_thread
        self.on_assistant_complete = None    # tid -> controller.complete_thread
        self.on_assistant_delete_thread = None  # tid -> controller.delete_thread
        self.assistant_scroll = None
        self.assistant_doc = None
        self.assistant_input = None
        self.assistant_wrap = None
        self._routing_box = None  # transient echo row while the router runs
        self._toast_box = None    # transient action-confirmation row
        self._pending_toast = None  # text queued to draw after the next refresh
        self._busy_thread = None  # tid of the thread whose 이어서 is streaming
        self._busy_ts = None      # monotonic stamp → watchdog clears a stuck busy
        self._inbox = []  # pending proposals (index == button tag)
        self._threads = []  # in-progress threads (index == button tag)
        self.table = None  # session list (right column)
        self.chat_scroll = None
        self.chat_doc = None
        self.copy_button = None
        self.reask_button = None
        self.enabled_switch = None
        self.save_images_switch = None
        self.save_text_switch = None
        self.floating_switch = None
        self._all = []  # all sessions, newest first
        self._filtered = []  # sessions currently in the list
        history.on_appended = self._historyAppended
        return self

    # -- showing ---------------------------------------------------------------

    def showHistory(self):
        self._show_("history")

    def showSettings(self):
        self._show_("settings")

    def showAssistant(self):
        self._show_("assistant")

    def runOnboardingIfNeeded(self):
        """First run of a downloaded .app (M13): the user hasn't picked a
        backend yet, so guide them. External API → land on the Settings
        Connection pane (tested entry UI); Local → show the install command.
        Marked done either way so it shows exactly once."""
        if bool(self.config.get("onboarded")):
            return
        print("onboarding: first run — no backend configured yet", flush=True)
        self.showSettings()  # brings the app forward; pane is ready behind the dialog
        alert = NSAlert.alloc().init()
        alert.setMessageText_(t("onboard.title"))
        alert.setInformativeText_(t("onboard.body"))
        alert.addButtonWithTitle_(t("onboard.external"))  # first = default
        alert.addButtonWithTitle_(t("onboard.local"))
        alert.addButtonWithTitle_(t("onboard.later"))
        icon = NSImage.alloc().initWithContentsOfFile_(
            str(asset_dir() / "macsist-1024.png")
        )
        if icon is not None:
            alert.setIcon_(icon)
        choice = alert.runModal()
        self.config.set("onboarded", True)
        self.config.save()
        print(f"onboarding: choice={int(choice)}", flush=True)
        if choice == NSAlertSecondButtonReturn:  # local model
            info = NSAlert.alloc().init()
            info.setMessageText_(t("onboard.local_title"))
            info.setInformativeText_(t("onboard.local_body"))
            if icon is not None:
                info.setIcon_(icon)
            info.runModal()
        # external (first) / later (third): the Connection pane is already shown

    def toggleHistory(self):
        """Global hotkey (main thread via callAfter): show the History tab,
        or close the window when it's already in front."""
        if (self.window is not None and self.window.isVisible()
                and self.window.isKeyWindow()):
            self.window.performClose_(None)
        else:
            self.showHistory()

    def _show_(self, tab_id):
        if self.window is None:
            self._buildWindow()
        self.tab_view.selectTabViewItemWithIdentifier_(tab_id)
        self.sidebar.selectIdentifier_(tab_id)
        self._refreshTab_(tab_id)
        origin_env = os.environ.get("HE_DEBUG_WIN_ORIGIN")
        if origin_env:
            x, y = (float(v) for v in origin_env.split(","))
            self.window.setFrameOrigin_((x, y))
        # While the window is up the app is a Regular app — Dock + Cmd-Tab.
        # windowWillClose_ drops back to Accessory (menu-bar only).
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        print(
            f"main window shown tab={tab_id} frame={self.window.frame()}"
            f" visible={bool(self.window.isVisible())}",
            flush=True,
        )

    def windowDidResize_(self, notification):
        # keep the 비서 column centered and re-lay its cards at the new width on
        # live resize (debounced — the card rebuild shouldn't run every drag tick).
        from AppKit import NSObject as _NSObject
        if self.assistant_wrap is None:
            return
        _NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "relayoutAssistant", None)
        self.performSelector_withObject_afterDelay_(
            "relayoutAssistant", None, 0.06)

    def relayoutAssistant(self):
        wrap = self.assistant_wrap
        if wrap is None or wrap.superview() is None:
            return
        cw = wrap.superview().frame().size.width
        col_w = min(cw - 2 * PADDING, ASSIST_COL_W)
        x0 = round((cw - col_w) / 2.0)
        wrap.setFrame_(NSMakeRect(x0, 0, col_w, wrap.superview().frame().size.height))
        # children reflow via their autoresizing masks; re-lay the cards to the
        # new column width (scroll content width tracks the wrap via WidthSizable).
        if (self.tab_view is not None
                and str(self.tab_view.selectedTabViewItem().identifier())
                == "assistant"):
            self.refreshAssistant()

    def windowWillClose_(self, notification):
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        # Drop the window so the next open rebuilds fresh — this is how 창 모양
        # (window glass/opacity) and other appearance changes take effect after
        # a Settings save, without rebuilding mid-session (which reset scroll).
        self.window = None
        self.tab_view = None
        print("main window closed -> Accessory policy", flush=True)

    def _refreshTab_(self, tab_id):
        if tab_id == "history":
            self.refreshHistory()
        elif tab_id == "assistant":
            self.refreshAssistant()
        else:
            self.settings.refresh()

    def tabView_didSelectTabViewItem_(self, tab_view, item):
        # programmatic selection also lands here — same refresh as the menu
        self._refreshTab_(str(item.identifier()))

    def _sidebarSelected_(self, identifier):
        # sidebar click (M8) — the tab selection above triggers the refresh
        self.tab_view.selectTabViewItemWithIdentifier_(identifier)
        print(f"sidebar selected {identifier}", flush=True)

    # -- toolbar (M8: unified glass toolbar hosting the search field) ----------

    def toolbarDefaultItemIdentifiers_(self, toolbar):
        return [NSToolbarFlexibleSpaceItemIdentifier, _SEARCH_ITEM_ID]

    def toolbarAllowedItemIdentifiers_(self, toolbar):
        return [NSToolbarFlexibleSpaceItemIdentifier, _SEARCH_ITEM_ID]

    def toolbar_itemForItemIdentifier_willBeInsertedIntoToolbar_(
        self, toolbar, identifier, will_insert
    ):
        if str(identifier) != _SEARCH_ITEM_ID:
            return None
        item = NSSearchToolbarItem.alloc().initWithItemIdentifier_(
            _SEARCH_ITEM_ID
        )
        item.setPreferredWidthForSearchField_(240.0)
        field = item.searchField()
        field.setPlaceholderString_(t("history.search_placeholder"))
        field.setTarget_(self)
        field.setAction_("searchChanged:")
        field.setSendsSearchStringImmediately_(True)
        self.search_field = field
        return item

    # -- build -------------------------------------------------------------------

    def _glassStyle(self):
        # window-specific (separate from the explain panel's glass_style)
        return _GLASS_STYLES.get(str(self.config.get("window_glass_style")), 0)

    def _useGlass(self):
        return _GlassEffectView is not None and bool(
            self.config.get("window_glass_enabled")
        )

    def _buildWindow(self):
        pane_w, pane_h = pane_min_size()
        content_x = SIDEBAR_INSET + SIDEBAR_WIDTH + 8  # right of the island
        width = content_x + max(CONTENT_WIDTH, pane_w + PADDING * 2)
        height = max(CONTENT_HEIGHT, pane_h + PADDING)
        # Full-size content view: the glass body runs the full window height
        # under the transparent titlebar/toolbar. Panes are laid out within
        # contentLayoutRect height so they never sit under the toolbar.
        self.window = _MainWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
            | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Macsist")
        self.window.setTitlebarAppearsTransparent_(True)
        # floor the window so the 비서 column never narrows enough to clip the
        # card button rows (sidebar island + a comfortable content column).
        self.window.setContentMinSize_(
            NSMakeSize(content_x + 540.0, 520.0))
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)  # windowWillClose_ → Accessory policy
        self._applyFloating()

        # M8 glass toolbar — on macOS 26 a unified toolbar gets the Liquid
        # Glass treatment automatically; it hosts the history search field.
        toolbar = NSToolbar.alloc().initWithIdentifier_("MacsistToolbar")
        toolbar.setDelegate_(self)
        toolbar.setAllowsUserCustomization_(False)
        toolbar.setDisplayMode_(NSToolbarDisplayModeIconOnly)  # no item labels
        self.window.setToolbar_(toolbar)
        self.window.setToolbarStyle_(NSWindowToolbarStyleUnified)

        # grow the window by the titlebar+toolbar height so the panes keep
        # their full design height below the toolbar
        chrome_h = height - self.window.contentLayoutRect().size.height
        total_h = height + chrome_h
        self.window.setContentSize_((width, total_h))
        print(f"main window chrome_h={chrome_h:.0f}", flush=True)

        # design height of the pane area (below the toolbar) — rebuildContent
        # (M11 language switch) re-derives the rest from the live contentView
        self._design_height = height
        self._buildContent()

        # first open lands screen-centered (it spawned bottom-left otherwise);
        # the position the user drags it to is kept for later opens
        self.window.center()

    def _buildContent(self):
        content = self.window.contentView()
        size = content.frame().size
        width, total_h = size.width, size.height
        height = self._design_height
        content_x = SIDEBAR_INSET + SIDEBAR_WIDTH + 8
        use_glass = self._useGlass()

        # Translucent glass sheet body (user feedback round 2: clear was too
        # transparent — frosted glass + a windowBackground tint keeps text
        # readable while the desktop still shows through). The big corner
        # radius + non-opaque window leaves the window edges genuinely
        # transparent outside the rounded sheet.
        self.window.setOpaque_(False)
        self.window.setBackgroundColor_(NSColor.clearColor())
        tint_alpha = float(self.config.get("window_tint_alpha"))
        if use_glass:
            body = _GlassEffectView.alloc().initWithFrame_(
                NSMakeRect(0, 0, width, total_h)
            )
            body.setStyle_(self._glassStyle())
            body.setCornerRadius_(WINDOW_RADIUS)
            if tint_alpha > 0:
                body.setTintColor_(
                    NSColor.windowBackgroundColor().colorWithAlphaComponent_(
                        tint_alpha
                    )
                )
        else:
            body = NSVisualEffectView.alloc().initWithFrame_(
                NSMakeRect(0, 0, width, total_h)
            )
            body.setMaterial_(NSVisualEffectMaterialUnderWindowBackground)
            body.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            body.setState_(NSVisualEffectStateActive)
            body.setWantsLayer_(True)
            body.layer().setCornerRadius_(WINDOW_RADIUS)
            body.layer().setMasksToBounds_(True)
        body.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content.addSubview_(body)
        print(
            f"window body={type(body).__name__} glass={use_glass} "
            f"style={self._glassStyle()} tint={tint_alpha:g} "
            f"radius={WINDOW_RADIUS:g}",
            flush=True,
        )

        # Floating glass sidebar island (Finder style): inset from every
        # window edge, rounded, traffic lights sitting on top of it.
        island_h = total_h - 2 * SIDEBAR_INSET
        island = NSMakeRect(SIDEBAR_INSET, SIDEBAR_INSET, SIDEBAR_WIDTH,
                            island_h)
        if use_glass:
            backdrop = _GlassEffectView.alloc().initWithFrame_(island)
            backdrop.setCornerRadius_(SIDEBAR_RADIUS)
            backdrop.setStyle_(self._glassStyle())
            side_host = NSView.alloc().initWithFrame_(
                NSMakeRect(0, 0, SIDEBAR_WIDTH, island_h)
            )
            backdrop.setContentView_(side_host)
        else:
            backdrop = NSVisualEffectView.alloc().initWithFrame_(island)
            backdrop.setMaterial_(NSVisualEffectMaterialSidebar)
            backdrop.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            backdrop.setState_(NSVisualEffectStateActive)
            backdrop.setWantsLayer_(True)
            backdrop.layer().setCornerRadius_(SIDEBAR_RADIUS)
            backdrop.layer().setMasksToBounds_(True)
            side_host = backdrop
        content.addSubview_(backdrop)
        self.sidebar_effect = backdrop
        print(
            f"sidebar island={type(backdrop).__name__} glass={use_glass}",
            flush=True,
        )

        # source list (기록/비서/설정) at the island top, below the traffic lights
        list_h = len(self.sidebar._ITEMS) * 36.0 + 8
        side_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, island_h - 44 - list_h, SIDEBAR_WIDTH, list_h)
        )
        side_scroll.setDrawsBackground_(False)
        side_table = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, SIDEBAR_WIDTH, list_h)
        )
        side_table.setStyle_(NSTableViewStyleSourceList)
        side_table.setFocusRingType_(NSFocusRingTypeNone)
        side_table.setBackgroundColor_(NSColor.clearColor())
        side_table.setRowHeight_(36.0)
        # the cell draws its own selection pill — the system capsule
        # re-tiles rows on selection and made the sidebar wobble
        side_table.setSelectionHighlightStyle_(
            NSTableViewSelectionHighlightStyleNone
        )
        column = NSTableColumn.alloc().initWithIdentifier_("item")
        column.setWidth_(SIDEBAR_WIDTH - 20)
        side_table.addTableColumn_(column)
        side_table.setHeaderView_(None)
        side_table.setAllowsMultipleSelection_(False)
        side_table.setDataSource_(self.sidebar)
        side_table.setDelegate_(self.sidebar)
        self.sidebar.table = side_table
        side_scroll.setDocumentView_(side_table)
        side_host.addSubview_(side_scroll)

        # toggle switches at the island bottom (user feedback: switches, not
        # checkboxes, and they live in the sidebar)
        self.enabled_switch = self._addSwitchTo_y_title_action_(
            side_host, 14 + 3 * 36, t("history.save_master"), "toggleEnabled:"
        )
        self.save_images_switch = self._addSwitchTo_y_title_action_(
            side_host, 14 + 2 * 36, t("history.save_images"), "toggleSaveImages:"
        )
        self.save_text_switch = self._addSwitchTo_y_title_action_(
            side_host, 14 + 1 * 36, t("history.save_text"), "toggleSaveText:"
        )
        self.floating_switch = self._addSwitchTo_y_title_action_(
            side_host, 14, t("history.floating"), "toggleFloating:"
        )

        # tabless tab view fills the area right of the island, below the
        # toolbar (its height is the pre-chrome design height)
        self.tab_view = NSTabView.alloc().initWithFrame_(
            NSMakeRect(content_x, 0, width - content_x, height)
        )
        self.tab_view.setTabViewType_(NSNoTabsNoBorder)
        self.tab_view.setDelegate_(self)
        content.addSubview_(self.tab_view)

        rect = self.tab_view.contentRect()
        cw, ch = rect.size.width, rect.size.height

        history_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        self._buildHistoryTab_(history_view)
        item = NSTabViewItem.alloc().initWithIdentifier_("history")
        item.setLabel_("History")
        item.setView_(history_view)
        self.tab_view.addTabViewItem_(item)

        assistant_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        self._buildAssistantTab_(assistant_view)
        item = NSTabViewItem.alloc().initWithIdentifier_("assistant")
        item.setLabel_("Assistant")
        item.setView_(assistant_view)
        self.tab_view.addTabViewItem_(item)

        settings_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        self.settings.buildInView_(settings_view)
        item = NSTabViewItem.alloc().initWithIdentifier_("settings")
        item.setLabel_("Settings")
        item.setView_(settings_view)
        self.tab_view.addTabViewItem_(item)

    def rebuildContent(self):
        """Tear down and rebuild every pane in the current language (M11).
        Must NOT be called synchronously from an action inside the hierarchy
        being torn down (the settings Save button) — main.py defers it via
        AppHelper.callAfter."""
        if self.window is None:
            return  # nothing built yet — next _show_ builds fresh
        current_tab = str(self.tab_view.selectedTabViewItem().identifier()) \
            if self.tab_view is not None else "history"
        for sub in list(self.window.contentView().subviews()):
            sub.removeFromSuperview()
        self.sidebar._last_row = -1
        self._last_selected_row = -1
        self._buildContent()
        if self.search_field is not None:
            self.search_field.setPlaceholderString_(
                t("history.search_placeholder")
            )
        self.refreshHistory()  # switch states live here, not in _buildContent
        self.tab_view.selectTabViewItemWithIdentifier_(current_tab)
        self.sidebar.selectIdentifier_(current_tab)
        self._refreshTab_(current_tab)
        print(f"window content rebuilt lang={current_language()}", flush=True)

    def _addSwitchTo_y_title_action_(self, host, y, title, action):
        label = NSTextField.labelWithString_(title)
        label.setFont_(NSFont.systemFontOfSize_(FONT_UI))
        label.setFrame_(NSMakeRect(16, y + 5, SIDEBAR_WIDTH - 80, 17))
        host.addSubview_(label)
        switch = NSSwitch.alloc().initWithFrame_(
            NSMakeRect(SIDEBAR_WIDTH - 16 - 40, y, 40, 26)
        )
        switch.setTarget_(self)
        switch.setAction_(action)
        host.addSubview_(switch)
        return switch

    def _buildHistoryTab_(self, container):
        size = container.frame().size
        cw, ch = size.width, size.height
        sessions_x = cw - PADDING - SESSIONS_WIDTH
        chat_w = sessions_x - 8 - PADDING

        # bottom-left: actions for the selected session (rounded pill style)
        self.copy_button = _make_pill(
            t("history.copy"), self, "copyResponse:",
            NSMakeRect(PADDING, PADDING, 96, 34),
        )
        container.addSubview_(self.copy_button)
        self.reask_button = _make_pill(
            t("history.reask"), self, "reask:",
            NSMakeRect(PADDING + 104, PADDING, 120, 34),
        )
        container.addSubview_(self.reask_button)

        # middle: the chat transcript (AI left, user right)
        chat_y = PADDING + ROW_HEIGHT + 8
        self.chat_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(PADDING, chat_y, chat_w, ch - chat_y - PADDING)
        )
        self.chat_scroll.setHasVerticalScroller_(True)
        self.chat_scroll.setDrawsBackground_(False)
        self.chat_doc = _FlippedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, chat_w, 10)
        )
        self.chat_scroll.setDocumentView_(self.chat_doc)
        container.addSubview_(self.chat_scroll)

        # right: session cards (snippet + datetime), chatbot-style
        sess_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(sessions_x, PADDING, SESSIONS_WIDTH, ch - PADDING * 2)
        )
        sess_scroll.setHasVerticalScroller_(True)
        sess_scroll.setDrawsBackground_(False)
        self.table = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, SESSIONS_WIDTH, ch - PADDING * 2)
        )
        self.table.setStyle_(NSTableViewStyleInset)
        self.table.setFocusRingType_(NSFocusRingTypeNone)
        self.table.setBackgroundColor_(NSColor.clearColor())
        self.table.setRowHeight_(64.0)
        # selection is drawn by the card itself (rounded grid, Codex-style)
        self.table.setSelectionHighlightStyle_(
            NSTableViewSelectionHighlightStyleNone
        )
        column = NSTableColumn.alloc().initWithIdentifier_("session")
        column.setWidth_(SESSIONS_WIDTH - 24)
        self.table.addTableColumn_(column)
        self.table.setHeaderView_(None)
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setAllowsMultipleSelection_(False)
        sess_scroll.setDocumentView_(self.table)
        container.addSubview_(sess_scroll)

    # -- assistant (M13: read-only kanban cockpit) -------------------------------

    def _buildAssistantTab_(self, container):
        size = container.frame().size
        cw, ch = size.width, size.height
        bar_h = 44.0
        # Readable, centered column (chat-style) — full-width cards on a wide
        # window look stretched and empty. The column re-centers on resize via
        # flexible left/right autoresizing margins on the wrapper.
        col_w = min(cw - 2 * PADDING, ASSIST_COL_W)
        x0 = round((cw - col_w) / 2.0)
        wrap = NSView.alloc().initWithFrame_(NSMakeRect(x0, 0, col_w, ch))
        wrap.setAutoresizingMask_(
            NSViewMinXMargin | NSViewMaxXMargin | NSViewHeightSizable)
        container.addSubview_(wrap)
        self.assistant_wrap = wrap  # re-framed on window resize (keeps centered)

        bar_y = ch - PADDING - bar_h
        send_w, refresh_w, gap = 84.0, 34.0, 8.0
        field_w = col_w - (send_w + refresh_w + 2 * gap)
        # single input box — the local LLM routes the text to the right action
        # (answer / todo / thread / remote / scan). One 전송 pill; Return sends.
        box, field = _make_round_field(
            NSMakeRect(0, bar_y + 6, field_w, 32), 14.0)
        box.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        field.setPlaceholderString_(t("assistant.input_placeholder"))
        field.setTarget_(self)
        field.setAction_("sendClicked:")  # Return = 전송 (router decides)
        self.assistant_input = field
        wrap.addSubview_(box)
        # manual refresh — "check now" (pokes the proactive scan + re-reads)
        refresh = _make_pill(
            "↻", self, "refreshClicked:",
            NSMakeRect(field_w + gap, bar_y + 7, refresh_w, 30))
        refresh.setToolTip_(t("assistant.refresh_tip"))
        refresh.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
        wrap.addSubview_(refresh)
        send = _make_pill(
            t("assistant.send"), self, "sendClicked:",
            NSMakeRect(col_w - send_w, bar_y + 7, send_w, 30))
        send.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
        wrap.addSubview_(send)
        # scroll area below the toolbar
        self.assistant_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, PADDING, col_w, bar_y - PADDING)
        )
        self.assistant_scroll.setAutoresizingMask_(
            NSViewWidthSizable | NSViewHeightSizable)
        self.assistant_scroll.setHasVerticalScroller_(True)
        self.assistant_scroll.setDrawsBackground_(False)
        self.assistant_doc = _FlippedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, col_w, 10)
        )
        self.assistant_scroll.setDocumentView_(self.assistant_doc)
        wrap.addSubview_(self.assistant_scroll)

    # -- assistant tab actions --

    def sendClicked_(self, sender):
        text = str(self.assistant_input.stringValue()).strip()
        if text and self.on_assistant_send is not None:
            self.assistant_input.setStringValue_("")
            self.on_assistant_send(text)

    def refreshClicked_(self, sender):
        if self.on_assistant_scan is not None:
            self.on_assistant_scan()  # poke the proactive scan ("check now")
        self.refreshAssistant()
        self.assistantToast_(t("assistant.toast_refreshed"))

    def assistantShowRouting_(self, text):
        """Transient echo row pinned above the list while the LLM router runs;
        cleared by the controller's _dispatch before it refreshes the tab."""
        doc = self.assistant_doc
        if doc is None:
            return
        self.assistantClearRouting()
        width = self.assistant_scroll.contentSize().width
        # opaque card (not a translucent overlay) so the status line never bleeds
        # through behind it; sits pinned at the very top while the router runs.
        box, inner = _card_box(4, width - 8, 38)
        from AppKit import NSLineBreakByTruncatingTail
        lbl = NSTextField.labelWithString_(
            f"⏳ {t('assistant.routing')}  {str(text)[:60]}")
        lbl.setFont_(NSFont.systemFontOfSize_(12.0))
        lbl.setTextColor_(NSColor.secondaryLabelColor())
        lbl.setLineBreakMode_(NSLineBreakByTruncatingTail)
        lbl.setFrame_(NSMakeRect(12, 11, width - 8 - 24, 18))
        inner.addSubview_(lbl)
        doc.addSubview_(box)
        self._routing_box = box

    def assistantClearRouting(self):
        if self._routing_box is not None:
            self._routing_box.removeFromSuperview()
            self._routing_box = None

    def assistantToast_(self, text):
        """Brief confirmation row after a card action (승인/완료/삭제 …) so the
        acted-on card doesn't silently vanish. The actual draw is deferred one
        runloop tick so it lands AFTER the action's queued refresh (which would
        otherwise wipe it immediately)."""
        from AppKit import NSObject as _NSObject
        self._pending_toast = str(text)
        _NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "assistantDrawToast", None)
        self.performSelector_withObject_afterDelay_(
            "assistantDrawToast", None, 0.05)

    def assistantDrawToast(self):
        doc = self.assistant_doc
        if doc is None or self._pending_toast is None:
            return
        from AppKit import NSLineBreakByTruncatingTail, NSObject as _NSObject
        if self._toast_box is not None:
            self._toast_box.removeFromSuperview()
        width = self.assistant_scroll.contentSize().width
        box, inner = _card_box(4, width - 8, 34)
        lbl = NSTextField.labelWithString_("✓ " + self._pending_toast)
        lbl.setFont_(NSFont.systemFontOfSize_(12.0))
        lbl.setTextColor_(NSColor.secondaryLabelColor())
        lbl.setLineBreakMode_(NSLineBreakByTruncatingTail)
        lbl.setFrame_(NSMakeRect(12, 9, width - 8 - 24, 18))
        inner.addSubview_(lbl)
        doc.addSubview_(box)
        self._toast_box = box
        self._pending_toast = None
        _NSObject.cancelPreviousPerformRequestsWithTarget_selector_object_(
            self, "assistantClearToast", None)
        self.performSelector_withObject_afterDelay_(
            "assistantClearToast", None, 2.0)

    def assistantClearToast(self):
        if self._toast_box is not None:
            self._toast_box.removeFromSuperview()
            self._toast_box = None

    def assistantSetThreadBusy_(self, tid):
        """Mark a thread as actively being worked on (이어서 streaming) so its
        card shows '작업 중'; only one at a time (a new answer preempts)."""
        import time
        self._busy_thread = str(tid) if tid else None
        self._busy_ts = time.monotonic()
        self.refreshAssistantIfVisible()

    def assistantClearThreadBusy(self):
        if self._busy_thread is not None:
            self._busy_thread = None
            self._busy_ts = None
            self.refreshAssistantIfVisible()

    def approveProposal_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._inbox) and self.on_assistant_approve is not None:
            self.on_assistant_approve(self._inbox[idx].get("id"))
            self.assistantToast_(t("assistant.toast_approved"))

    def skipProposal_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._inbox) and self.on_assistant_skip is not None:
            self.on_assistant_skip(self._inbox[idx].get("id"))
            self.assistantToast_(t("assistant.toast_skipped"))

    def snoozeProposal_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._inbox) and self.on_assistant_snooze is not None:
            self.on_assistant_snooze(self._inbox[idx].get("id"))
            self.assistantToast_(t("assistant.toast_snoozed"))

    def resumeThread_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._threads) and self.on_assistant_resume is not None:
            self.on_assistant_resume(self._threads[idx].get("id"))

    def completeThread_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._threads) and self.on_assistant_complete is not None:
            self.on_assistant_complete(self._threads[idx].get("id"))
            self.assistantToast_(t("assistant.toast_completed"))

    def deleteThread_(self, sender):
        idx = int(sender.tag())
        if not (0 <= idx < len(self._threads)
                and self.on_assistant_delete_thread is not None):
            return
        tid = self._threads[idx].get("id")
        # destructive + no undo → confirm first
        alert = NSAlert.alloc().init()
        alert.setMessageText_(t("assistant.delete_confirm_title"))
        alert.setInformativeText_(t("assistant.delete_confirm_msg"))
        alert.addButtonWithTitle_(t("assistant.delete"))  # first = default
        alert.addButtonWithTitle_(t("assistant.cancel"))
        if alert.runModal() == NSAlertFirstButtonReturn:
            self.on_assistant_delete_thread(tid)
            self.assistantToast_(t("assistant.toast_deleted"))

    def refreshAssistant(self):
        """Re-render the 비서 tab: work threads (M14, "어디까지 했더라") + the
        read-only kanban board (M13). Safe when stores are unset — empty state."""
        threads = []
        if self.assistant_threads is not None:
            try:
                threads = self.assistant_threads.for_display()
            except Exception as exc:
                print(f"assistant tab: thread read error {exc!r}", flush=True)
        tasks = []
        if self.assistant_bridge is not None:
            try:
                tasks = self.assistant_bridge.board_tasks()
            except Exception as exc:  # a read must never break the window
                print(f"assistant tab: board read error {exc!r}", flush=True)
        inbox = []
        if self.assistant_proposals is not None:
            try:
                inbox = self.assistant_proposals.pending()
            except Exception as exc:
                print(f"assistant tab: inbox read error {exc!r}", flush=True)
        self._inbox = inbox
        self._threads = threads  # index == button tag for the card actions
        status = {}
        if self.assistant_bridge is not None:
            try:
                status = self.assistant_bridge.status()
            except Exception as exc:
                print(f"assistant tab: status error {exc!r}", flush=True)
        doc = self.assistant_doc
        if doc is None:
            return
        self._routing_box = None  # was removed by the rebuild below
        self._toast_box = None
        # watchdog: a gen-gated completion callback can be dropped if the answer
        # is preempted / the panel is dismissed; never let "작업 중" stick forever.
        if self._busy_thread is not None and self._busy_ts is not None:
            import time
            # > a long Hermes agent run (its docstring says ~10–60s; allow slack)
            if time.monotonic() - self._busy_ts > 300:
                self._busy_thread = None
                self._busy_ts = None
        for sub in list(doc.subviews()):
            sub.removeFromSuperview()
        width = self.assistant_scroll.contentSize().width
        connected = bool(status.get("connected"))  # external agent (Hermes)
        gap = 10.0
        # cards are drawn with content-derived heights and we accumulate y, so
        # the doc height is exact (no hardcoded per-card constants to desync).
        y = 6.0
        if connected:
            gw = t("assistant.gw_on") if status.get("gateway") == "running" \
                else t("assistant.gw_off")
            line = (f"{t('assistant.hermes_on')} · {gw} · "
                    f"{t('assistant.tasks_title')} {status.get('board_count', 0)}")
        else:
            line = t("assistant.local_only")
        y = _assistant_status(doc, y, width, line, connected)
        # help line is onboarding copy — only when the whole tab is empty
        if not inbox and not threads:
            y = _assistant_empty(doc, y, width, t("assistant.help_line"))
        y += 6
        y = _assistant_section(doc, y, width, t("assistant.section_proposals"),
                               len(inbox))
        if inbox:
            for i in range(len(inbox)):
                y += self._addProposalCardTo_y_width_index_(doc, y, width, i) + gap
        else:
            y = _assistant_empty(doc, y, width, t("assistant.inbox_empty"))
        y += 8
        y = _assistant_section(doc, y, width, t("assistant.threads_title"),
                               len(threads))
        # the passive-memory promise is always shown here (it's the trust line a
        # new user most needs precisely when they have no threads yet)
        y = _assistant_empty(doc, y, width, t("assistant.passive_hint"))
        if threads:
            for i in range(len(threads)):
                y += self._addThreadCardTo_y_width_index_(doc, y, width, i) + gap
        else:
            y = _assistant_empty(doc, y, width, t("assistant.no_threads"))
        if connected:  # external board section only when an agent is connected
            y += 8
            y = _assistant_section(doc, y, width, t("assistant.section_kanban"),
                                   len(tasks))
            if tasks:
                for task in tasks:
                    y += self._addKanbanCardTo_y_width_task_(doc, y, width, task) \
                        + gap
            else:
                y = _assistant_empty(doc, y, width, t("assistant.empty"))
        doc.setFrameSize_(NSMakeSize(width, y + 16))

    def refreshAssistantIfVisible(self):
        """Called from AssistantController on a change — only redraw when the
        user is actually looking at the 비서 tab."""
        if (self.window is not None and self.window.isVisible()
                and self.tab_view is not None
                and str(self.tab_view.selectedTabViewItem().identifier())
                == "assistant"):
            self.refreshAssistant()

    def _addKanbanCardTo_y_width_task_(self, doc, y, width, task):
        """Read-only Hermes board card (never writes the DB); returns height."""
        from datetime import datetime

        from AppKit import NSLineBreakByTruncatingTail, NSTextAlignmentRight

        body = str(task.get("body") or "").replace("\n", " ").strip()
        pad = 14.0
        card_h = 80.0 if body else 60.0
        card_w = width - 8
        box, inner = _card_box(y, card_w, card_h)

        title_s = str(task.get("title") or "—")
        title = NSTextField.labelWithString_(title_s)
        title.setFont_(NSFont.boldSystemFontOfSize_(15.0))
        title.setLineBreakMode_(NSLineBreakByTruncatingTail)
        title.setToolTip_(title_s)
        title.setFrame_(NSMakeRect(pad, card_h - 31, card_w - 2 * pad - 104, 20))
        inner.addSubview_(title)

        status = str(task.get("status") or "")
        if status:
            st = NSTextField.labelWithString_(status)
            st.setFont_(NSFont.systemFontOfSize_(11.0))
            st.setAlignment_(NSTextAlignmentRight)
            st.setTextColor_(NSColor.secondaryLabelColor())
            st.setFrame_(NSMakeRect(card_w - pad - 100, card_h - 29, 100, 16))
            inner.addSubview_(st)

        if body:
            sn = NSTextField.labelWithString_(body)
            sn.setFont_(NSFont.systemFontOfSize_(12.0))
            sn.setTextColor_(NSColor.secondaryLabelColor())
            sn.setLineBreakMode_(NSLineBreakByTruncatingTail)
            sn.setToolTip_(body)
            sn.setFrame_(NSMakeRect(pad, card_h - 52, card_w - 2 * pad, 17))
            inner.addSubview_(sn)

        # footer meta — the section header already says "(읽기 전용)", so no
        # per-card read-only tag here (it was redundant).
        bits = []
        for field in ("assignee", "tenant"):
            if task.get(field):
                bits.append(str(task[field]))
        ts = task.get("created_at")
        if ts:
            try:
                v = float(ts)
                if v > 1e12:  # tolerate epoch-ms
                    v /= 1000.0
                bits.append(datetime.fromtimestamp(v).strftime("%m-%d %H:%M"))
            except (ValueError, OSError, OverflowError):
                pass
        if bits:
            ft = NSTextField.labelWithString_(" · ".join(bits))
            ft.setFont_(NSFont.systemFontOfSize_(11.0))
            ft.setTextColor_(NSColor.tertiaryLabelColor())
            ft.setLineBreakMode_(NSLineBreakByTruncatingTail)
            ft.setFrame_(NSMakeRect(pad, 9, card_w - 2 * pad, 15))
            inner.addSubview_(ft)

        doc.addSubview_(box)
        return card_h

    def _addThreadCardTo_y_width_index_(self, doc, y, width, index):
        """Render one work-thread card sized to its content; returns its height."""
        from AppKit import NSLineBreakByTruncatingTail, NSTextAlignmentRight

        thread = self._threads[index]
        pad, line_h, btn_h = 14.0, 22.0, 30.0
        where = str(thread.get("where_was_i") or "").replace("\n", " ").strip()
        nxt = str(thread.get("next_action") or "").replace("\n", " ").strip()
        last = str(thread.get("last_result") or "").replace("\n", " ").strip()
        n_lines = (1 if where else 0) + (1 if nxt else 0) + (1 if last else 0)
        card_h = 14 + 22 + n_lines * line_h + 12 + btn_h + 12
        card_w = width - 8
        box, inner = _card_box(y, card_w, card_h)

        # colored status dot + title
        status = str(thread.get("status") or "active")
        label_key, dot_rgb = _STATUS_META.get(
            status, ("assistant.status_active", _C_GRAY))
        dot = NSBox.alloc().initWithFrame_(NSMakeRect(pad, card_h - 25, 9, 9))
        dot.setBoxType_(NSBoxCustom)
        dot.setTitlePosition_(0)
        dot.setBorderWidth_(0.0)
        dot.setCornerRadius_(4.5)
        dot.setContentViewMargins_(NSMakeSize(0, 0))
        dr, dg, db = dot_rgb
        dot.setFillColor_(NSColor.colorWithRed_green_blue_alpha_(dr, dg, db, 1.0))
        inner.addSubview_(dot)

        title_s = str(thread.get("title") or "—")
        glyph = _SOURCE_GLYPH.get(str(thread.get("source") or ""), "")
        title = NSTextField.labelWithString_(
            (glyph + " " + title_s) if glyph else title_s)
        title.setFont_(NSFont.boldSystemFontOfSize_(15.0))
        title.setLineBreakMode_(NSLineBreakByTruncatingTail)
        title.setToolTip_(title_s)
        title.setFrame_(NSMakeRect(pad + 16, card_h - 31, card_w - 2 * pad - 150, 20))
        inner.addSubview_(title)

        # corner status stays SHORT (status/⏳ + relative time); the substance of
        # what was done lives in the full-width 📍 line below (where_was_i, which
        # the completion hook updates), so it never gets crammed/clipped here.
        try:
            hrs = self.assistant_threads.idle_hours(thread)
        except Exception:
            hrs = None
        busy = (self._busy_thread is not None
                and str(thread.get("id")) == self._busy_thread)
        if busy:
            prog = "⏳ " + t("assistant.working")
        else:
            prog = t(label_key)
            when = _rel_time(hrs) if hrs is not None else ""
            if when:
                prog = f"{prog} · {when}"
        pl = NSTextField.labelWithString_(prog)
        pl.setFont_(NSFont.systemFontOfSize_(11.0))
        pl.setAlignment_(NSTextAlignmentRight)
        pl.setTextColor_(NSColor.tertiaryLabelColor())
        pl.setLineBreakMode_(NSLineBreakByTruncatingTail)
        pl.setFrame_(NSMakeRect(card_w - pad - 150, card_h - 29, 150, 16))
        inner.addSubview_(pl)

        ly = card_h - 31 - line_h
        if where:
            w = NSTextField.labelWithString_("📍 " + where)
            w.setFont_(NSFont.systemFontOfSize_(12.0))
            w.setTextColor_(NSColor.secondaryLabelColor())
            w.setLineBreakMode_(NSLineBreakByTruncatingTail)
            w.setToolTip_(where)
            w.setFrame_(NSMakeRect(pad, ly, card_w - 2 * pad, 17))
            inner.addSubview_(w)
            ly -= line_h

        if nxt:
            n = NSTextField.labelWithString_("→ " + nxt)
            n.setFont_(NSFont.systemFontOfSize_(12.0))
            n.setTextColor_(NSColor.labelColor())
            n.setLineBreakMode_(NSLineBreakByTruncatingTail)
            n.setToolTip_(nxt)
            n.setFrame_(NSMakeRect(pad, ly, card_w - 2 * pad, 17))
            inner.addSubview_(n)
            ly -= line_h

        if last:  # what the assistant produced last time you hit 이어서
            lr = NSTextField.labelWithString_("✅ " + last)
            lr.setFont_(NSFont.systemFontOfSize_(12.0))
            lr.setTextColor_(NSColor.secondaryLabelColor())
            lr.setLineBreakMode_(NSLineBreakByTruncatingTail)
            lr.setToolTip_(last)
            lr.setFrame_(NSMakeRect(pad, ly, card_w - 2 * pad, 17))
            inner.addSubview_(lr)

        # 이어서 = filled accent · 완료 / 삭제 = subtle
        inner.addSubview_(_accent_button(
            t("assistant.resume"), self, "resumeThread:", index,
            NSMakeRect(pad, 12, 84, btn_h), _ACCENT_BLUE))
        inner.addSubview_(_subtle_button(
            t("assistant.done"), self, "completeThread:", index,
            NSMakeRect(pad + 92, 12, 76, btn_h)))
        inner.addSubview_(_subtle_button(
            t("assistant.delete"), self, "deleteThread:", index,
            NSMakeRect(pad + 176, 12, 76, btn_h)))

        doc.addSubview_(box)
        return card_h

    def _addProposalCardTo_y_width_index_(self, doc, y, width, index):
        """Render one proposal card sized to its content; returns its height."""
        from AppKit import NSLineBreakByTruncatingTail

        prop = self._inbox[index]
        pad, line_h, btn_h = 14.0, 22.0, 30.0
        kind = str(prop.get("kind") or "")
        rat = str(prop.get("rationale") or "").replace("\n", " ").strip()
        # body lines: effect (always — generic fallback) + rationale (if any)
        n_lines = 1 + (1 if rat else 0)
        card_h = 14 + 22 + n_lines * line_h + 12 + btn_h + 12
        card_w = width - 8
        box, inner = _card_box(y, card_w, card_h)

        # risk chip — colored, human-readable (mirrors the floating panel badge)
        klass = str(prop.get("risk") or risk.NEVER_AUTO)
        r, g, b = _RISK_RGB.get(klass, _RISK_RGB[risk.NEVER_AUTO])
        chip_w = 104.0
        chip = NSBox.alloc().initWithFrame_(
            NSMakeRect(card_w - pad - chip_w, card_h - 32, chip_w, 20))
        chip.setBoxType_(NSBoxCustom)
        chip.setTitlePosition_(0)
        chip.setBorderWidth_(0.0)
        chip.setCornerRadius_(10.0)
        chip.setContentViewMargins_(NSMakeSize(0, 0))
        chip.setFillColor_(NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0))
        cl = NSTextField.labelWithString_(t(_RISK_LABEL.get(klass,
                                                            "assistant.risk_never")))
        cl.setFont_(NSFont.boldSystemFontOfSize_(10.0))
        cl.setTextColor_(NSColor.whiteColor())
        cl.setAlignment_(2)  # NSTextAlignmentCenter
        cl.setLineBreakMode_(NSLineBreakByTruncatingTail)
        cl.setFrame_(NSMakeRect(2, 3, chip_w - 4, 14))
        chip.contentView().addSubview_(cl)
        inner.addSubview_(chip)

        title_s = str(prop.get("title") or "—")
        title = NSTextField.labelWithString_(title_s)
        title.setFont_(NSFont.boldSystemFontOfSize_(15.0))
        title.setLineBreakMode_(NSLineBreakByTruncatingTail)
        title.setToolTip_(title_s)
        title.setFrame_(NSMakeRect(pad, card_h - 31, card_w - 2 * pad - chip_w - 8, 20))
        inner.addSubview_(title)

        ly = card_h - 31 - line_h
        # deterministic "what happens if I approve" line (kind-based, no LLM);
        # generic fallback guarantees no approve button is ever unlabeled.
        eff_key = ("assistant.effect_" + kind) if kind in _EFFECT_KINDS \
            else "assistant.effect_generic"
        eff_s = t(eff_key)
        ef = NSTextField.labelWithString_(eff_s)
        ef.setFont_(NSFont.systemFontOfSize_(12.0))
        # semantic color (adapts to light/dark); the risk *color* lives on the
        # chip, so the effect text stays readable on the near-white card.
        ef.setTextColor_(NSColor.secondaryLabelColor())
        ef.setLineBreakMode_(NSLineBreakByTruncatingTail)
        ef.setToolTip_(eff_s)
        ef.setFrame_(NSMakeRect(pad, ly, card_w - 2 * pad, 17))
        inner.addSubview_(ef)
        ly -= line_h

        if rat:
            rr = NSTextField.labelWithString_(rat)
            rr.setFont_(NSFont.systemFontOfSize_(12.0))
            rr.setTextColor_(NSColor.secondaryLabelColor())
            rr.setLineBreakMode_(NSLineBreakByTruncatingTail)
            rr.setToolTip_(rat)
            rr.setFrame_(NSMakeRect(pad, ly, card_w - 2 * pad, 17))
            inner.addSubview_(rr)

        # 승인 = filled accent (red when irreversible) · 나중에 / 건너뛰기 = subtle
        approve_rgb = _RISK_RGB[risk.NEVER_AUTO] if klass == risk.NEVER_AUTO \
            else _ACCENT_BLUE
        inner.addSubview_(_accent_button(
            t("assistant.approve"), self, "approveProposal:", index,
            NSMakeRect(pad, 12, 104, btn_h), approve_rgb))
        snooze_b = _subtle_button(
            t("assistant.snooze"), self, "snoozeProposal:", index,
            NSMakeRect(pad + 112, 12, 96, btn_h))
        snooze_b.setToolTip_(t("assistant.snooze_tip"))
        inner.addSubview_(snooze_b)
        skip_b = _subtle_button(
            t("assistant.skip"), self, "skipProposal:", index,
            NSMakeRect(pad + 216, 12, 96, btn_h))
        skip_b.setToolTip_(t("assistant.skip_tip"))
        inner.addSubview_(skip_b)

        doc.addSubview_(box)
        return card_h

    # -- history sessions ---------------------------------------------------------

    def refreshHistory(self):
        self._all = _build_sessions(self.history.load())
        self.enabled_switch.setState_(
            1 if self.config.get("history_enabled") else 0
        )
        self.save_images_switch.setState_(
            1 if self.config.get("history_save_images") else 0
        )
        self.save_text_switch.setState_(
            1 if self.config.get("history_save_text") else 0
        )
        self._applySaveToggleEnabled()
        self.floating_switch.setState_(
            1 if self.config.get("history_window_floating") else 0
        )
        self.applyFilter()

    def _applySaveToggleEnabled(self):
        # sub-toggles are meaningless while the master switch is off
        master = bool(self.config.get("history_enabled"))
        self.save_images_switch.setEnabled_(master)
        self.save_text_switch.setEnabled_(master)

    def _session_matches(self, session, query):
        for record in session["records"]:
            if (query in str(record.get("input", "")).lower()
                    or query in str(record.get("response", "")).lower()):
                return True
        return False

    def applyFilter(self):
        query = str(self.search_field.stringValue()).strip().lower()
        if query:
            self._filtered = [
                s for s in self._all if self._session_matches(s, query)
            ]
        else:
            self._filtered = list(self._all)
        self.table.reloadData()
        # auto-select the newest session so the chat pane is never empty
        if self._filtered:
            self.table.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(0), False
            )
        else:
            self.table.deselectAll_(None)
            self._renderChat_(None)
        print(
            f"history filter q={query!r} -> {len(self._filtered)}/{len(self._all)}",
            flush=True,
        )

    def _historyAppended(self):
        # HistoryStore.append runs on the main thread (_commitSession)
        if self.window is not None and self.window.isVisible():
            self.refreshHistory()

    def searchChanged_(self, sender):
        self.applyFilter()

    # session list datasource/delegate — rounded card cells (Codex-style)

    def numberOfRowsInTableView_(self, table):
        return len(self._filtered)

    def tableView_viewForTableColumn_row_(self, table, column, row):
        session = self._filtered[row]
        records = session["records"]
        first = records[0]
        mode = _mode_label(first.get("mode"))
        title_text = (
            " ".join(str(first.get("input", "")).split())[:44]
            or t("history.empty_question")
        )
        sub_text = (f"{_short_ts(first)} · {mode} · "
                    f"{t('history.turns').format(n=len(records))}")
        w = float(column.width()) if column is not None else SESSIONS_WIDTH - 24
        container = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, w, 64))
        card = NSBox.alloc().initWithFrame_(NSMakeRect(2, 3, w - 4, 58))
        card.setBoxType_(NSBoxCustom)
        card.setTitlePosition_(0)
        card.setBorderWidth_(0.0)
        card.setCornerRadius_(12.0)
        card.setContentViewMargins_(NSMakeSize(0, 0))
        if row == self.table.selectedRow():
            card.setFillColor_(
                NSColor.controlAccentColor().colorWithAlphaComponent_(0.22)
            )
        else:
            card.setFillColor_(
                NSColor.textBackgroundColor().colorWithAlphaComponent_(0.55)
            )
        title = NSTextField.labelWithString_(title_text)
        title.setFont_(NSFont.systemFontOfSize_weight_(FONT_UI,
                                                       NSFontWeightMedium))
        title.setLineBreakMode_(4)  # truncate tail
        title.setFrame_(NSMakeRect(12, 31, w - 56, 18))
        card.contentView().addSubview_(title)
        sub = NSTextField.labelWithString_(sub_text)
        sub.setFont_(NSFont.systemFontOfSize_(FONT_SMALL))
        sub.setTextColor_(NSColor.secondaryLabelColor())
        sub.setFrame_(NSMakeRect(12, 9, w - 56, 16))
        card.contentView().addSubview_(sub)
        # per-card delete (M11) — immediate, no confirmation; tag carries the
        # FILTERED row index (cells are rebuilt on every reload, never stale)
        delete = NSButton.alloc().initWithFrame_(NSMakeRect(w - 38, 17, 24, 24))
        icon = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            "xmark.circle.fill", "delete session"
        )
        delete.setImage_(icon)
        delete.setBordered_(False)
        delete.setButtonType_(0)  # momentary light
        delete.setContentTintColor_(NSColor.tertiaryLabelColor())
        delete.setTag_(row)
        delete.setTarget_(self)
        delete.setAction_("deleteSession:")
        card.contentView().addSubview_(delete)
        container.addSubview_(card)
        return container

    def deleteSession_(self, sender):
        row = int(sender.tag())
        if not 0 <= row < len(self._filtered):
            return
        session = self._filtered[row]
        self.history.delete_records(session["records"])
        self._last_selected_row = -1  # stale index after the reload
        self.refreshHistory()
        print(
            f"history: session deleted row={row} "
            f"records={len(session['records'])}",
            flush=True,
        )

    def _reloadSessionRows_(self, rows):
        valid = {r for r in rows if 0 <= r < len(self._filtered)}
        if not valid:
            return
        from Foundation import NSMutableIndexSet
        index_set = NSMutableIndexSet.indexSet()
        for r in valid:
            index_set.addIndex_(r)
        self.table.reloadDataForRowIndexes_columnIndexes_(
            index_set, NSIndexSet.indexSetWithIndex_(0)
        )

    def tableViewSelectionDidChange_(self, notification):
        # repaint the previously/newly selected cards (selection is card fill)
        current = self.table.selectedRow()
        previous = getattr(self, "_last_selected_row", -1)
        self._last_selected_row = current
        self._reloadSessionRows_([previous, current])
        self._renderChat_(self._selectedSession())

    def _selectedSession(self):
        row = self.table.selectedRow()
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    # -- chat transcript rendering -------------------------------------------------

    def _renderChat_(self, session):
        doc = self.chat_doc
        for sub in list(doc.subviews()):
            sub.removeFromSuperview()
        doc_w = self.chat_scroll.contentSize().width
        y = 4.0
        if session is None:
            label = NSTextField.labelWithString_(
                t("history.empty") if not self._filtered
                else t("history.select_session")
            )
            label.setTextColor_(NSColor.secondaryLabelColor())
            label.setFrame_(NSMakeRect(8, y, doc_w - 16, 20))
            doc.addSubview_(label)
            y += 28
        else:
            cap_font = NSFont.systemFontOfSize_(FONT_SMALL)
            max_text_w = max(120.0, doc_w * 0.72) - 2 * BUBBLE_PAD
            for record in session["records"]:
                mode = _mode_label(record.get("mode"))
                caption = NSTextField.labelWithString_(
                    f"{_short_ts(record)} · {mode} · "
                    f"{record.get('model', '')}"
                )
                caption.setFont_(cap_font)
                caption.setTextColor_(NSColor.tertiaryLabelColor())
                caption.setAlignment_(2)  # NSTextAlignmentCenter
                caption.setFrame_(NSMakeRect(0, y, doc_w, CAPTION_H))
                doc.addSubview_(caption)
                y += CAPTION_H + 4
                # user question — right-aligned accent bubble
                y = self._addBubbleTo_y_text_width_right_(
                    doc, y, str(record.get("input", "")), max_text_w, True
                ) + BUBBLE_GAP
                # AI answer — left-aligned neutral bubble
                y = self._addBubbleTo_y_text_width_right_(
                    doc, y, str(record.get("response", "")), max_text_w, False
                ) + BUBBLE_GAP
        doc.setFrame_(NSMakeRect(0, 0, doc_w, max(y, 10.0)))
        doc.scrollPoint_((0, 0))  # flipped: (0,0) is the top
        has = session is not None
        self.copy_button.setEnabled_(has)
        if has:
            first = session["records"][0]
            if first.get("mode") == "region":
                # re-runnable only when its capture PNG still exists
                self.reask_button.setEnabled_(
                    self.history.image_path(first) is not None
                )
            else:
                self.reask_button.setEnabled_(True)
        else:
            self.reask_button.setEnabled_(False)
        print(
            f"chat rendered turns={len(session['records']) if session else 0} "
            f"height={y:.0f}",
            flush=True,
        )

    def _addBubbleTo_y_text_width_right_(self, doc, y, text, max_text_w,
                                         is_user):
        doc_w = doc.frame().size.width or self.chat_scroll.contentSize().width
        font = NSFont.systemFontOfSize_(FONT_BODY)
        text = text if text.strip() else " "
        # explicit attributed text — wrapping labels can drop a plain
        # setTextColor_, which made the white-on-accent text invisible
        attr = NSAttributedString.alloc().initWithString_attributes_(
            text, {
                NSFontAttributeName: font,
                NSForegroundColorAttributeName:
                    NSColor.whiteColor() if is_user else NSColor.labelColor(),
            }
        )
        label = NSTextField.wrappingLabelWithString_(text)
        label.setAttributedStringValue_(attr)
        label.setSelectable_(True)
        # measure with the field's own cell — boundingRect under-counts the
        # per-line leading on long answers, which clipped the bubble tails
        size = label.cell().cellSizeForBounds_(
            NSMakeRect(0, 0, max_text_w, 1.0e7)
        )
        tw = min(max_text_w, math.ceil(size.width))
        th = math.ceil(size.height)
        bw = tw + 2 * BUBBLE_PAD  # bubble hugs its text like a chat app
        bh = th + 2 * BUBBLE_PAD
        bx = (doc_w - bw - 2) if is_user else 2
        bubble = NSBox.alloc().initWithFrame_(NSMakeRect(bx, y, bw, bh))
        bubble.setBoxType_(NSBoxCustom)
        bubble.setTitlePosition_(0)  # NSNoTitle
        bubble.setBorderWidth_(0.0)
        bubble.setCornerRadius_(BUBBLE_RADIUS)
        # default contentViewMargins (5,5) silently clipped the label
        bubble.setContentViewMargins_(NSMakeSize(0, 0))
        # NSBox re-resolves semantic fills on appearance change (vs CALayer)
        if is_user:
            bubble.setFillColor_(NSColor.controlAccentColor())
        else:
            bubble.setFillColor_(
                NSColor.textBackgroundColor().colorWithAlphaComponent_(0.85)
            )
        label.setFrame_(NSMakeRect(BUBBLE_PAD, BUBBLE_PAD, tw, th))
        bubble.contentView().addSubview_(label)
        doc.addSubview_(bubble)
        return y + bh

    # -- actions -------------------------------------------------------------------

    def copyResponse_(self, sender):
        session = self._selectedSession()
        if session is None:
            return
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(
            _session_transcript(session), NSPasteboardTypeString
        )
        print("history: response copied", flush=True)

    def reask_(self, sender):
        session = self._selectedSession()
        if session is None:
            return
        first = session["records"][0]
        text = str(first.get("input", ""))
        if first.get("mode") == "region":
            path = self.history.image_path(first)
            if path is None or self.on_reask_image is None:
                return
            self.on_reask_image(text, path.read_bytes())
        elif self.on_reask is not None:
            self.on_reask(text)

    def toggleEnabled_(self, sender):
        enabled = bool(sender.state())
        self.config.set("history_enabled", enabled)
        self.config.save()
        self._applySaveToggleEnabled()
        print(f"history_enabled={enabled}", flush=True)

    def toggleSaveImages_(self, sender):
        self.config.set("history_save_images", bool(sender.state()))
        self.config.save()
        print(f"history_save_images={bool(sender.state())}", flush=True)

    def toggleSaveText_(self, sender):
        self.config.set("history_save_text", bool(sender.state()))
        self.config.save()
        print(f"history_save_text={bool(sender.state())}", flush=True)

    def toggleFloating_(self, sender):
        self.config.set("history_window_floating", bool(sender.state()))
        self.config.save()
        self._applyFloating()

    def _applyFloating(self):
        floating = bool(self.config.get("history_window_floating"))
        self.window.setLevel_(
            NSFloatingWindowLevel if floating else NSNormalWindowLevel
        )
        print(f"history_window_floating={floating}", flush=True)

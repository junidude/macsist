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
BUBBLE_RADIUS = 14.0
BUBBLE_PAD = 12.0
BUBBLE_GAP = 14.0
CAPTION_H = 18.0
FONT_BODY = 15.0  # 13 × 1.15
FONT_SMALL = 12.0  # captions / session sublines
FONT_UI = 14.0  # buttons, switch labels, session titles
_SEARCH_ITEM_ID = "search"

def _assistant_section(doc, y, width, title):
    """Module-level (NOT a method): NSObject-subclass methods need selector
    arity (project memory pyobjc-selector-arg-naming). Returns the next y."""
    label = NSTextField.labelWithString_(title)
    label.setFont_(NSFont.boldSystemFontOfSize_(13.0))
    label.setTextColor_(NSColor.secondaryLabelColor())
    label.setFrame_(NSMakeRect(8, y + 6, width - 16, 18))
    doc.addSubview_(label)
    return y + 30.0


def _assistant_empty(doc, y, width, text):
    label = NSTextField.labelWithString_(text)
    label.setFont_(NSFont.systemFontOfSize_(12.0))
    label.setTextColor_(NSColor.tertiaryLabelColor())
    label.setFrame_(NSMakeRect(12, y + 2, width - 24, 18))
    doc.addSubview_(label)
    return y + 26.0


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
        self.on_assistant_propose = None     # text -> controller.handlePropose_
        self.on_assistant_new_thread = None  # text -> controller.new_thread
        self.on_assistant_scan = None        # -> controller.handleScan
        self.assistant_scroll = None
        self.assistant_doc = None
        self.assistant_input = None
        self._inbox = []  # pending proposals (index == button tag)
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
        inner_w = cw - 2 * PADDING
        # top toolbar: input + 제안 / 스레드 추가 / 스캔
        bar_y = ch - PADDING - bar_h
        btn_w, btn_gap = 92.0, 8.0
        buttons = (
            (t("assistant.answer_btn"), "answerClicked:"),
            (t("assistant.propose"), "proposeClicked:"),
            (t("assistant.new_thread"), "newThreadClicked:"),
            (t("assistant.scan"), "scanClicked:"),
        )
        field_w = inner_w - len(buttons) * (btn_w + btn_gap)
        box, field = _make_round_field(
            NSMakeRect(PADDING, bar_y + 6, field_w, 32), 14.0)
        field.setPlaceholderString_(t("assistant.input_placeholder"))
        field.setTarget_(self)
        field.setAction_("answerClicked:")  # Return = 답변(즉시 수행)
        self.assistant_input = field
        container.addSubview_(box)
        bx = PADDING + field_w + btn_gap
        for i, (label, action) in enumerate(buttons):
            container.addSubview_(_make_pill(
                label, self, action,
                NSMakeRect(bx + i * (btn_w + btn_gap), bar_y + 7, btn_w, 30)))
        # scroll area below the toolbar
        self.assistant_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(PADDING, PADDING, inner_w, bar_y - PADDING)
        )
        self.assistant_scroll.setHasVerticalScroller_(True)
        self.assistant_scroll.setDrawsBackground_(False)
        self.assistant_doc = _FlippedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, inner_w, 10)
        )
        self.assistant_scroll.setDocumentView_(self.assistant_doc)
        container.addSubview_(self.assistant_scroll)

    # -- assistant tab actions --

    def answerClicked_(self, sender):
        text = str(self.assistant_input.stringValue()).strip()
        if text and self.on_assistant_answer is not None:
            self.on_assistant_answer(text)
            self.assistant_input.setStringValue_("")

    def proposeClicked_(self, sender):
        text = str(self.assistant_input.stringValue()).strip()
        if text and self.on_assistant_propose is not None:
            self.on_assistant_propose(text)
            self.assistant_input.setStringValue_("")

    def newThreadClicked_(self, sender):
        text = str(self.assistant_input.stringValue()).strip()
        if text and self.on_assistant_new_thread is not None:
            self.on_assistant_new_thread(text)
            self.assistant_input.setStringValue_("")

    def scanClicked_(self, sender):
        if self.on_assistant_scan is not None:
            self.on_assistant_scan()

    def approveProposal_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._inbox) and self.on_assistant_approve is not None:
            self.on_assistant_approve(self._inbox[idx].get("id"))

    def skipProposal_(self, sender):
        idx = int(sender.tag())
        if 0 <= idx < len(self._inbox) and self.on_assistant_skip is not None:
            self.on_assistant_skip(self._inbox[idx].get("id"))

    def refreshAssistant(self):
        """Re-render the 비서 tab: work threads (M14, "어디까지 했더라") + the
        read-only kanban board (M13). Safe when stores are unset — empty state."""
        threads = []
        if self.assistant_threads is not None:
            try:
                threads = self.assistant_threads.active()
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
        status = {}
        if self.assistant_bridge is not None:
            try:
                status = self.assistant_bridge.status()
            except Exception as exc:
                print(f"assistant tab: status error {exc!r}", flush=True)
        doc = self.assistant_doc
        if doc is None:
            return
        for sub in list(doc.subviews()):
            sub.removeFromSuperview()
        width = self.assistant_scroll.contentSize().width
        connected = bool(status.get("connected"))  # external agent (Hermes)
        inbox_h, th_h, task_h, gap = 100.0, 88.0, 76.0, 8.0
        total = 56.0  # status line + help line
        total += 30 + (len(inbox) * (inbox_h + gap) if inbox else 26)
        total += 30 + (len(threads) * (th_h + gap) if threads else 26)
        if connected:
            total += 30 + (len(tasks) * (task_h + gap) if tasks else 26)
        doc.setFrameSize_(NSMakeSize(width, total))
        y = 4.0
        if connected:
            gw = t("assistant.gw_on") if status.get("gateway") == "running" \
                else t("assistant.gw_off")
            line = (f"⌁ {t('assistant.hermes_on')} · {gw} · "
                    f"{t('assistant.tasks_title')} {status.get('board_count', 0)}")
        else:
            line = t("assistant.local_only")
        y = _assistant_empty(doc, y, width, line)
        y = _assistant_empty(doc, y, width, t("assistant.help_line"))
        y = _assistant_section(doc, y, width, t("menubar.assistant_inbox"))
        if inbox:
            for i in range(len(inbox)):
                self._addProposalCardTo_y_width_index_(doc, y, width, i)
                y += inbox_h + gap
        else:
            y = _assistant_empty(doc, y, width, t("assistant.inbox_empty"))
        y = _assistant_section(doc, y, width, t("assistant.threads_title"))
        if threads:
            for th in threads:
                self._addThreadCardTo_y_width_thread_(doc, y, width, th)
                y += th_h + gap
        else:
            y = _assistant_empty(doc, y, width, t("assistant.no_threads"))
        if connected:  # external board section only when an agent is connected
            y = _assistant_section(doc, y, width, t("assistant.tasks_title"))
            if tasks:
                for task in tasks:
                    self._addKanbanCardTo_y_width_task_(doc, y, width, task)
                    y += task_h + gap
            else:
                y = _assistant_empty(doc, y, width, t("assistant.empty"))

    def refreshAssistantIfVisible(self):
        """Called from AssistantController on a change — only redraw when the
        user is actually looking at the 비서 tab."""
        if (self.window is not None and self.window.isVisible()
                and self.tab_view is not None
                and str(self.tab_view.selectedTabViewItem().identifier())
                == "assistant"):
            self.refreshAssistant()

    def _addKanbanCardTo_y_width_task_(self, doc, y, width, task):
        from datetime import datetime

        from AppKit import NSLineBreakByTruncatingTail, NSTextAlignmentRight

        card_w, card_h, pad = width - 8, 76.0, 12.0
        box = NSBox.alloc().initWithFrame_(NSMakeRect(4, y, card_w, card_h))
        box.setBoxType_(NSBoxCustom)
        box.setTitlePosition_(0)
        box.setBorderWidth_(0.0)
        box.setCornerRadius_(10.0)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        box.setFillColor_(
            NSColor.textBackgroundColor().colorWithAlphaComponent_(0.5)
        )
        inner = box.contentView()

        title = NSTextField.labelWithString_(str(task.get("title") or "—"))
        title.setFont_(NSFont.boldSystemFontOfSize_(14.0))
        title.setLineBreakMode_(NSLineBreakByTruncatingTail)
        title.setFrame_(NSMakeRect(pad, card_h - 28, card_w - 2 * pad - 104, 19))
        inner.addSubview_(title)

        status = str(task.get("status") or "")
        if status:
            st = NSTextField.labelWithString_(status)
            st.setFont_(NSFont.systemFontOfSize_(11.0))
            st.setAlignment_(NSTextAlignmentRight)
            st.setTextColor_(NSColor.secondaryLabelColor())
            st.setFrame_(NSMakeRect(card_w - pad - 100, card_h - 27, 100, 16))
            inner.addSubview_(st)

        body = str(task.get("body") or "").replace("\n", " ").strip()
        if body:
            sn = NSTextField.labelWithString_(body)
            sn.setFont_(NSFont.systemFontOfSize_(12.0))
            sn.setTextColor_(NSColor.secondaryLabelColor())
            sn.setLineBreakMode_(NSLineBreakByTruncatingTail)
            sn.setFrame_(NSMakeRect(pad, card_h - 50, card_w - 2 * pad, 17))
            inner.addSubview_(sn)

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
            ft.setFrame_(NSMakeRect(pad, 8, card_w - 2 * pad, 15))
            inner.addSubview_(ft)

        doc.addSubview_(box)

    def _addThreadCardTo_y_width_thread_(self, doc, y, width, thread):
        from AppKit import NSLineBreakByTruncatingTail, NSTextAlignmentRight

        card_w, card_h, pad = width - 8, 88.0, 12.0
        box = NSBox.alloc().initWithFrame_(NSMakeRect(4, y, card_w, card_h))
        box.setBoxType_(NSBoxCustom)
        box.setTitlePosition_(0)
        box.setBorderWidth_(0.0)
        box.setCornerRadius_(10.0)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        box.setFillColor_(
            NSColor.textBackgroundColor().colorWithAlphaComponent_(0.5)
        )
        inner = box.contentView()

        title = NSTextField.labelWithString_(str(thread.get("title") or "—"))
        title.setFont_(NSFont.boldSystemFontOfSize_(14.0))
        title.setLineBreakMode_(NSLineBreakByTruncatingTail)
        title.setFrame_(NSMakeRect(pad, card_h - 28, card_w - 2 * pad - 90, 19))
        inner.addSubview_(title)

        status = str(thread.get("status") or "")
        if status:
            st = NSTextField.labelWithString_(status)
            st.setFont_(NSFont.systemFontOfSize_(11.0))
            st.setAlignment_(NSTextAlignmentRight)
            st.setTextColor_(NSColor.secondaryLabelColor())
            st.setFrame_(NSMakeRect(card_w - pad - 86, card_h - 27, 86, 16))
            inner.addSubview_(st)

        where = str(thread.get("where_was_i") or "").replace("\n", " ").strip()
        if where:
            w = NSTextField.labelWithString_("📍 " + where)
            w.setFont_(NSFont.systemFontOfSize_(12.0))
            w.setTextColor_(NSColor.secondaryLabelColor())
            w.setLineBreakMode_(NSLineBreakByTruncatingTail)
            w.setFrame_(NSMakeRect(pad, card_h - 50, card_w - 2 * pad, 17))
            inner.addSubview_(w)

        nxt = str(thread.get("next_action") or "").replace("\n", " ").strip()
        if nxt:
            n = NSTextField.labelWithString_("→ " + nxt)
            n.setFont_(NSFont.systemFontOfSize_(12.0))
            n.setLineBreakMode_(NSLineBreakByTruncatingTail)
            n.setFrame_(NSMakeRect(pad, 10, card_w - 2 * pad, 17))
            inner.addSubview_(n)

        doc.addSubview_(box)

    def _addProposalCardTo_y_width_index_(self, doc, y, width, index):
        from AppKit import (
            NSBezelStyleRounded,
            NSLineBreakByTruncatingTail,
            NSTextAlignmentRight,
        )

        prop = self._inbox[index]
        card_w, card_h, pad = width - 8, 100.0, 12.0
        box = NSBox.alloc().initWithFrame_(NSMakeRect(4, y, card_w, card_h))
        box.setBoxType_(NSBoxCustom)
        box.setTitlePosition_(0)
        box.setBorderWidth_(0.0)
        box.setCornerRadius_(10.0)
        box.setContentViewMargins_(NSMakeSize(0, 0))
        box.setFillColor_(
            NSColor.textBackgroundColor().colorWithAlphaComponent_(0.6)
        )
        inner = box.contentView()

        title = NSTextField.labelWithString_(str(prop.get("title") or "—"))
        title.setFont_(NSFont.boldSystemFontOfSize_(14.0))
        title.setLineBreakMode_(NSLineBreakByTruncatingTail)
        title.setFrame_(NSMakeRect(pad, card_h - 28, card_w - 2 * pad - 90, 19))
        inner.addSubview_(title)

        risk = str(prop.get("risk") or "")
        if risk:
            rb = NSTextField.labelWithString_(risk)
            rb.setFont_(NSFont.systemFontOfSize_(10.0))
            rb.setTextColor_(NSColor.tertiaryLabelColor())
            rb.setAlignment_(NSTextAlignmentRight)
            rb.setFrame_(NSMakeRect(card_w - pad - 90, card_h - 26, 90, 14))
            inner.addSubview_(rb)

        rat = str(prop.get("rationale") or "").replace("\n", " ").strip()
        if rat:
            r = NSTextField.labelWithString_(rat)
            r.setFont_(NSFont.systemFontOfSize_(12.0))
            r.setTextColor_(NSColor.secondaryLabelColor())
            r.setLineBreakMode_(NSLineBreakByTruncatingTail)
            r.setFrame_(NSMakeRect(pad, card_h - 50, card_w - 2 * pad, 17))
            inner.addSubview_(r)

        approve = NSButton.alloc().initWithFrame_(NSMakeRect(pad, 12, 96, 28))
        approve.setTitle_(t("assistant.approve"))
        approve.setBezelStyle_(NSBezelStyleRounded)
        approve.setTag_(index)
        approve.setTarget_(self)
        approve.setAction_("approveProposal:")
        inner.addSubview_(approve)

        skip = NSButton.alloc().initWithFrame_(NSMakeRect(pad + 104, 12, 96, 28))
        skip.setTitle_(t("assistant.skip"))
        skip.setBezelStyle_(NSBezelStyleRounded)
        skip.setTag_(index)
        skip.setTarget_(self)
        skip.setAction_("skipProposal:")
        inner.addSubview_(skip)

        doc.addSubview_(box)

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

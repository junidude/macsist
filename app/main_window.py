"""MainWindowController — the History/Settings window (M7).

A regular activating window (the never-steal-focus invariant applies only to
the result panel; the old standalone settings window already activated the
app the same way). Two tabs:

- History: master-detail over history.jsonl — search field + newest-first
  table on top, full Q/A text below with 복사 / 다시 질문 buttons. Chosen over
  inline row expansion deliberately: this bundle-less app cannot be verified
  by screenshots, so the layout must stay fixed-frame simple.
- Settings: the SettingsPaneController controls (M0–M6 logic unchanged),
  built into this window's tab via buildInView_.

Owned by StatusItemController (one instance, setReleasedWhenClosed_(False)).
All methods run on the main thread.
"""

import os

import objc
from AppKit import (
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSButton,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSNormalWindowLevel,
    NSObject,
    NSPasteboard,
    NSPasteboardTypeString,
    NSScrollView,
    NSSearchField,
    NSTableColumn,
    NSTableView,
    NSTabView,
    NSTabViewItem,
    NSTextField,
    NSTextView,
    NSView,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskTitled,
)

from settings_window import SettingsPaneController, pane_min_size

PADDING = 16
ROW_HEIGHT = 24
DETAIL_HEIGHT = 170
CONTENT_WIDTH = 760.0
CONTENT_HEIGHT = 660.0

_MODE_LABELS = {"text": "텍스트", "region": "화면", "followup": "추가질문"}


def _row_title(record):
    ts = str(record.get("ts", ""))[5:16].replace("T", " ")  # "MM-DD HH:MM"
    mode = _MODE_LABELS.get(record.get("mode"), str(record.get("mode")))
    snippet = " ".join(str(record.get("input", "")).split())[:80]
    return f"{ts} · {mode} · {snippet}"


def _detail_text(record):
    return (
        f"{record.get('ts', '')} · "
        f"{_MODE_LABELS.get(record.get('mode'), record.get('mode'))} · "
        f"{record.get('model', '')} · {record.get('detail', '')}\n"
        f"\n질문:\n{record.get('input', '')}\n"
        f"\n────────\n"
        f"\n응답:\n{record.get('response', '')}"
    )


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
        self.search_field = None
        self.table = None
        self.detail_view = None
        self.copy_button = None
        self.reask_button = None
        self.enabled_checkbox = None
        self.save_images_checkbox = None
        self.save_text_checkbox = None
        self.floating_checkbox = None
        self._all = []  # every record, newest first
        self._filtered = []  # rows currently in the table
        history.on_appended = self._historyAppended
        return self

    # -- showing ---------------------------------------------------------------

    def showHistory(self):
        self._show_("history")

    def showSettings(self):
        self._show_("settings")

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
        print("main window closed -> Accessory policy", flush=True)

    def _refreshTab_(self, tab_id):
        if tab_id == "history":
            self.refreshHistory()
        else:
            self.settings.refresh()

    def tabView_didSelectTabViewItem_(self, tab_view, item):
        # user clicked the other tab — same refresh as opening it from the menu
        self._refreshTab_(str(item.identifier()))

    # -- build -------------------------------------------------------------------

    def _buildWindow(self):
        pane_w, pane_h = pane_min_size()
        width = max(CONTENT_WIDTH, pane_w + PADDING * 2)
        height = max(CONTENT_HEIGHT, pane_h + 60)  # 60 ≈ tab chrome
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("Macsist")
        self.window.setReleasedWhenClosed_(False)
        self.window.setDelegate_(self)  # windowWillClose_ → Accessory policy
        self._applyFloating()

        content = self.window.contentView()
        self.tab_view = NSTabView.alloc().initWithFrame_(
            NSMakeRect(0, 0, width, height)
        )
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

        settings_view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        self.settings.buildInView_(settings_view)
        item = NSTabViewItem.alloc().initWithIdentifier_("settings")
        item.setLabel_("Settings")
        item.setView_(settings_view)
        self.tab_view.addTabViewItem_(item)

    def _buildHistoryTab_(self, container):
        size = container.frame().size
        cw, ch = size.width, size.height

        # row 1: search + 항상 위
        top_y = ch - PADDING - ROW_HEIGHT
        self.floating_checkbox = NSButton.checkboxWithTitle_target_action_(
            "항상 위", self, "toggleFloating:"
        )
        self.floating_checkbox.setFrame_(
            NSMakeRect(cw - PADDING - 80, top_y, 80, ROW_HEIGHT)
        )
        container.addSubview_(self.floating_checkbox)
        self.search_field = NSSearchField.alloc().initWithFrame_(
            NSMakeRect(PADDING, top_y, cw - PADDING * 2 - 80 - 8, ROW_HEIGHT)
        )
        self.search_field.setPlaceholderString_("검색 (질문/응답)")
        self.search_field.setTarget_(self)
        self.search_field.setAction_("searchChanged:")
        self.search_field.setSendsSearchStringImmediately_(True)
        container.addSubview_(self.search_field)

        # row 2: master save toggle + per-mode sub-toggles
        toggles_y = top_y - ROW_HEIGHT - 4
        self.enabled_checkbox = NSButton.checkboxWithTitle_target_action_(
            "기록 저장 (전체)", self, "toggleEnabled:"
        )
        self.enabled_checkbox.setFrame_(
            NSMakeRect(PADDING, toggles_y, 140, ROW_HEIGHT)
        )
        container.addSubview_(self.enabled_checkbox)
        self.save_images_checkbox = NSButton.checkboxWithTitle_target_action_(
            "이미지 저장", self, "toggleSaveImages:"
        )
        self.save_images_checkbox.setFrame_(
            NSMakeRect(PADDING + 164, toggles_y, 110, ROW_HEIGHT)
        )
        container.addSubview_(self.save_images_checkbox)
        self.save_text_checkbox = NSButton.checkboxWithTitle_target_action_(
            "텍스트 저장", self, "toggleSaveText:"
        )
        self.save_text_checkbox.setFrame_(
            NSMakeRect(PADDING + 164 + 118, toggles_y, 110, ROW_HEIGHT)
        )
        container.addSubview_(self.save_text_checkbox)

        # bottom: buttons row, then the detail text above it
        self.copy_button = NSButton.buttonWithTitle_target_action_(
            "복사", self, "copyResponse:"
        )
        self.copy_button.setFrame_(NSMakeRect(PADDING, PADDING, 80, ROW_HEIGHT))
        container.addSubview_(self.copy_button)
        self.reask_button = NSButton.buttonWithTitle_target_action_(
            "다시 질문", self, "reask:"
        )
        self.reask_button.setFrame_(
            NSMakeRect(PADDING + 88, PADDING, 100, ROW_HEIGHT)
        )
        container.addSubview_(self.reask_button)

        detail_y = PADDING + ROW_HEIGHT + 8
        detail_scroll = NSTextView.scrollableTextView()
        detail_scroll.setFrame_(
            NSMakeRect(PADDING, detail_y, cw - PADDING * 2, DETAIL_HEIGHT)
        )
        self.detail_view = detail_scroll.documentView()
        self.detail_view.setEditable_(False)
        self.detail_view.setRichText_(False)
        self.detail_view.setFont_(NSFont.systemFontOfSize_(12.0))
        container.addSubview_(detail_scroll)

        # middle: the record table fills the rest
        table_y = detail_y + DETAIL_HEIGHT + 8
        table_h = toggles_y - 8 - table_y
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(PADDING, table_y, cw - PADDING * 2, table_h)
        )
        scroll.setHasVerticalScroller_(True)
        self.table = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, cw - PADDING * 2, table_h)
        )
        column = NSTableColumn.alloc().initWithIdentifier_("qa")
        column.setWidth_(cw - PADDING * 2 - 20)
        column.setTitle_("기록")
        self.table.addTableColumn_(column)
        self.table.setHeaderView_(None)
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setAllowsMultipleSelection_(False)
        scroll.setDocumentView_(self.table)
        container.addSubview_(scroll)

        self._showDetail_(None)

    # -- history list ------------------------------------------------------------

    def refreshHistory(self):
        self._all = self.history.load()
        self.enabled_checkbox.setState_(
            1 if self.config.get("history_enabled") else 0
        )
        self.save_images_checkbox.setState_(
            1 if self.config.get("history_save_images") else 0
        )
        self.save_text_checkbox.setState_(
            1 if self.config.get("history_save_text") else 0
        )
        self._applySaveToggleEnabled()
        self.floating_checkbox.setState_(
            1 if self.config.get("history_window_floating") else 0
        )
        self.applyFilter()

    def _applySaveToggleEnabled(self):
        # sub-toggles are meaningless while the master switch is off
        master = bool(self.config.get("history_enabled"))
        self.save_images_checkbox.setEnabled_(master)
        self.save_text_checkbox.setEnabled_(master)

    def applyFilter(self):
        query = str(self.search_field.stringValue()).strip().lower()
        if query:
            self._filtered = [
                r for r in self._all
                if query in str(r.get("input", "")).lower()
                or query in str(r.get("response", "")).lower()
            ]
        else:
            self._filtered = list(self._all)
        self.table.reloadData()
        self.table.deselectAll_(None)
        self._showDetail_(None)
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

    def numberOfRowsInTableView_(self, table):
        return len(self._filtered)

    def tableView_objectValueForTableColumn_row_(self, table, column, row):
        return _row_title(self._filtered[row])

    def tableViewSelectionDidChange_(self, notification):
        self._showDetail_(self._selectedRecord())

    def _selectedRecord(self):
        row = self.table.selectedRow()
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def _showDetail_(self, record):
        if record is None:
            self.detail_view.setString_(
                "기록이 없습니다." if not self._filtered
                else "행을 선택하면 전체 내용이 표시됩니다."
            )
            self.copy_button.setEnabled_(False)
            self.reask_button.setEnabled_(False)
            return
        self.detail_view.setString_(_detail_text(record))
        self.detail_view.scrollRangeToVisible_((0, 0))
        self.copy_button.setEnabled_(True)
        if record.get("mode") == "region":
            # re-runnable only when its capture PNG was saved and still exists
            self.reask_button.setEnabled_(
                self.history.image_path(record) is not None
            )
        else:
            self.reask_button.setEnabled_(True)

    # -- actions -------------------------------------------------------------------

    def copyResponse_(self, sender):
        record = self._selectedRecord()
        if record is None:
            return
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(
            str(record.get("response", "")), NSPasteboardTypeString
        )
        print("history: response copied", flush=True)

    def reask_(self, sender):
        record = self._selectedRecord()
        if record is None:
            return
        text = str(record.get("input", ""))
        if record.get("mode") == "region":
            path = self.history.image_path(record)
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

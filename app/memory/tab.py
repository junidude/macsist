"""MemoryTabController — the 기억 tab in the main window (M20).

Two panes, mirroring the 기록 tab the user already knows: note cards on the
right, the selected note's text on the left (and the 관심사 프로필 when nothing
is selected). Below it, the three things one wants to do to a memory: rebuild
the profile, forget a note, and open the folder — because the notes are plain
markdown files the user is meant to be able to read and edit themselves.

A separate NSObject on purpose, for the reason `_SidebarController` gives:
MainWindowController is already the datasource/delegate of the history
sessions table, and a shared delegate would make every callback ambiguous.

PyObjC: methods taking arguments need the trailing-underscore arity (a plain
`def foo(self, a)` on an NSObject subclass fails at import) — helpers without
`self` live at module level instead.
"""

import subprocess

import objc
from AppKit import (
    NSBox,
    NSBoxCustom,
    NSColor,
    NSFocusRingTypeNone,
    NSFont,
    NSIndexSet,
    NSMakeRect,
    NSMakeSize,
    NSScrollView,
    NSTableCellView,
    NSTableColumn,
    NSTableView,
    NSTableViewSelectionHighlightStyleNone,
    NSTableViewStyleInset,
    NSSwitch,
    NSTextField,
    NSTextView,
)
from Foundation import NSObject

from i18n import t
from ui_kit import make_pill

PADDING = 16
LIST_WIDTH = 364.0
ROW_H = 72.0
BUTTON_H = 34.0
FONT_BODY = 15.0
FONT_UI = 14.0
FONT_SMALL = 12.0


def _label(text, frame, size=FONT_UI, secondary=False, bold=False):
    field = NSTextField.labelWithString_(str(text))
    field.setFrame_(frame)
    field.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
                   else NSFont.systemFontOfSize_(size))
    if secondary:
        field.setTextColor_(NSColor.secondaryLabelColor())
    return field


def _add_switch(host, target, x, y, title, action):
    """Right-aligned label + NSSwitch. Module level on purpose: an NSObject
    method's trailing underscores ARE its selector arity, so a 5-argument
    helper named `_switchAt_title_action_` raises BadPrototypeError at import
    (project memory pyobjc-selector-arg-naming)."""
    label = _label(title, NSMakeRect(x - 96, y + 5, 92, 18),
                   size=FONT_SMALL, secondary=True)
    label.setAlignment_(2)  # NSTextAlignmentRight
    host.addSubview_(label)
    switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(x, y + 3, 40, 26))
    switch.setTarget_(target)
    switch.setAction_(action)
    host.addSubview_(switch)
    return switch


def _note_detail(note, body):
    """(title, subtitle, body) for the detail pane. The note's own markdown is
    shown as-is: it is the artifact the user can open in any editor, so the UI
    must not present a prettier fiction of it."""
    title = str(note.get("title") or note.get("slug") or "—")
    bits = []
    domains = ", ".join(note.get("domains") or [])
    if domains:
        bits.append(domains)
    bits.append(t("memory.seen_times").format(n=int(note.get("seen") or 1)))
    when = str(note.get("last_ts") or "")[:10]
    if when:
        bits.append(when)
    aliases = ", ".join(note.get("aliases") or [])
    if aliases:
        bits.append(aliases)
    return title, " · ".join(bits), body or str(note.get("summary") or "")


class MemoryTabController(NSObject):
    def initWithConfig_store_(self, config, store):
        self = objc.super(MemoryTabController, self).init()
        if self is None:
            return None
        self.config = config
        self.store = store
        self.on_backfill = None   # set by main_window -> MemoryMonitor
        self.on_profile = None
        self.on_distill = None
        self.table = None
        self.detail = None
        self.header = None
        self.title_label = None
        self.sub_label = None
        self.delete_button = None
        self.enabled_switch = None
        self.local_switch = None
        self._notes = []
        self._filtered = []
        self._query = ""
        return self

    # -- build ---------------------------------------------------------------

    def buildInView_(self, container):
        size = container.frame().size
        cw, ch = size.width, size.height
        list_x = cw - PADDING - LIST_WIDTH
        detail_w = list_x - 8 - PADDING

        row_y = PADDING
        self.profile_button = make_pill(
            t("memory.rebuild_profile"), self, "rebuildProfile:",
            NSMakeRect(PADDING, row_y, 150, BUTTON_H))
        container.addSubview_(self.profile_button)
        self.delete_button = make_pill(
            t("memory.forget"), self, "forgetNote:",
            NSMakeRect(PADDING + 158, row_y, 120, BUTTON_H))
        container.addSubview_(self.delete_button)
        self.open_button = make_pill(
            t("memory.reveal"), self, "revealFolder:",
            NSMakeRect(PADDING + 286, row_y, 150, BUTTON_H))
        container.addSubview_(self.open_button)

        # A feature that records what you read needs its off switch in the UI,
        # not only in config.json. Both flags apply live: the monitor re-reads
        # them every tick and recall_block checks them per capture.
        self.enabled_switch = _add_switch(
            container, self, cw - PADDING - 40, row_y,
            t("memory.save_master"), "toggleEnabled:")
        self.local_switch = _add_switch(
            container, self, cw - PADDING - 40 - 150, row_y,
            t("memory.local_only"), "toggleLocalOnly:")

        # header: note count + the domains the reading actually falls in
        header_h = 40.0
        self.header = _label("", NSMakeRect(PADDING, ch - PADDING - 20,
                                           cw - 2 * PADDING, 20),
                             size=FONT_SMALL, secondary=True)
        container.addSubview_(self.header)

        detail_top = ch - PADDING - header_h
        self.title_label = _label("", NSMakeRect(PADDING, detail_top - 26,
                                                detail_w, 24),
                                  size=18.0, bold=True)
        container.addSubview_(self.title_label)
        self.sub_label = _label("", NSMakeRect(PADDING, detail_top - 48,
                                               detail_w, 18),
                                size=FONT_SMALL, secondary=True)
        container.addSubview_(self.sub_label)

        body_y = row_y + BUTTON_H + 10
        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(PADDING, body_y, detail_w, detail_top - 56 - body_y))
        scroll.setHasVerticalScroller_(True)
        scroll.setDrawsBackground_(False)
        self.detail = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, detail_w, 10))
        self.detail.setEditable_(False)
        self.detail.setDrawsBackground_(False)
        self.detail.setFont_(NSFont.systemFontOfSize_(FONT_BODY))
        self.detail.setTextContainerInset_(NSMakeSize(4, 6))
        scroll.setDocumentView_(self.detail)
        container.addSubview_(scroll)

        list_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(list_x, PADDING, LIST_WIDTH, ch - PADDING * 2))
        list_scroll.setHasVerticalScroller_(True)
        list_scroll.setDrawsBackground_(False)
        self.table = NSTableView.alloc().initWithFrame_(
            NSMakeRect(0, 0, LIST_WIDTH, ch - PADDING * 2))
        self.table.setStyle_(NSTableViewStyleInset)
        self.table.setFocusRingType_(NSFocusRingTypeNone)
        self.table.setBackgroundColor_(NSColor.clearColor())
        self.table.setRowHeight_(ROW_H)
        self.table.setSelectionHighlightStyle_(
            NSTableViewSelectionHighlightStyleNone)
        column = NSTableColumn.alloc().initWithIdentifier_("note")
        column.setWidth_(LIST_WIDTH - 24)
        self.table.addTableColumn_(column)
        self.table.setHeaderView_(None)
        self.table.setDataSource_(self)
        self.table.setDelegate_(self)
        self.table.setAllowsMultipleSelection_(False)
        list_scroll.setDocumentView_(self.table)
        container.addSubview_(list_scroll)

    # -- refresh -------------------------------------------------------------

    def refresh(self):
        self._notes = self.store.notes()
        stats = self.store.stats()
        parts = [t("memory.count").format(n=stats["notes"])]
        if stats["domains"]:
            parts.append(", ".join(stats["domains"]))
        if stats["pending"]:
            parts.append(t("memory.pending").format(n=stats["pending"]))
        self.header.setStringValue_(" · ".join(parts))
        if self.enabled_switch is not None:
            self.enabled_switch.setState_(
                1 if self.config.get("memory_enabled") else 0)
            self.local_switch.setState_(
                1 if self.config.get("memory_local_only") else 0)
        self.applyFilter_(self._query)

    def applyFilter_(self, query):
        """The window's shared search field also filters notes (M20) — same
        field, dispatched by the selected tab."""
        self._query = str(query or "").strip().lower()
        if self._query:
            self._filtered = [n for n in self._notes if _matches(n, self._query)]
        else:
            self._filtered = list(self._notes)
        if self.table is None:
            return
        self.table.reloadData()
        if self._filtered:
            self.table.selectRowIndexes_byExtendingSelection_(
                NSIndexSet.indexSetWithIndex_(0), False)
        else:
            self.table.deselectAll_(None)
            self._renderSelection()
        print(f"memory tab: {len(self._filtered)}/{len(self._notes)} note(s) "
              f"q={self._query!r}", flush=True)

    def _selected(self):
        row = self.table.selectedRow() if self.table is not None else -1
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def _renderSelection(self):
        note = self._selected()
        if note is None:
            # nothing selected (or nothing to select): the profile IS the view —
            # "what this reader reads" is the memory's own summary of itself.
            self.title_label.setStringValue_(t("memory.profile_title"))
            self.sub_label.setStringValue_("")
            self.detail.setString_(self.store.profile()
                                   or t("memory.empty"))
            if self.delete_button is not None:
                self.delete_button.setEnabled_(False)
            return
        title, subtitle, body = _note_detail(
            note, self.store.note_body(note["slug"]))
        self.title_label.setStringValue_(title)
        self.sub_label.setStringValue_(subtitle)
        self.detail.setString_(body)
        self.detail.scrollRangeToVisible_((0, 0))
        if self.delete_button is not None:
            self.delete_button.setEnabled_(True)

    # -- table datasource / delegate -----------------------------------------

    def numberOfRowsInTableView_(self, table):
        return len(self._filtered)

    def tableView_viewForTableColumn_row_(self, table, column, row):
        note = self._filtered[row]
        w = float(column.width()) if column is not None else LIST_WIDTH - 24
        cell = NSTableCellView.alloc().initWithFrame_(
            NSMakeRect(0, 0, w, ROW_H))
        card = NSBox.alloc().initWithFrame_(NSMakeRect(2, 3, w - 4, ROW_H - 6))
        card.setBoxType_(NSBoxCustom)
        card.setTitlePosition_(0)
        card.setBorderWidth_(0.0)
        card.setCornerRadius_(12.0)
        card.setContentViewMargins_(NSMakeSize(0, 0))
        if row == self.table.selectedRow():
            card.setFillColor_(
                NSColor.controlAccentColor().colorWithAlphaComponent_(0.22))
        else:
            card.setFillColor_(
                NSColor.textBackgroundColor().colorWithAlphaComponent_(0.55))
        body = card.contentView()
        inner_w = w - 28
        title = _label(str(note.get("title") or note.get("slug")),
                       NSMakeRect(12, ROW_H - 32, inner_w, 20), size=FONT_UI)
        title.setLineBreakMode_(4)  # NSLineBreakByTruncatingTail
        body.addSubview_(title)
        summary = " ".join(str(note.get("summary") or "").split())
        body.addSubview_(_label(summary[:70],
                                NSMakeRect(12, ROW_H - 50, inner_w, 16),
                                size=FONT_SMALL, secondary=True))
        meta = " · ".join(filter(None, [
            ", ".join(note.get("domains") or [])[:40],
            t("memory.seen_times").format(n=int(note.get("seen") or 1)),
            str(note.get("last_ts") or "")[:10],
        ]))
        body.addSubview_(_label(meta, NSMakeRect(12, 8, inner_w, 15),
                                size=FONT_SMALL, secondary=True))
        cell.addSubview_(card)
        cell.setTextField_(title)
        return cell

    def tableViewSelectionDidChange_(self, notification):
        self.table.reloadData()   # the card draws its own selection
        self._renderSelection()

    # -- actions -------------------------------------------------------------

    def rebuildProfile_(self, sender):
        print("memory tab: rebuild profile", flush=True)
        if self.on_profile is not None:
            self.on_profile()

    def forgetNote_(self, sender):
        note = self._selected()
        if note is None:
            return
        print(f"memory tab: forget {note['slug']}", flush=True)
        if self.store.delete(note["slug"]):
            self.refresh()

    def toggleEnabled_(self, sender):
        self.config.set("memory_enabled", bool(sender.state()))
        self.config.save()
        print(f"memory: enabled={bool(sender.state())}", flush=True)

    def toggleLocalOnly_(self, sender):
        self.config.set("memory_local_only", bool(sender.state()))
        self.config.save()
        print(f"memory: local_only={bool(sender.state())}", flush=True)

    def revealFolder_(self, sender):
        path = str(self.store.root)
        print(f"memory tab: reveal {path}", flush=True)
        subprocess.Popen(["/usr/bin/open", path])


def _matches(note, query):
    haystack = " ".join([
        str(note.get("title") or ""),
        str(note.get("summary") or ""),
        " ".join(note.get("aliases") or []),
        " ".join(note.get("domains") or []),
        str(note.get("slug") or ""),
    ]).lower()
    return query in haystack

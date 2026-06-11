"""SettingsWindowController — minimal native settings window (M0 scope).

Edits server URL, model ids, and hotkeys; full settings UI lands in M4.
A regular activating window is fine here — the non-activating requirement
applies only to the ResultPanel (M2).

Model fields are editable NSComboBoxes: the dropdown lists the models
currently loaded on the server (/v1/models, fetched on a background thread
each time the window opens), while free text keeps working when the server is
down or for a model id not in the list.
"""

import threading

import httpx
import objc
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSButton,
    NSComboBox,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventModifierFlagShift,
    NSMakeRect,
    NSObject,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextField,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from PyObjCTools import AppHelper

from hotkeys import format_binding

_ESC_KEYCODE = 53
_MOD_SYMBOLS = {"<cmd>": "⌘", "<ctrl>": "⌃", "<alt>": "⌥", "<shift>": "⇧"}

MODEL_FIELDS = [("explain_model", "Explain model"), ("vision_model", "Vision model")]
HOTKEY_FIELDS = [
    ("hotkey_explain_text", "Explain hotkey"),
    ("hotkey_explain_region", "Region hotkey"),
]


def _pretty_binding(binding):
    """'<cmd>+<shift>+e' → '⌘⇧E' for display."""
    return "".join(
        _MOD_SYMBOLS.get(part, part.upper()) for part in binding.split("+")
    )

PADDING = 20
LABEL_WIDTH = 110
FIELD_WIDTH = 330
ROW_HEIGHT = 24
ROW_GAP = 12


class SettingsWindowController(NSObject):
    def initWithConfig_(self, config):
        self = objc.super(SettingsWindowController, self).init()
        if self is None:
            return None
        self.config = config
        self.window = None
        self.url_field = None
        self.model_fields = {}  # config key -> NSComboBox
        self.hotkey_buttons = {}  # config key -> NSButton
        self.detail_control = None  # NSSegmentedControl
        self._detail_keys = []  # segment index -> detail_levels key
        self.status_label = None
        self.on_saved = None  # set by main.py: ExplainController.reloadHotkeys
        self.on_record_changed = None  # set by main.py: pause hotkeys while recording
        self._hotkey_bindings = {}  # config key -> pynput format, saved on Save
        self._record_target = None  # config key currently recording
        self._record_monitor = None
        return self

    def show(self):
        if self.window is None:
            self._buildWindow()
        self._endRecording_(None)  # drop a stale recording session, if any
        self.url_field.setStringValue_(self.config.get("server_base_url"))
        for key, field in self.model_fields.items():
            field.setStringValue_(self.config.get(key))
        for key, button in self.hotkey_buttons.items():
            self._hotkey_bindings[key] = str(self.config.get(key))
            button.setTitle_(_pretty_binding(self._hotkey_bindings[key]))
        current = str(self.config.get("explain_detail"))
        if current in self._detail_keys:
            self.detail_control.setSelectedSegment_(self._detail_keys.index(current))
        self.status_label.setStringValue_("")
        self._refreshModelList()
        import os
        origin_env = os.environ.get("HE_DEBUG_WIN_ORIGIN")
        if origin_env:
            x, y = (float(v) for v in origin_env.split(","))
            self.window.setFrameOrigin_((x, y))
        self.window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        print(
            "settings window shown:", self.window.frame(),
            "visible:", bool(self.window.isVisible()),
            flush=True,
        )

    def _buildWindow(self):
        width = PADDING * 2 + LABEL_WIDTH + 8 + FIELD_WIDTH
        rows = 2 + len(MODEL_FIELDS) + len(HOTKEY_FIELDS)  # + save row below
        height = PADDING * 2 + ROW_HEIGHT * (rows + 1) + ROW_GAP * rows
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("HotkeyExplain Settings")
        self.window.setReleasedWhenClosed_(False)
        self.window.center()
        content = self.window.contentView()

        def row_y(row_index):
            return height - PADDING - ROW_HEIGHT * (row_index + 1) - ROW_GAP * row_index

        def add_label(row_index, text):
            label = NSTextField.labelWithString_(text)
            label.setFrame_(
                NSMakeRect(PADDING, row_y(row_index), LABEL_WIDTH, ROW_HEIGHT)
            )
            content.addSubview_(label)

        def add_row(row_index, label_text, field_class=NSTextField):
            add_label(row_index, label_text)
            field = field_class.alloc().initWithFrame_(
                NSMakeRect(
                    PADDING + LABEL_WIDTH + 8, row_y(row_index),
                    FIELD_WIDTH, ROW_HEIGHT,
                )
            )
            content.addSubview_(field)
            return field

        row = 0
        self.url_field = add_row(row, "Server URL")
        for key, label in MODEL_FIELDS:
            row += 1
            field = add_row(row, label, NSComboBox)
            field.setCompletes_(True)
            self.model_fields[key] = field
        row += 1
        add_label(row, "Detail")
        levels = self.config.get("detail_levels")
        self._detail_keys = list(levels.keys())
        labels = [str(levels[k].get("label", k)) for k in self._detail_keys]
        self.detail_control = (
            NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
                labels, NSSegmentSwitchTrackingSelectOne, None, None
            )
        )
        self.detail_control.setFrame_(
            NSMakeRect(PADDING + LABEL_WIDTH + 8, row_y(row), 220, ROW_HEIGHT)
        )
        content.addSubview_(self.detail_control)

        for key, label in HOTKEY_FIELDS:
            row += 1
            add_label(row, label)
            button = NSButton.buttonWithTitle_target_action_(
                "", self, "recordHotkey:"
            )
            button.setFrame_(
                NSMakeRect(PADDING + LABEL_WIDTH + 8, row_y(row), 160, ROW_HEIGHT)
            )
            content.addSubview_(button)
            self.hotkey_buttons[key] = button

        button_y = PADDING
        save_button = NSButton.buttonWithTitle_target_action_("Save", self, "save:")
        save_button.setFrame_(NSMakeRect(width - PADDING - 80, button_y, 80, ROW_HEIGHT))
        content.addSubview_(save_button)

        self.status_label = NSTextField.labelWithString_("")
        self.status_label.setFrame_(
            NSMakeRect(PADDING, button_y, width - PADDING * 2 - 90, ROW_HEIGHT)
        )
        content.addSubview_(self.status_label)

    # -- hotkey recorder ------------------------------------------------------
    # Click a hotkey button → the next key combo becomes that binding. Captured
    # via a local keyDown monitor (the settings window is key, so events reach
    # our app); matched by keyCode, not character, which under the user's
    # Korean input source would never be a Latin letter. The global hotkey
    # listener is paused while recording so capturing a bound combo doesn't
    # fire it.

    def recordHotkey_(self, sender):
        target = next(
            (key for key, btn in self.hotkey_buttons.items() if btn is sender), None
        )
        if target is None:
            return
        was_recording = self._record_target
        self._endRecording_(None)  # cancel any active session (toggles off)
        if was_recording == target:
            return  # second click on the same button = cancel only
        self._record_target = target
        self.hotkey_buttons[target].setTitle_("단축키를 누르세요… (Esc 취소)")
        self.status_label.setStringValue_("")
        if self.on_record_changed is not None:
            self.on_record_changed(True)
        self._record_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, self._handleRecordKeyDown_
        )

    def _handleRecordKeyDown_(self, event):
        if event.keyCode() == _ESC_KEYCODE:
            self._endRecording_(None)
            return None  # consume
        flags = event.modifierFlags()
        binding = format_binding(
            event.keyCode(),
            cmd=bool(flags & NSEventModifierFlagCommand),
            ctrl=bool(flags & NSEventModifierFlagControl),
            alt=bool(flags & NSEventModifierFlagOption),
            shift=bool(flags & NSEventModifierFlagShift),
        )
        if binding is None or "+" not in binding:
            # non-ANSI key, or no modifier at all — keep recording
            self.status_label.setStringValue_("⌘/⌥/⌃/⇧ 와 함께 눌러주세요")
            return None
        self._endRecording_(binding)
        print("hotkey recorded:", binding, flush=True)
        return None  # consume

    def _endRecording_(self, binding):
        if self._record_monitor is not None:
            NSEvent.removeMonitor_(self._record_monitor)
            self._record_monitor = None
            if self.on_record_changed is not None:
                self.on_record_changed(False)
        if binding is not None and self._record_target is not None:
            self._hotkey_bindings[self._record_target] = binding
        self._record_target = None
        for key, button in self.hotkey_buttons.items():
            if self._hotkey_bindings.get(key):
                button.setTitle_(_pretty_binding(self._hotkey_bindings[key]))

    def _refreshModelList(self):
        base_url = str(self.url_field.stringValue()).strip().rstrip("/")
        timeout = float(self.config.get("request_connect_timeout"))

        def fetch():
            try:
                resp = httpx.get(f"{base_url}/v1/models", timeout=timeout)
                resp.raise_for_status()
                ids = [m["id"] for m in resp.json().get("data", []) if m.get("id")]
            except Exception:
                ids = []  # server down / bad URL: dropdown stays empty, free text still works
            AppHelper.callAfter(self._applyModelList_, ids)

        threading.Thread(target=fetch, daemon=True).start()

    def _applyModelList_(self, ids):
        if self.window is None or not self.window.isVisible():
            return
        for field in self.model_fields.values():
            typed = str(field.stringValue())  # don't clobber user input
            field.removeAllItems()
            if ids:
                field.addItemsWithObjectValues_(ids)
                field.setNumberOfVisibleItems_(min(len(ids), 8))
            field.setStringValue_(typed)
        print("model list refreshed:", ids, flush=True)

    def save_(self, sender):
        self._endRecording_(None)
        self.config.set("server_base_url", str(self.url_field.stringValue()).strip())
        for key, field in self.model_fields.items():
            self.config.set(key, str(field.stringValue()).strip())
        for key, binding in self._hotkey_bindings.items():
            if binding:
                self.config.set(key, binding)
        selected = self.detail_control.selectedSegment()
        if 0 <= selected < len(self._detail_keys):
            self.config.set("explain_detail", self._detail_keys[selected])
        self.config.save()
        if self.on_saved is not None:
            self.on_saved()  # re-register the global hotkeys with new bindings
        self.status_label.setStringValue_("Saved ✓")
        print(
            "settings saved:", self.config.get("server_base_url"),
            self.config.get("explain_model"), self.config.get("vision_model"),
            self.config.get("hotkey_explain_text"),
            self.config.get("hotkey_explain_region"),
            "detail=" + str(self.config.get("explain_detail")), flush=True,
        )

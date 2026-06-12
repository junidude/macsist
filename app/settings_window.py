"""SettingsWindowController — minimal native settings window (M0 scope).

Edits server URL, model ids, and hotkeys; full settings UI lands in M4.
A regular activating window is fine here — the non-activating requirement
applies only to the ResultPanel (M2).

Model fields are editable NSComboBoxes: the dropdown lists the models
currently loaded on the server (/v1/models, fetched on a background thread
each time the window opens), while free text keeps working when the server is
down or for a model id not in the list.

The "고급 설정" toggle expands the window with the fields most LLM UIs hide
behind an Advanced flap: the system prompts (e.g. translate-first behavior),
image user prompt, temperature, max_tokens, follow-up turn cap and
chat_template_kwargs. Top-anchored views carry NSViewMinYMargin so the window
can resize from the bottom edge; the save row sticks to the bottom.
"""

import json
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
    NSFont,
    NSMakeRect,
    NSObject,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextField,
    NSTextView,
    NSViewMinYMargin,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskTitled,
)
from PyObjCTools import AppHelper

from config import DEFAULTS
from hotkeys import format_binding

_ESC_KEYCODE = 53
_MOD_SYMBOLS = {"<cmd>": "⌘", "<ctrl>": "⌃", "<alt>": "⌥", "<shift>": "⇧"}

MODEL_FIELDS = [("explain_model", "Explain model"), ("vision_model", "Vision model")]
HOTKEY_FIELDS = [
    ("hotkey_explain_text", "Explain hotkey"),
    ("hotkey_explain_region", "Region hotkey"),
]
ADV_PROMPT_FIELDS = [
    ("system_prompt_text", "System prompt\n(텍스트)"),
    ("system_prompt_image", "System prompt\n(이미지)"),
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
PROMPT_HEIGHT = 64


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
        # advanced section (system prompts, sampling, follow-up, kwargs)
        self.prompt_views = {}  # config key -> NSTextView
        self.user_prompt_image_field = None
        self.temperature_field = None
        self.max_tokens_field = None
        self.followup_field = None
        self.template_kwargs_field = None
        self.advanced_button = None
        self._advanced_views = []
        self._advanced_visible = False
        self._collapsed_height = 0
        self._expanded_height = 0
        self._win_width = 0
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
        for key, text_view in self.prompt_views.items():
            text_view.setString_(str(self.config.get(key)))
        self.user_prompt_image_field.setStringValue_(
            str(self.config.get("user_prompt_image"))
        )
        self.temperature_field.setStringValue_(str(self.config.get("temperature")))
        self.max_tokens_field.setStringValue_(str(self.config.get("max_tokens")))
        self.followup_field.setStringValue_(
            str(self.config.get("followup_max_turns"))
        )
        self.template_kwargs_field.setStringValue_(
            json.dumps(self.config.get("chat_template_kwargs"), ensure_ascii=False)
        )
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
        self._win_width = width
        basic_rows = 2 + len(MODEL_FIELDS) + len(HOTKEY_FIELDS)
        self._collapsed_height = (
            PADDING * 2 + ROW_HEIGHT * (basic_rows + 1) + ROW_GAP * basic_rows
        )
        # advanced flap: 2 prompt editors + 3 field rows + reset row
        self._expanded_height = (
            self._collapsed_height
            + len(ADV_PROMPT_FIELDS) * (PROMPT_HEIGHT + ROW_GAP)
            + 4 * (ROW_HEIGHT + ROW_GAP)
        )
        # Build at EXPANDED height (all frames laid out top-down), then
        # collapse: top-anchored views carry NSViewMinYMargin, so shrinking
        # the window pushes the advanced rows below the content bounds.
        height = self._expanded_height
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable,
            NSBackingStoreBuffered,
            False,
        )
        self.window.setTitle_("HotkeyExplain Settings")
        self.window.setReleasedWhenClosed_(False)
        content = self.window.contentView()

        y_cursor = [height - PADDING]

        def place(h):
            y_cursor[0] -= h
            y = y_cursor[0]
            y_cursor[0] -= ROW_GAP
            return y

        def pin(view, advanced=False):
            view.setAutoresizingMask_(NSViewMinYMargin)  # track the top edge
            content.addSubview_(view)
            if advanced:
                self._advanced_views.append(view)

        def add_label_at(y, text, advanced=False, x=PADDING, w=LABEL_WIDTH,
                         h=ROW_HEIGHT):
            label = NSTextField.labelWithString_(text)
            label.setFrame_(NSMakeRect(x, y, w, h))
            pin(label, advanced)
            return label

        def add_row(label_text, field_class=NSTextField, advanced=False):
            y = place(ROW_HEIGHT)
            add_label_at(y, label_text, advanced)
            field = field_class.alloc().initWithFrame_(
                NSMakeRect(
                    PADDING + LABEL_WIDTH + 8, y, FIELD_WIDTH, ROW_HEIGHT
                )
            )
            pin(field, advanced)
            return field

        # -- basic section --
        self.url_field = add_row("Server URL")
        for key, label in MODEL_FIELDS:
            field = add_row(label, NSComboBox)
            field.setCompletes_(True)
            self.model_fields[key] = field
        y = place(ROW_HEIGHT)
        add_label_at(y, "Detail")
        levels = self.config.get("detail_levels")
        self._detail_keys = list(levels.keys())
        labels = [str(levels[k].get("label", k)) for k in self._detail_keys]
        self.detail_control = (
            NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
                labels, NSSegmentSwitchTrackingSelectOne, None, None
            )
        )
        self.detail_control.setFrame_(
            NSMakeRect(PADDING + LABEL_WIDTH + 8, y, 220, ROW_HEIGHT)
        )
        pin(self.detail_control)

        for key, label in HOTKEY_FIELDS:
            y = place(ROW_HEIGHT)
            add_label_at(y, label)
            button = NSButton.buttonWithTitle_target_action_(
                "", self, "recordHotkey:"
            )
            button.setFrame_(
                NSMakeRect(PADDING + LABEL_WIDTH + 8, y, 160, ROW_HEIGHT)
            )
            pin(button)
            self.hotkey_buttons[key] = button

        # -- advanced section (hidden until toggled) --
        for key, label in ADV_PROMPT_FIELDS:
            y = place(PROMPT_HEIGHT)
            label_view = add_label_at(
                y, label, advanced=True, h=PROMPT_HEIGHT
            )
            label_view.setFont_(NSFont.systemFontOfSize_(12.0))
            scroll = NSTextView.scrollableTextView()
            scroll.setFrame_(
                NSMakeRect(
                    PADDING + LABEL_WIDTH + 8, y, FIELD_WIDTH, PROMPT_HEIGHT
                )
            )
            text_view = scroll.documentView()
            text_view.setRichText_(False)
            text_view.setFont_(NSFont.systemFontOfSize_(12.0))
            # prompts are data, not prose — no smart quotes/dashes/replacements
            text_view.setAutomaticQuoteSubstitutionEnabled_(False)
            text_view.setAutomaticDashSubstitutionEnabled_(False)
            text_view.setAutomaticTextReplacementEnabled_(False)
            pin(scroll, advanced=True)
            self.prompt_views[key] = text_view

        self.user_prompt_image_field = add_row(
            "Image user prompt", advanced=True
        )

        y = place(ROW_HEIGHT)
        add_label_at(y, "Temperature", advanced=True)
        self.temperature_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(PADDING + LABEL_WIDTH + 8, y, 70, ROW_HEIGHT)
        )
        pin(self.temperature_field, advanced=True)
        x = PADDING + LABEL_WIDTH + 8 + 70 + 16
        add_label_at(y, "Max tokens", advanced=True, x=x, w=85)
        self.max_tokens_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(x + 85 + 4, y, 70, ROW_HEIGHT)
        )
        pin(self.max_tokens_field, advanced=True)

        y = place(ROW_HEIGHT)
        add_label_at(y, "Follow-up 턴 수", advanced=True)
        self.followup_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(PADDING + LABEL_WIDTH + 8, y, 70, ROW_HEIGHT)
        )
        pin(self.followup_field, advanced=True)
        x = PADDING + LABEL_WIDTH + 8 + 70 + 16
        add_label_at(y, "Template kwargs", advanced=True, x=x, w=110)
        self.template_kwargs_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(x + 110 + 4, y, width - PADDING - (x + 110 + 4), ROW_HEIGHT)
        )
        pin(self.template_kwargs_field, advanced=True)

        y = place(ROW_HEIGHT)
        reset_button = NSButton.buttonWithTitle_target_action_(
            "고급 기본값 복원", self, "resetAdvanced:"
        )
        reset_button.setFrame_(
            NSMakeRect(PADDING + LABEL_WIDTH + 8, y, 160, ROW_HEIGHT)
        )
        pin(reset_button, advanced=True)

        # -- bottom row (sticks to the bottom edge: default autoresizing) --
        button_y = PADDING
        save_button = NSButton.buttonWithTitle_target_action_("Save", self, "save:")
        save_button.setFrame_(NSMakeRect(width - PADDING - 80, button_y, 80, ROW_HEIGHT))
        content.addSubview_(save_button)

        self.advanced_button = NSButton.buttonWithTitle_target_action_(
            "고급 설정 ▾", self, "toggleAdvanced:"
        )
        self.advanced_button.setFrame_(
            NSMakeRect(PADDING, button_y, 110, ROW_HEIGHT)
        )
        content.addSubview_(self.advanced_button)

        self.status_label = NSTextField.labelWithString_("")
        self.status_label.setFrame_(
            NSMakeRect(
                PADDING + 118, button_y, width - PADDING * 2 - 118 - 90, ROW_HEIGHT
            )
        )
        content.addSubview_(self.status_label)

        for view in self._advanced_views:
            view.setHidden_(True)
        self._setContentHeight_animate_(self._collapsed_height, False)
        self.window.center()

    def _setContentHeight_animate_(self, target_height, animate):
        frame_rect = self.window.frameRectForContentRect_(
            NSMakeRect(0, 0, self._win_width, target_height)
        )
        old = self.window.frame()
        self.window.setFrame_display_animate_(
            NSMakeRect(
                old.origin.x,
                old.origin.y + old.size.height - frame_rect.size.height,
                frame_rect.size.width,
                frame_rect.size.height,
            ),
            True,
            animate,
        )

    def toggleAdvanced_(self, sender):
        self._advanced_visible = not self._advanced_visible
        for view in self._advanced_views:
            view.setHidden_(not self._advanced_visible)
        self._setContentHeight_animate_(
            self._expanded_height if self._advanced_visible
            else self._collapsed_height,
            True,
        )
        self.advanced_button.setTitle_(
            "고급 설정 ▴" if self._advanced_visible else "고급 설정 ▾"
        )
        print(
            "advanced settings", "shown" if self._advanced_visible else "hidden",
            "frame:", self.window.frame(), flush=True,
        )

    def resetAdvanced_(self, sender):
        """Reset the advanced FIELDS to the shipped defaults — applied on Save."""
        for key, text_view in self.prompt_views.items():
            text_view.setString_(str(DEFAULTS[key]))
        self.user_prompt_image_field.setStringValue_(
            str(DEFAULTS["user_prompt_image"])
        )
        self.temperature_field.setStringValue_(str(DEFAULTS["temperature"]))
        self.max_tokens_field.setStringValue_(str(DEFAULTS["max_tokens"]))
        self.followup_field.setStringValue_(str(DEFAULTS["followup_max_turns"]))
        self.template_kwargs_field.setStringValue_(
            json.dumps(DEFAULTS["chat_template_kwargs"], ensure_ascii=False)
        )
        self.status_label.setStringValue_("기본값 복원됨 — Save로 적용")

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

    def _collectAdvanced(self):
        """Validate the advanced fields → (values dict, None) or (None, error).
        Always collected, even with the flap closed — show() loaded the fields
        from config, so saving them back unchanged is a no-op."""
        values = {}
        for key, text_view in self.prompt_views.items():
            text = str(text_view.string()).strip()
            if not text:
                return None, "System prompt가 비어 있습니다."
            values[key] = text
        user_prompt = str(self.user_prompt_image_field.stringValue()).strip()
        if not user_prompt:
            return None, "Image user prompt가 비어 있습니다."
        values["user_prompt_image"] = user_prompt
        try:
            values["temperature"] = float(
                str(self.temperature_field.stringValue()).strip()
            )
        except ValueError:
            return None, "Temperature는 숫자여야 합니다."
        try:
            values["max_tokens"] = int(
                str(self.max_tokens_field.stringValue()).strip()
            )
        except ValueError:
            return None, "Max tokens는 정수여야 합니다."
        try:
            values["followup_max_turns"] = int(
                str(self.followup_field.stringValue()).strip()
            )
        except ValueError:
            return None, "Follow-up 턴 수는 정수여야 합니다."
        kwargs_text = str(self.template_kwargs_field.stringValue()).strip()
        if not kwargs_text:
            values["chat_template_kwargs"] = {}
        else:
            try:
                kwargs = json.loads(kwargs_text)
            except ValueError:
                return None, 'Template kwargs는 JSON이어야 합니다 (예: {"enable_thinking": false})'
            if not isinstance(kwargs, dict):
                return None, "Template kwargs는 JSON 객체여야 합니다."
            values["chat_template_kwargs"] = kwargs
        return values, None

    def save_(self, sender):
        self._endRecording_(None)
        advanced, error = self._collectAdvanced()
        if error:
            self.status_label.setStringValue_("⚠ " + error)
            print("settings NOT saved:", error, flush=True)
            return
        self.config.set("server_base_url", str(self.url_field.stringValue()).strip())
        for key, field in self.model_fields.items():
            self.config.set(key, str(field.stringValue()).strip())
        for key, binding in self._hotkey_bindings.items():
            if binding:
                self.config.set(key, binding)
        selected = self.detail_control.selectedSegment()
        if 0 <= selected < len(self._detail_keys):
            self.config.set("explain_detail", self._detail_keys[selected])
        for key, value in advanced.items():
            self.config.set(key, value)
        self.config.save()
        if self.on_saved is not None:
            self.on_saved()  # re-register the global hotkeys with new bindings
        self.status_label.setStringValue_("Saved ✓")
        print(
            "settings saved:", self.config.get("server_base_url"),
            self.config.get("explain_model"), self.config.get("vision_model"),
            self.config.get("hotkey_explain_text"),
            self.config.get("hotkey_explain_region"),
            "detail=" + str(self.config.get("explain_detail")),
            "temp=" + str(self.config.get("temperature")),
            "max_tokens=" + str(self.config.get("max_tokens")),
            "followup=" + str(self.config.get("followup_max_turns")),
            "prompt_text[:30]=" + repr(
                str(self.config.get("system_prompt_text"))[:30]
            ),
            flush=True,
        )

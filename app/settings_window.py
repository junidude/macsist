"""SettingsPaneController — the Settings controls, built into a host view.

M8 redesign (user-directed, Codex-style): scrollable sections — a bold
header per section, each a rounded card of rows (title + description on the
left, the control on the right, hairline separators between rows). The old
"고급 설정" flap is gone: 고급 is just another section and the pane scrolls.

Sections: 연결 (server/models) · 응답 (detail preset) · 단축키 (recorder
buttons) · 모양 (panel font/box sizes + glass style — M8) · 고급 (system
prompts, sampling, follow-up, template kwargs).

All M0–M6 logic is unchanged: field population, the keycode-based hotkey
recorder, /v1/models fetch, validation and the explicit Save (which fires
on_saved → hotkey re-registration + result-panel rebuild).
"""

import json
import threading

import httpx
import objc
from AppKit import (
    NSBox,
    NSBoxCustom,
    NSBoxSeparator,
    NSColor,
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
    NSPopUpButton,
    NSScrollView,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextField,
    NSTextView,
    NSViewHeightSizable,
    NSViewWidthSizable,
)
from Foundation import NSMakeSize
from PyObjCTools import AppHelper

from config import DEFAULTS
from hotkeys import format_binding
from ui_kit import FlippedView, make_pill, make_round_field

FONT_TITLE = 15.0  # row titles (Codex-style, user feedback)
FONT_DESC = 13.0  # row descriptions
FONT_FIELD = 14.0  # input text

_ESC_KEYCODE = 53
_MOD_SYMBOLS = {"<cmd>": "⌘", "<ctrl>": "⌃", "<alt>": "⌥", "<shift>": "⇧"}

MODEL_FIELDS = [
    ("explain_model", "설명 모델", "텍스트 설명에 사용"),
    ("vision_model", "비전 모델", "화면 캡처 설명에 사용 (멀티모달 모델 필요)"),
]
HOTKEY_FIELDS = [
    ("hotkey_explain_text", "텍스트 설명", "선택한 텍스트를 설명"),
    ("hotkey_explain_region", "영역 설명", "화면 영역을 캡처해 설명"),
    ("hotkey_open_history", "기록 창", "History/Settings 창 토글"),
]
ADV_PROMPT_FIELDS = [
    ("system_prompt_text", "System prompt (텍스트)"),
    ("system_prompt_image", "System prompt (이미지)"),
]
_GLASS_STYLE_ITEMS = [("regular", "Frosted (기본)"), ("clear", "투명 (Clear)")]

# layout
INSET_X = 24.0  # sections inset from the pane edges
CARD_RADIUS = 12.0
ROW_PAD_X = 16.0
ROW_H = 66.0  # row with title + description, control on the right
INPUT_ROW_H = 104.0  # stacked row: title + desc + full-width round field
PROMPT_ROW_H = 156.0  # title + multi-line text view (15pt, ~5 lines)
SECTION_GAP = 28.0
BOTTOM_BAR_H = 56.0
CTRL_W_WIDE = 320.0
CTRL_W_NARROW = 96.0


def pane_min_size():
    """Minimum tab-content size for the Settings pane. The pane scrolls, so
    this is a comfortable floor, not the full content height."""
    return 680.0, 620.0


def _pretty_binding(binding):
    """'<cmd>+<shift>+e' → '⌘⇧E' for display."""
    return "".join(
        _MOD_SYMBOLS.get(part, part.upper()) for part in binding.split("+")
    )


class SettingsPaneController(NSObject):
    def initWithConfig_(self, config):
        self = objc.super(SettingsPaneController, self).init()
        if self is None:
            return None
        self.config = config
        self.container = None  # host NSView, injected via buildInView_
        self.url_field = None
        self.model_fields = {}  # config key -> NSComboBox
        self.hotkey_buttons = {}  # config key -> pill NSButton
        self.detail_control = None  # NSSegmentedControl
        self._detail_keys = []  # segment index -> detail_levels key
        self.status_label = None
        # 모양 (M8): result-panel sizing + glass style
        self.panel_font_field = None
        self.panel_width_field = None
        self.panel_height_field = None
        self.glass_style_popup = None
        # 고급 (system prompts, sampling, follow-up, kwargs)
        self.prompt_views = {}  # config key -> NSTextView
        self.user_prompt_image_field = None
        self.temperature_field = None
        self.max_tokens_field = None
        self.followup_field = None
        self.template_kwargs_field = None
        self.on_saved = None  # set by main.py: hotkey reload + panel rebuild
        self.on_record_changed = None  # set by main.py: pause hotkeys while recording
        self._hotkey_bindings = {}  # config key -> pynput format, saved on Save
        self._record_target = None  # config key currently recording
        self._record_monitor = None
        return self

    # -- refresh ---------------------------------------------------------------

    def refresh(self):
        """(Re)load every field from config — called each time the Settings
        tab is shown. buildInView_ must have run first."""
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
        self.panel_font_field.setStringValue_(
            f"{float(self.config.get('panel_font_size')):g}"
        )
        self.panel_width_field.setStringValue_(
            f"{float(self.config.get('panel_width')):g}"
        )
        self.panel_height_field.setStringValue_(
            f"{float(self.config.get('panel_height')):g}"
        )
        style = str(self.config.get("glass_style"))
        keys = [k for k, _label in _GLASS_STYLE_ITEMS]
        self.glass_style_popup.selectItemAtIndex_(
            keys.index(style) if style in keys else 0
        )
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
        print("settings pane refreshed", flush=True)

    # -- build (Codex-style sections + cards) -----------------------------------

    def buildInView_(self, container):
        self.container = container
        size = container.frame().size
        width, height = size.width, size.height

        scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, BOTTOM_BAR_H, width, height - BOTTOM_BAR_H)
        )
        scroll.setHasVerticalScroller_(True)
        scroll.setDrawsBackground_(False)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        doc = FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, width, 10))
        scroll.setDocumentView_(doc)
        container.addSubview_(scroll)

        card_w = width - 2 * INSET_X
        ctrl_x = card_w - ROW_PAD_X  # controls right-aligned inside the card
        self._y = 20.0

        def section(title):
            label = NSTextField.labelWithString_(title)
            label.setFont_(NSFont.boldSystemFontOfSize_(15.0))
            label.setFrame_(NSMakeRect(INSET_X, self._y, card_w, 20))
            doc.addSubview_(label)
            self._y += 30

        def card(rows):
            """rows: list of (row_height, build(card_content, row_y)) — the
            card box grows to fit; hairline separators between rows."""
            card_h = sum(h for h, _build in rows)
            box = NSBox.alloc().initWithFrame_(
                NSMakeRect(INSET_X, self._y, card_w, card_h)
            )
            box.setBoxType_(NSBoxCustom)
            box.setTitlePosition_(0)
            box.setBorderWidth_(0.0)
            box.setCornerRadius_(CARD_RADIUS)
            box.setContentViewMargins_(NSMakeSize(0, 0))
            box.setFillColor_(
                NSColor.textBackgroundColor().colorWithAlphaComponent_(0.55)
            )
            inner = FlippedView.alloc().initWithFrame_(
                NSMakeRect(0, 0, card_w, card_h)
            )
            box.setContentView_(inner)
            doc.addSubview_(box)
            row_y = 0.0
            for i, (row_h, build) in enumerate(rows):
                if i > 0:
                    sep = NSBox.alloc().initWithFrame_(
                        NSMakeRect(ROW_PAD_X, row_y, card_w - 2 * ROW_PAD_X, 1)
                    )
                    sep.setBoxType_(NSBoxSeparator)
                    inner.addSubview_(sep)
                build(inner, row_y)
                row_y += row_h
            self._y += card_h + SECTION_GAP

        def titled(inner, row_y, title, desc):
            label = NSTextField.labelWithString_(title)
            label.setFont_(NSFont.systemFontOfSize_(FONT_TITLE))
            label.setFrame_(NSMakeRect(ROW_PAD_X, row_y + 12, 460, 19))
            inner.addSubview_(label)
            if desc:
                sub = NSTextField.labelWithString_(desc)
                sub.setFont_(NSFont.systemFontOfSize_(FONT_DESC))
                sub.setTextColor_(NSColor.secondaryLabelColor())
                sub.setFrame_(NSMakeRect(ROW_PAD_X, row_y + 36, 520, 17))
                inner.addSubview_(sub)

        def control_frame(row_y, w, h=28):
            return NSMakeRect(ctrl_x - w, row_y + (ROW_H - h) / 2.0, w, h)

        def field_row(title, desc, w=CTRL_W_WIDE, field_class=NSTextField):
            """Compact row: ChatGPT-style round field on the right (numbers
            and other short values)."""
            holder = {}

            def build(inner, row_y):
                titled(inner, row_y, title, desc)
                if field_class is NSTextField:
                    box, field = make_round_field(
                        control_frame(row_y, w, 32), FONT_FIELD
                    )
                    inner.addSubview_(box)
                else:
                    field = field_class.alloc().initWithFrame_(
                        control_frame(row_y, w)
                    )
                    field.setFont_(NSFont.systemFontOfSize_(FONT_FIELD))
                    inner.addSubview_(field)
                holder["field"] = field
            return holder, (ROW_H, build)

        def input_row(title, desc):
            """Stacked row: title + description, full-width round field below
            (the ChatGPT input look the user asked for)."""
            holder = {}

            def build(inner, row_y):
                titled(inner, row_y, title, desc)
                box, field = make_round_field(
                    NSMakeRect(ROW_PAD_X, row_y + 58,
                               card_w - 2 * ROW_PAD_X, 34),
                    FONT_FIELD,
                )
                inner.addSubview_(box)
                holder["field"] = field
            return holder, (INPUT_ROW_H, build)

        # ---- 연결 ----
        section("연결")
        url_holder, url_row = input_row(
            "서버 주소", "로컬 MLX 프록시 또는 OpenAI 호환 엔드포인트"
        )
        model_holders, model_rows = [], []
        for key, title, desc in MODEL_FIELDS:
            holder, row = field_row(title, desc, field_class=NSComboBox)
            model_holders.append((key, holder))
            model_rows.append(row)
        card([url_row] + model_rows)
        self.url_field = url_holder["field"]
        for key, holder in model_holders:
            holder["field"].setCompletes_(True)
            self.model_fields[key] = holder["field"]

        # ---- 응답 ----
        section("응답")
        levels = self.config.get("detail_levels")
        self._detail_keys = list(levels.keys())
        seg_labels = [str(levels[k].get("label", k)) for k in self._detail_keys]

        def build_detail(inner, row_y):
            titled(inner, row_y, "상세도", "답변 길이/깊이 프리셋")
            control = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
                seg_labels, NSSegmentSwitchTrackingSelectOne, None, None
            )
            control.setFrame_(control_frame(row_y, 230))
            inner.addSubview_(control)
            self.detail_control = control
        card([(ROW_H, build_detail)])

        # ---- 단축키 ----
        section("단축키")
        hotkey_rows = []
        for key, title, desc in HOTKEY_FIELDS:
            def build_hotkey(inner, row_y, key=key, title=title, desc=desc):
                titled(inner, row_y, title, desc)
                button = make_pill("", self, "recordHotkey:",
                                   control_frame(row_y, 190, 30))
                inner.addSubview_(button)
                self.hotkey_buttons[key] = button
            hotkey_rows.append((ROW_H, build_hotkey))
        card(hotkey_rows)

        # ---- 모양 (M8: panel sizing + glass) ----
        section("모양")

        def size_row(title, desc):
            holder, row = field_row(title, desc, w=CTRL_W_NARROW)
            return holder, row

        font_holder, font_row = size_row(
            "패널 폰트 크기", "결과 패널 본문/입력 글자 크기 (pt)"
        )
        width_holder, width_row = size_row(
            "패널 너비", "결과 패널 가로 크기 (pt)"
        )
        height_holder, height_row = size_row(
            "패널 최대 높이", "내용에 따라 이 높이까지 자라고, 그 뒤로는 스크롤"
        )

        def build_glass(inner, row_y):
            titled(inner, row_y, "Glass 스타일",
                   "패널/창 유리 효과 — Frosted가 가독성이 좋습니다")
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                control_frame(row_y, 170), False
            )
            for _key, label in _GLASS_STYLE_ITEMS:
                popup.addItemWithTitle_(label)
            inner.addSubview_(popup)
            self.glass_style_popup = popup
        card([font_row, width_row, height_row, (ROW_H, build_glass)])
        self.panel_font_field = font_holder["field"]
        self.panel_width_field = width_holder["field"]
        self.panel_height_field = height_holder["field"]

        # ---- 고급 ----
        section("고급")
        adv_rows = []
        for key, title in ADV_PROMPT_FIELDS:
            def build_prompt(inner, row_y, key=key, title=title):
                titled(inner, row_y, title, None)
                frame = NSMakeRect(
                    ROW_PAD_X, row_y + 40, card_w - 2 * ROW_PAD_X,
                    PROMPT_ROW_H - 52,
                )
                # same rounded-input look as the single-line fields
                backdrop = NSBox.alloc().initWithFrame_(frame)
                backdrop.setBoxType_(NSBoxCustom)
                backdrop.setTitlePosition_(0)
                backdrop.setBorderWidth_(0.0)
                backdrop.setCornerRadius_(9.0)
                backdrop.setContentViewMargins_(NSMakeSize(0, 0))
                backdrop.setFillColor_(
                    NSColor.labelColor().colorWithAlphaComponent_(0.06)
                )
                inner.addSubview_(backdrop)
                prompt_scroll = NSTextView.scrollableTextView()
                prompt_scroll.setFrame_(frame)
                prompt_scroll.setDrawsBackground_(False)
                text_view = prompt_scroll.documentView()
                text_view.setRichText_(False)
                text_view.setDrawsBackground_(False)
                text_view.setFont_(NSFont.systemFontOfSize_(15.0))
                text_view.setTextContainerInset_((8.0, 8.0))
                # prompts are data, not prose — no smart substitutions
                text_view.setAutomaticQuoteSubstitutionEnabled_(False)
                text_view.setAutomaticDashSubstitutionEnabled_(False)
                text_view.setAutomaticTextReplacementEnabled_(False)
                inner.addSubview_(prompt_scroll)
                self.prompt_views[key] = text_view
            adv_rows.append((PROMPT_ROW_H, build_prompt))

        img_holder, img_row = input_row(
            "이미지 질문 프롬프트", "화면 캡처와 함께 보내는 사용자 메시지"
        )
        adv_rows.append(img_row)
        temp_holder, temp_row = field_row(
            "Temperature", "샘플링 온도 (0~2)", w=CTRL_W_NARROW
        )
        adv_rows.append(temp_row)
        tokens_holder, tokens_row = field_row(
            "Max tokens", "응답 길이 상한 (상세도 프리셋이 우선)",
            w=CTRL_W_NARROW,
        )
        adv_rows.append(tokens_row)
        followup_holder, followup_row = field_row(
            "Follow-up 턴 수", "추가 질문 대화 깊이 (오래된 쌍부터 삭제)",
            w=CTRL_W_NARROW,
        )
        adv_rows.append(followup_row)
        kwargs_holder, kwargs_row = input_row(
            "Template kwargs", 'JSON — 로컬 서버 전용 (예: {"enable_thinking": false})'
        )
        adv_rows.append(kwargs_row)

        def build_reset(inner, row_y):
            titled(inner, row_y, "기본값 복원", "고급 필드를 출하 기본값으로 (저장 시 적용)")
            button = make_pill("복원", self, "resetAdvanced:",
                               control_frame(row_y, 90, 30))
            inner.addSubview_(button)
        adv_rows.append((ROW_H, build_reset))
        card(adv_rows)

        self.user_prompt_image_field = img_holder["field"]
        self.temperature_field = temp_holder["field"]
        self.max_tokens_field = tokens_holder["field"]
        self.followup_field = followup_holder["field"]
        self.template_kwargs_field = kwargs_holder["field"]

        doc.setFrame_(NSMakeRect(0, 0, width, self._y + 8))

        # -- bottom bar: status + Save (pinned below the scroll) --
        self.status_label = NSTextField.labelWithString_("")
        self.status_label.setFont_(NSFont.systemFontOfSize_(FONT_DESC))
        self.status_label.setFrame_(
            NSMakeRect(INSET_X, (BOTTOM_BAR_H - 18) / 2, width - 200, 18)
        )
        container.addSubview_(self.status_label)
        save_button = make_pill(
            "저장", self, "save:",
            NSMakeRect(width - INSET_X - 96, (BOTTOM_BAR_H - 32) / 2, 96, 32),
        )
        container.addSubview_(save_button)

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
        self.status_label.setStringValue_("기본값 복원됨 — 저장으로 적용")

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

    # -- model list -------------------------------------------------------------

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
        host = self.container.window() if self.container is not None else None
        if host is None or not host.isVisible():
            return
        for field in self.model_fields.values():
            typed = str(field.stringValue())  # don't clobber user input
            field.removeAllItems()
            if ids:
                field.addItemsWithObjectValues_(ids)
                field.setNumberOfVisibleItems_(min(len(ids), 8))
            field.setStringValue_(typed)
        print("model list refreshed:", ids, flush=True)

    # -- save -------------------------------------------------------------------

    def _collectAppearance(self):
        """Validate the 모양 fields → (values dict, None) or (None, error)."""
        values = {}
        try:
            font_size = float(str(self.panel_font_field.stringValue()).strip())
        except ValueError:
            return None, "패널 폰트 크기는 숫자여야 합니다."
        if not 8 <= font_size <= 40:
            return None, "패널 폰트 크기는 8~40 사이여야 합니다."
        values["panel_font_size"] = font_size
        try:
            panel_w = float(str(self.panel_width_field.stringValue()).strip())
            panel_h = float(str(self.panel_height_field.stringValue()).strip())
        except ValueError:
            return None, "패널 크기는 숫자여야 합니다."
        if panel_w < 200 or panel_h < 150:
            return None, "패널 크기가 너무 작습니다 (너비 200+, 높이 150+)."
        values["panel_width"] = panel_w
        values["panel_height"] = panel_h
        idx = int(self.glass_style_popup.indexOfSelectedItem())
        values["glass_style"] = _GLASS_STYLE_ITEMS[
            idx if 0 <= idx < len(_GLASS_STYLE_ITEMS) else 0
        ][0]
        return values, None

    def _collectAdvanced(self):
        """Validate the advanced fields → (values dict, None) or (None, error)."""
        values = {}
        for key, text_view in self.prompt_views.items():
            text = str(text_view.string()).strip()
            if not text:
                return None, "System prompt가 비어 있습니다."
            values[key] = text
        user_prompt = str(self.user_prompt_image_field.stringValue()).strip()
        if not user_prompt:
            return None, "이미지 질문 프롬프트가 비어 있습니다."
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
        appearance, error = self._collectAppearance()
        if error is None:
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
        for key, value in appearance.items():
            self.config.set(key, value)
        for key, value in advanced.items():
            self.config.set(key, value)
        self.config.save()
        if self.on_saved is not None:
            self.on_saved()  # re-register hotkeys + rebuild the result panel
        self.status_label.setStringValue_("저장됨 ✓")
        print(
            "settings saved:", self.config.get("server_base_url"),
            self.config.get("explain_model"), self.config.get("vision_model"),
            self.config.get("hotkey_explain_text"),
            self.config.get("hotkey_explain_region"),
            "detail=" + str(self.config.get("explain_detail")),
            "panel=" + f"{self.config.get('panel_width'):g}x"
                       f"{self.config.get('panel_height'):g}"
                       f"@{self.config.get('panel_font_size'):g}pt",
            "glass=" + str(self.config.get("glass_style")),
            "temp=" + str(self.config.get("temperature")),
            "max_tokens=" + str(self.config.get("max_tokens")),
            "followup=" + str(self.config.get("followup_max_turns")),
            flush=True,
        )

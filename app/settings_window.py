"""SettingsPaneController — the Settings controls, built into a host view.

M8 redesign (user-directed, Codex-style): scrollable sections — a bold
header per section, each a rounded card of rows (title + description on the
left, the control on the right, hairline separators between rows). The old
"고급 설정" flap is gone: 고급 is just another section and the pane scrolls.

Sections: 연결 (providers — M9) · 응답 (detail preset) · 단축키 (recorder
buttons) · 모양 (panel font/box sizes + glass style — M8) · 고급 (system
prompts, sampling, follow-up, template kwargs).

M9 — the 연결 section manages the `providers` list: a picker chooses which
entry the fields below edit (and which becomes `active_provider` on Save).
Everything is staged in memory (`_providers` deepcopy) and committed by the
explicit Save, matching the rest of the pane. Typed API keys go to the
Keychain on Save (staged in a private `_pending_key` field, stripped before
config.set) — they NEVER reach config.json; the config keeps only the
Keychain account name in `api_key_env_or_value`.
"""

import copy
import json
import re
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
    NSSwitch,
    NSTextField,
    NSTextView,
    NSViewHeightSizable,
    NSViewWidthSizable,
)
from Foundation import NSMakeSize
from PyObjCTools import AppHelper

import i18n
import keychain
from i18n import t
from config import DEFAULTS
from hotkeys import format_binding
from ui_kit import FlippedView, make_pill, make_round_field

FONT_TITLE = 15.0  # row titles (Codex-style, user feedback)
FONT_DESC = 13.0  # row descriptions
FONT_FIELD = 14.0  # input text

_ESC_KEYCODE = 53
_MOD_SYMBOLS = {"<cmd>": "⌘", "<ctrl>": "⌃", "<alt>": "⌥", "<shift>": "⇧"}

MODEL_FIELDS = [  # (config key, i18n title key, i18n desc key)
    ("explain_model", "settings.model_explain_title",
     "settings.model_explain_desc"),
    ("vision_model", "settings.model_vision_title",
     "settings.model_vision_desc"),
]
# M9: template for 추가 — OpenRouter is the documented example endpoint
NEW_PROVIDER = {
    "name": "",  # filled with t("settings.new_provider_name") at add time
    "base_url": "https://openrouter.ai/api",
    "api_key_env_or_value": "",
    "explain_model": "",
    "vision_model": "",
    "is_local": False,
}
HOTKEY_FIELDS = [  # (config key, i18n title key, i18n desc key)
    ("hotkey_explain_text", "settings.hk_text_title", "settings.hk_text_desc"),
    ("hotkey_explain_region", "settings.hk_region_title",
     "settings.hk_region_desc"),
    ("hotkey_open_history", "settings.hk_history_title",
     "settings.hk_history_desc"),
]
ADV_PROMPT_FIELDS = [  # (config key, i18n label key)
    ("system_prompt_text", "settings.prompt_text_label"),
    ("system_prompt_image", "settings.prompt_image_label"),
]
_GLASS_STYLE_ITEMS = [("regular", "settings.glass_regular"),
                      ("clear", "settings.glass_clear")]

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


def _unique_account(providers, name):
    """Keychain account for a provider getting its first key: a slug of the
    name, de-duplicated against every other staged ref. Stable once stored —
    later renames don't touch the Keychain. (Module-level: PyObjC selectors
    can't take plain positional args without underscore naming.)"""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    base = f"provider-{slug}" if slug else "provider"
    taken = {
        str(p.get("api_key_env_or_value", "")).strip() for p in providers
    }
    account, n = base, 2
    while account in taken:
        account, n = f"{base}-{n}", n + 1
    return account


class SettingsPaneController(NSObject):
    def initWithConfig_(self, config):
        self = objc.super(SettingsPaneController, self).init()
        if self is None:
            return None
        self.config = config
        self.container = None  # host NSView, injected via buildInView_
        self.url_field = None
        self.model_fields = {}  # provider field -> NSComboBox (M9: per-provider)
        # M9 provider management — staged in memory, committed on Save
        self.provider_popup = None
        self.name_field = None
        self.key_field = None  # NSSecureTextField
        self.key_desc_label = None  # doubles as the key status line
        self.local_switch = None
        self._providers = []  # deepcopy of config["providers"] being edited
        self._selected = 0  # index into _providers (edited + active on Save)
        self._deleted_refs = []  # keychain accounts to delete on Save
        self.hotkey_buttons = {}  # config key -> pill NSButton
        self.detail_control = None  # NSSegmentedControl
        self._detail_keys = []  # segment index -> detail_levels key
        # M11 language picker — popup shows native names, never translated
        self.language_popup = None
        self._language_codes = list(i18n.LANGUAGES)
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
        # 비서 (M14): proactive toggle + trust dial + interval
        self.assistant_proactive_switch = None
        self.assistant_autonomy_popup = None
        self.assistant_interval_field = None
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
        self._providers = copy.deepcopy(self.config.get("providers")) or [
            copy.deepcopy(DEFAULTS["providers"][0])
        ]
        self._deleted_refs = []
        names = [str(p.get("name", "")) for p in self._providers]
        active = str(self.config.get("active_provider"))
        self._selected = names.index(active) if active in names else 0
        self._rebuildProviderPopup()
        self._loadProviderFields()
        for key, button in self.hotkey_buttons.items():
            self._hotkey_bindings[key] = str(self.config.get(key))
            button.setTitle_(_pretty_binding(self._hotkey_bindings[key]))
        lang = str(self.config.get("language"))
        self.language_popup.selectItemAtIndex_(
            self._language_codes.index(lang)
            if lang in self._language_codes else 0
        )
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
        keys = [k for k, _label_key in _GLASS_STYLE_ITEMS]
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
        self.assistant_proactive_switch.setState_(
            1 if self.config.get("assistant_proactive_enabled") else 0
        )
        self.assistant_autonomy_popup.selectItemAtIndex_(
            1 if str(self.config.get("assistant_autonomy")) == "auto_safe" else 0
        )
        self.assistant_interval_field.setStringValue_(
            f"{float(self.config.get('assistant_proactive_interval')):g}"
        )
        self.status_label.setStringValue_("")
        print("settings pane refreshed", flush=True)

    # -- provider staging (M9) ---------------------------------------------------

    def _rebuildProviderPopup(self):
        """Repopulate the picker from the staged list. Items go through the
        menu directly — NSPopUpButton.addItemWithTitle_ silently drops
        duplicate titles, and unsaved edits may briefly duplicate names."""
        popup = self.provider_popup
        popup.removeAllItems()
        for entry in self._providers:
            popup.menu().addItemWithTitle_action_keyEquivalent_(
                str(entry.get("name", "")), None, ""
            )
        popup.selectItemAtIndex_(self._selected)

    def _loadProviderFields(self):
        entry = self._providers[self._selected]
        self.name_field.setStringValue_(str(entry.get("name", "")))
        self.url_field.setStringValue_(str(entry.get("base_url", "")))
        self.key_field.setStringValue_("")  # never display stored keys
        self.local_switch.setState_(1 if entry.get("is_local") else 0)
        for key, field in self.model_fields.items():
            field.setStringValue_(str(entry.get(key, "")))
        self._updateKeyStatus()
        self._refreshModelList()

    def _stashFields(self):
        """Fields → the staged entry. A typed key moves to the private
        _pending_key staging slot (committed to the Keychain on Save) and the
        secure field is cleared immediately."""
        entry = self._providers[self._selected]
        entry["name"] = str(self.name_field.stringValue()).strip()
        entry["base_url"] = str(self.url_field.stringValue()).strip()
        entry["is_local"] = bool(self.local_switch.state())
        for key, field in self.model_fields.items():
            entry[key] = str(field.stringValue()).strip()
        typed = str(self.key_field.stringValue()).strip()
        if typed:
            entry["_pending_key"] = typed
            self.key_field.setStringValue_("")
        self._updateKeyStatus()

    def _updateKeyStatus(self):
        entry = self._providers[self._selected]
        ref = str(entry.get("api_key_env_or_value", "")).strip()
        if entry.get("_pending_key"):
            text = t("settings.key_new")
        elif ref.startswith("env:"):
            text = t("settings.key_env").format(ref=ref)
        elif ref:
            text = t("settings.key_stored")
        else:
            text = t("settings.key_none")
        self.key_desc_label.setStringValue_(text)

    def providerChanged_(self, sender):
        idx = int(sender.indexOfSelectedItem())
        if idx == self._selected or not 0 <= idx < len(self._providers):
            return
        self._stashFields()
        self._selected = idx
        self._rebuildProviderPopup()  # pick up a possible rename
        self._loadProviderFields()

    def addProvider_(self, sender):
        self._stashFields()
        entry = dict(NEW_PROVIDER)
        entry["name"] = t("settings.new_provider_name")
        names = {str(p.get("name", "")) for p in self._providers}
        if entry["name"] in names:
            n = 2
            while f"{entry['name']} {n}" in names:
                n += 1
            entry["name"] = f"{entry['name']} {n}"
        self._providers.append(entry)
        self._selected = len(self._providers) - 1
        self._rebuildProviderPopup()
        self._loadProviderFields()
        self.status_label.setStringValue_(t("settings.provider_added"))

    def deleteProvider_(self, sender):
        if len(self._providers) <= 1:
            self.status_label.setStringValue_(t("settings.provider_last"))
            return
        entry = self._providers.pop(self._selected)
        ref = str(entry.get("api_key_env_or_value", "")).strip()
        if ref and not ref.startswith("env:"):
            self._deleted_refs.append(ref)  # Keychain cleanup on Save
        self._selected = 0
        self._rebuildProviderPopup()
        self._loadProviderFields()
        self.status_label.setStringValue_(
            t("settings.provider_delete_staged").format(
                name=entry.get("name", ""))
        )

    def fetchModels_(self, sender):
        self._refreshModelList()

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
            sub = None
            if desc:
                sub = NSTextField.labelWithString_(desc)
                sub.setFont_(NSFont.systemFontOfSize_(FONT_DESC))
                sub.setTextColor_(NSColor.secondaryLabelColor())
                sub.setFrame_(NSMakeRect(ROW_PAD_X, row_y + 36, 520, 17))
                inner.addSubview_(sub)
            return sub  # M9: the API-key row repurposes this as a status line

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

        # ---- 일반 (M11: language) ----
        section(t("settings.section_general"))

        def build_language(inner, row_y):
            titled(inner, row_y, t("settings.language_title"),
                   t("settings.language_desc"))
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                control_frame(row_y, 170), False
            )
            for name in i18n.LANGUAGES.values():
                popup.addItemWithTitle_(name)
            inner.addSubview_(popup)
            self.language_popup = popup
        card([(ROW_H, build_language)])

        # ---- 연결 (M9: provider picker + per-provider fields) ----
        section(t("settings.section_connection"))

        def build_picker(inner, row_y):
            titled(inner, row_y, t("settings.active_provider_title"),
                   t("settings.active_provider_desc"))
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                control_frame(row_y, 260), False
            )
            popup.setTarget_(self)
            popup.setAction_("providerChanged:")
            inner.addSubview_(popup)
            self.provider_popup = popup

        def build_manage(inner, row_y):
            titled(inner, row_y, t("settings.manage_title"),
                   t("settings.manage_desc"))
            inner.addSubview_(make_pill(
                t("settings.add"), self, "addProvider:",
                NSMakeRect(ctrl_x - 188, row_y + (ROW_H - 30) / 2, 90, 30),
            ))
            inner.addSubview_(make_pill(
                t("settings.delete"), self, "deleteProvider:",
                NSMakeRect(ctrl_x - 90, row_y + (ROW_H - 30) / 2, 90, 30),
            ))
        card([(ROW_H, build_picker), (ROW_H, build_manage)])

        name_holder, name_row = input_row(t("settings.name_label"),
                                          t("settings.name_placeholder"))
        url_holder, url_row = input_row(
            t("settings.url_label"),
            t("settings.url_placeholder"),
        )

        key_holder = {}

        def build_key(inner, row_y):
            # input_row twin, but secure + a handle on the desc label so it
            # can double as the Keychain status line
            self.key_desc_label = titled(inner, row_y,
                                         t("settings.api_key_title"), " ")
            box, field = make_round_field(
                NSMakeRect(ROW_PAD_X, row_y + 58,
                           card_w - 2 * ROW_PAD_X, 34),
                FONT_FIELD, secure=True,
            )
            inner.addSubview_(box)
            key_holder["field"] = field

        def build_local(inner, row_y):
            titled(inner, row_y, t("settings.local_title"),
                   t("settings.local_desc"))
            switch = NSSwitch.alloc().initWithFrame_(
                control_frame(row_y, 42, 25)
            )
            inner.addSubview_(switch)
            self.local_switch = switch

        model_holders, model_rows = [], []
        for key, title_key, desc_key in MODEL_FIELDS:
            holder, row = field_row(t(title_key), t(desc_key),
                                    field_class=NSComboBox)
            model_holders.append((key, holder))
            model_rows.append(row)

        def build_fetch(inner, row_y):
            titled(inner, row_y, t("settings.models_title"),
                   t("settings.models_desc"))
            inner.addSubview_(make_pill(
                t("settings.refresh"), self, "fetchModels:",
                control_frame(row_y, 110, 30)
            ))
        card([name_row, url_row, (INPUT_ROW_H, build_key),
              (ROW_H, build_local)] + model_rows + [(ROW_H, build_fetch)])
        self.name_field = name_holder["field"]
        self.url_field = url_holder["field"]
        self.key_field = key_holder["field"]
        for key, holder in model_holders:
            holder["field"].setCompletes_(True)
            self.model_fields[key] = holder["field"]

        # ---- 응답 ----
        section(t("settings.section_response"))
        levels = self.config.get("detail_levels")
        self._detail_keys = list(levels.keys())
        seg_labels = [str(levels[k].get("label", k)) for k in self._detail_keys]

        def build_detail(inner, row_y):
            titled(inner, row_y, t("settings.detail_title"),
                   t("settings.detail_desc"))
            control = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
                seg_labels, NSSegmentSwitchTrackingSelectOne, None, None
            )
            control.setFrame_(control_frame(row_y, 230))
            inner.addSubview_(control)
            self.detail_control = control
        card([(ROW_H, build_detail)])

        # ---- 비서 (M14) ----
        section(t("settings.section_assistant"))

        def build_proactive(inner, row_y):
            titled(inner, row_y, t("settings.assistant_proactive_title"),
                   t("settings.assistant_proactive_desc"))
            switch = NSSwitch.alloc().initWithFrame_(
                control_frame(row_y, 42, 25))
            inner.addSubview_(switch)
            self.assistant_proactive_switch = switch

        def build_autonomy(inner, row_y):
            titled(inner, row_y, t("settings.assistant_autonomy_title"),
                   t("settings.assistant_autonomy_desc"))
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                control_frame(row_y, 240), False)
            popup.addItemWithTitle_(t("settings.autonomy_propose"))
            popup.addItemWithTitle_(t("settings.autonomy_auto"))
            inner.addSubview_(popup)
            self.assistant_autonomy_popup = popup

        interval_holder, interval_row = field_row(
            t("settings.assistant_interval_title"),
            t("settings.assistant_interval_desc"), w=120)
        card([(ROW_H, build_proactive), (ROW_H, build_autonomy), interval_row])
        self.assistant_interval_field = interval_holder["field"]

        # ---- 단축키 ----
        section(t("settings.section_hotkeys"))
        hotkey_rows = []
        for key, title_key, desc_key in HOTKEY_FIELDS:
            def build_hotkey(inner, row_y, key=key, title_key=title_key,
                             desc_key=desc_key):
                titled(inner, row_y, t(title_key), t(desc_key))
                button = make_pill("", self, "recordHotkey:",
                                   control_frame(row_y, 190, 30))
                inner.addSubview_(button)
                self.hotkey_buttons[key] = button
            hotkey_rows.append((ROW_H, build_hotkey))
        card(hotkey_rows)

        # ---- 모양 (M8: panel sizing + glass) ----
        section(t("settings.section_appearance"))

        def size_row(title, desc):
            holder, row = field_row(title, desc, w=CTRL_W_NARROW)
            return holder, row

        font_holder, font_row = size_row(
            t("settings.font_title"), t("settings.font_desc")
        )
        width_holder, width_row = size_row(
            t("settings.width_title"), t("settings.width_desc")
        )
        height_holder, height_row = size_row(
            t("settings.height_title"), t("settings.height_desc")
        )

        def build_glass(inner, row_y):
            titled(inner, row_y, t("settings.glass_title"),
                   t("settings.glass_desc"))
            popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
                control_frame(row_y, 170), False
            )
            for _key, label_key in _GLASS_STYLE_ITEMS:
                popup.addItemWithTitle_(t(label_key))
            inner.addSubview_(popup)
            self.glass_style_popup = popup
        card([font_row, width_row, height_row, (ROW_H, build_glass)])
        self.panel_font_field = font_holder["field"]
        self.panel_width_field = width_holder["field"]
        self.panel_height_field = height_holder["field"]

        # ---- 고급 ----
        section(t("settings.section_advanced"))
        adv_rows = []
        for key, label_key in ADV_PROMPT_FIELDS:
            def build_prompt(inner, row_y, key=key, label_key=label_key):
                titled(inner, row_y, t(label_key), None)
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
            t("settings.img_prompt_title"), t("settings.img_prompt_desc")
        )
        adv_rows.append(img_row)
        temp_holder, temp_row = field_row(
            t("settings.temp_title"), t("settings.temp_desc"), w=CTRL_W_NARROW
        )
        adv_rows.append(temp_row)
        tokens_holder, tokens_row = field_row(
            t("settings.maxtok_title"), t("settings.maxtok_desc"),
            w=CTRL_W_NARROW,
        )
        adv_rows.append(tokens_row)
        followup_holder, followup_row = field_row(
            t("settings.followup_title"), t("settings.followup_desc"),
            w=CTRL_W_NARROW,
        )
        adv_rows.append(followup_row)
        kwargs_holder, kwargs_row = input_row(
            t("settings.kwargs_title"), t("settings.kwargs_desc")
        )
        adv_rows.append(kwargs_row)

        def build_reset(inner, row_y):
            titled(inner, row_y, t("settings.reset_title"),
                   t("settings.reset_desc"))
            button = make_pill(t("settings.reset_btn"), self, "resetAdvanced:",
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
            t("settings.save_btn"), self, "save:",
            NSMakeRect(width - INSET_X - 96, (BOTTOM_BAR_H - 32) / 2, 96, 32),
        )
        container.addSubview_(save_button)

    def resetAdvanced_(self, sender):
        """Reset the advanced FIELDS to the shipped defaults — applied on Save."""
        lang = str(self.config.get("language"))
        for key, text_view in self.prompt_views.items():
            text_view.setString_(str(i18n.prompt_default(key, lang)))
        self.user_prompt_image_field.setStringValue_(
            str(i18n.prompt_default("user_prompt_image", lang))
        )
        self.temperature_field.setStringValue_(str(DEFAULTS["temperature"]))
        self.max_tokens_field.setStringValue_(str(DEFAULTS["max_tokens"]))
        self.followup_field.setStringValue_(str(DEFAULTS["followup_max_turns"]))
        self.template_kwargs_field.setStringValue_(
            json.dumps(DEFAULTS["chat_template_kwargs"], ensure_ascii=False)
        )
        self.status_label.setStringValue_(t("settings.reset_done"))

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
        self.hotkey_buttons[target].setTitle_(t("settings.record_prompt"))
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
            self.status_label.setStringValue_(t("settings.record_need_mod"))
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
        # M9: authenticate like a real request would — a just-typed key wins,
        # then a staged pending key, then the stored Keychain/env reference
        # (resolved inside the fetch thread: it's a subprocess)
        entry = self._providers[self._selected] if self._providers else {}
        typed = str(self.key_field.stringValue()).strip() if self.key_field else ""
        pending = str(entry.get("_pending_key", ""))
        ref = str(entry.get("api_key_env_or_value", ""))

        def fetch():
            headers = {}
            key = typed or pending
            if not key:
                try:
                    key = keychain.resolve_key(ref)
                except keychain.KeychainError:
                    key = None
            if key:
                headers["Authorization"] = f"Bearer {key}"
            try:
                resp = httpx.get(
                    f"{base_url}/v1/models", timeout=timeout, headers=headers
                )
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
            return None, t("settings.v_font_num")
        if not 8 <= font_size <= 40:
            return None, t("settings.v_font_range")
        values["panel_font_size"] = font_size
        try:
            panel_w = float(str(self.panel_width_field.stringValue()).strip())
            panel_h = float(str(self.panel_height_field.stringValue()).strip())
        except ValueError:
            return None, t("settings.v_size_num")
        if panel_w < 200 or panel_h < 150:
            return None, t("settings.v_size_small")
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
                return None, t("settings.v_prompt_empty")
            values[key] = text
        user_prompt = str(self.user_prompt_image_field.stringValue()).strip()
        if not user_prompt:
            return None, t("settings.v_img_prompt_empty")
        values["user_prompt_image"] = user_prompt
        try:
            values["temperature"] = float(
                str(self.temperature_field.stringValue()).strip()
            )
        except ValueError:
            return None, t("settings.v_temp")
        try:
            values["max_tokens"] = int(
                str(self.max_tokens_field.stringValue()).strip()
            )
        except ValueError:
            return None, t("settings.v_maxtok")
        try:
            values["followup_max_turns"] = int(
                str(self.followup_field.stringValue()).strip()
            )
        except ValueError:
            return None, t("settings.v_followup")
        kwargs_text = str(self.template_kwargs_field.stringValue()).strip()
        if not kwargs_text:
            values["chat_template_kwargs"] = {}
        else:
            try:
                kwargs = json.loads(kwargs_text)
            except ValueError:
                return None, t("settings.v_kwargs_json")
            if not isinstance(kwargs, dict):
                return None, t("settings.v_kwargs_obj")
            values["chat_template_kwargs"] = kwargs
        return values, None

    def _validateProviders(self):
        names = [str(p.get("name", "")).strip() for p in self._providers]
        if any(not n for n in names):
            return t("settings.v_pname_empty")
        if len(set(names)) != len(names):
            return t("settings.v_pname_dup")
        for entry in self._providers:
            if not str(entry.get("base_url", "")).startswith("http"):
                return t("settings.v_url").format(name=entry["name"])
        if not str(self._providers[self._selected].get("explain_model", "")).strip():
            return t("settings.v_explain_empty")
        return None

    def _commitKeychain(self):
        """Pending keys → Keychain; deferred deletions. Only on full success
        are the staging slots cleared, so a failed Save can simply be retried
        (set_key -U is idempotent). Raises KeychainError."""
        for entry in self._providers:
            secret = entry.get("_pending_key")
            if not secret:
                continue
            ref = str(entry.get("api_key_env_or_value", "")).strip()
            if not ref or ref.startswith("env:"):
                ref = _unique_account(self._providers, entry["name"])
            keychain.set_key(ref, secret)
            entry["api_key_env_or_value"] = ref
        for ref in self._deleted_refs:
            keychain.delete_key(ref)
        self._deleted_refs = []
        for entry in self._providers:
            entry.pop("_pending_key", None)
        self._updateKeyStatus()

    def save_(self, sender):
        self._endRecording_(None)
        self._stashFields()
        error = self._validateProviders()
        appearance = advanced = None
        if error is None:
            appearance, error = self._collectAppearance()
        if error is None:
            advanced, error = self._collectAdvanced()
        if error:
            self.status_label.setStringValue_("⚠ " + error)
            print("settings NOT saved:", error, flush=True)
            return
        try:
            self._commitKeychain()
        except keychain.KeychainError as err:
            self.status_label.setStringValue_("⚠ " + str(err))
            print("settings NOT saved:", err, flush=True)
            return
        self.config.set("providers", copy.deepcopy(self._providers))
        self.config.set(
            "active_provider", self._providers[self._selected]["name"]
        )
        self._rebuildProviderPopup()  # pick up renames
        for key, binding in self._hotkey_bindings.items():
            if binding:
                self.config.set(key, binding)
        lang_index = self.language_popup.indexOfSelectedItem()
        if 0 <= lang_index < len(self._language_codes):
            self.config.set("language", self._language_codes[lang_index])
        selected = self.detail_control.selectedSegment()
        if 0 <= selected < len(self._detail_keys):
            self.config.set("explain_detail", self._detail_keys[selected])
        for key, value in appearance.items():
            self.config.set(key, value)
        for key, value in advanced.items():
            self.config.set(key, value)
        # 비서 (M14)
        self.config.set("assistant_proactive_enabled",
                        bool(self.assistant_proactive_switch.state()))
        self.config.set(
            "assistant_autonomy",
            "auto_safe" if self.assistant_autonomy_popup.indexOfSelectedItem() == 1
            else "propose_only")
        try:
            self.config.set("assistant_proactive_interval",
                            float(self.assistant_interval_field.stringValue()))
        except (ValueError, TypeError):
            pass  # keep the current interval on a bad value
        self.config.save()
        if self.on_saved is not None:
            self.on_saved()  # re-register hotkeys + rebuild the result panel
        self.status_label.setStringValue_(t("settings.saved"))
        active = self.config.active_provider()  # never log keys, only refs
        print(
            "settings saved:",
            f"provider={active['name']} ({active['base_url']})",
            active["explain_model"], active["vision_model"],
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

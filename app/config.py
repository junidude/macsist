"""ConfigStore — JSON-backed settings at ~/Library/Application Support/HotkeyExplain/.

Every tunable lives here (hard rule: no hardcoding in feature code).
Unknown keys in the file are preserved so manual edits survive upgrades.
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "HotkeyExplain"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "server_base_url": "http://127.0.0.1:8000",
    "explain_model": "mlx-community/Qwen3.6-35B-A3B-4bit",
    # region-capture requests always use this model: the explain model may be
    # a text-only pick (e.g. Qwen3.6-27B) while vision needs a multimodal one
    "vision_model": "mlx-community/Qwen3.6-35B-A3B-4bit",
    "alt_model": "mlx-community/Gemma-4-12B-4bit",
    "agent_model": "mlx-community/Qwen3.6-27B-4bit",
    "system_prompt_text": (
        "너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트의 핵심을 3~5문장으로 "
        "설명하고, 전문용어는 짧게 풀어줘. 군더더기 금지."
    ),
    "system_prompt_image": (
        "너는 한국어로 답하는 간결한 해설가다. 이미지의 핵심 내용을 설명하고, "
        "표/코드/도식이면 의미를 풀어줘. 3~6문장."
    ),
    "user_prompt_image": "이 이미지를 한국어로 간결하게 설명해줘.",
    # Detail presets: suffix is appended to the system prompt (text & image),
    # max_tokens overrides the global one so 자세히 doesn't get cut off.
    "explain_detail": "normal",
    "detail_levels": {
        "brief": {
            "label": "간단",
            "prompt_suffix": " 한두 문장으로 핵심만 말해.",
            "max_tokens": 256,
        },
        "normal": {
            "label": "보통",
            "prompt_suffix": "",
            "max_tokens": 512,
        },
        "detailed": {
            "label": "자세히",
            "prompt_suffix": (
                " 단, 이번에는 배경 지식과 맥락, 예시를 포함해 6~10문장으로 "
                "자세하게 설명해."
            ),
            "max_tokens": 1024,
        },
    },
    "hotkey_explain_text": "<cmd>+<shift>+e",
    "hotkey_explain_region": "<cmd>+<shift>+r",
    "max_tokens": 512,
    "temperature": 0.7,
    # Thinking models (e.g. Qwen3.6-27B) stream chain-of-thought as
    # delta.reasoning and can burn the whole max_tokens budget before any
    # content; for a hotkey explainer the latency isn't worth it either.
    "chat_template_kwargs": {"enable_thinking": False},
    "request_connect_timeout": 5.0,
    "request_read_timeout": 120.0,
    "region_max_dim": 1600,
    "capture_copy_timeout": 0.6,
    "capture_modifier_release_timeout": 0.3,
    "capture_max_chars": 4000,
    "panel_width": 420.0,
    "panel_height": 260.0,
    "panel_cursor_offset": 12.0,
}


class ConfigStore:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                on_disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                on_disk = {}
            self._data = {**DEFAULTS, **on_disk}
        else:
            self.save()

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self, key):
        return self._data[key]

    def set(self, key, value):
        self._data[key] = value

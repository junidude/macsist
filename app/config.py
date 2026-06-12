"""ConfigStore — JSON-backed settings at ~/Library/Application Support/Macsist/.

Every tunable lives here (hard rule: no hardcoding in feature code).
Unknown keys in the file are preserved so manual edits survive upgrades.
"""

import json
import shutil
from pathlib import Path

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Macsist"
CONFIG_PATH = CONFIG_DIR / "config.json"
# Pre-rename location: through M7 the whole product was called HotkeyExplain;
# now that's just the hotkey-explain feature and the product is Macsist.
_LEGACY_DIR = Path.home() / "Library" / "Application Support" / "HotkeyExplain"


def _migrate_legacy_data():
    """One-time move of user data after the Macsist rename. The legacy dir
    also holds old app/server deployments — those are redeployed, not moved."""
    for name in ("config.json", "history.jsonl"):
        old, new = _LEGACY_DIR / name, CONFIG_DIR / name
        if old.exists() and not new.exists():
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            shutil.move(old, new)
            print(f"migrated {name}: HotkeyExplain/ -> Macsist/", flush=True)

DEFAULTS = {
    # M9: ordered provider list — any OpenAI-compatible endpoint. api_key_env_or_value
    # is "" (no auth) | "env:VAR" | a Keychain account name (see keychain.py);
    # actual keys NEVER live in this file. vision_model is separate because the
    # explain model may be a text-only pick while region capture needs multimodal.
    # chat_template_kwargs (below) is only ever sent to is_local providers.
    "providers": [
        {
            "name": "로컬 서버",
            "base_url": "http://127.0.0.1:8000",
            "api_key_env_or_value": "",
            "explain_model": "mlx-community/Qwen3.6-35B-A3B-4bit",
            "vision_model": "mlx-community/Qwen3.6-35B-A3B-4bit",
            "is_local": True,
        },
    ],
    "active_provider": "로컬 서버",
    "alt_model": "mlx-community/Gemma-4-12B-4bit",
    "agent_model": "mlx-community/Qwen3.6-27B-4bit",
    "system_prompt_text": (
        "너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트가 한국어가 아니면"
        "(영어/중국어/일본어 등) 먼저 '번역:'으로 시작하는 자연스러운 한국어 "
        "번역을 제시하고(긴 글이면 핵심 위주로), 그다음 핵심을 3~5문장으로 "
        "설명해. 전문용어는 짧게 풀어줘. 군더더기 금지."
    ),
    "system_prompt_image": (
        "너는 한국어로 답하는 간결한 해설가다. 이미지 속 텍스트가 한국어가 "
        "아니면 먼저 '번역:'으로 시작하는 한국어 번역을 제시한 뒤 설명해. "
        "이미지의 핵심 내용을 설명하고, 표/코드/도식이면 의미를 풀어줘. 3~6문장."
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
    # History 윈도우 토글 (Cmd-Tab 미등장 보완 — Accessory 앱)
    "hotkey_open_history": "<cmd>+<shift>+h",
    "max_tokens": 512,
    "temperature": 0.7,
    # Thinking models (e.g. Qwen3.6-27B) stream chain-of-thought as
    # delta.reasoning and can burn the whole max_tokens budget before any
    # content; for a hotkey explainer the latency isn't worth it either.
    "chat_template_kwargs": {"enable_thinking": False},
    "request_connect_timeout": 5.0,
    "request_read_timeout": 120.0,
    "health_poll_interval": 10.0,
    "health_poll_timeout": 2.0,
    # external providers are polled via GET /v1/models over the internet —
    # needs more headroom than the local 2s budget
    "health_poll_timeout_external": 5.0,
    "region_max_dim": 1600,
    "capture_copy_timeout": 0.6,
    "capture_modifier_release_timeout": 0.3,
    "capture_max_chars": 4000,
    # M8 폴리시: 상자 1.3배 / 폰트 1.15배 확대 (사용자 피드백)
    "panel_width": 546.0,
    # M8: 패널은 panel_min_height에서 시작해 내용에 맞춰 panel_height까지
    # 자라고(auto-height), 그 뒤로는 스크롤된다.
    "panel_height": 338.0,
    "panel_min_height": 156.0,
    "panel_font_size": 15.0,
    # follow-up 세션이 시작되면(첫 질문 제출) 패널이 이 높이로 커진다 (M6)
    "panel_height_expanded": 546.0,
    "panel_cursor_offset": 12.0,
    # M8 glass UI: NSGlassEffectView 사용 여부 (False면 NSVisualEffectView
    # hudWindow 폴백 — Liquid Glass가 문제를 일으킬 때의 킬스위치)
    "glass_enabled": True,
    # "regular"(frosted — 가독성 유지) 또는 "clear"(최대 투명도)
    "glass_style": "regular",
    # History 창 본체 glass 위에 깔리는 배경 틴트의 불투명도 (0=완전 클리어)
    "glass_window_tint_alpha": 0.5,
    # Spotlight/제어 센터급 큰 둥근 모서리 (사용자 피드백, M8 폴리시)
    "panel_corner_radius": 26.0,
    "panel_fade_duration": 0.15,
    # follow-up 대화 깊이: 원래 질문/답 + N개의 추가 질문/답 쌍, 오래된 쌍부터 삭제
    "followup_max_turns": 5,
    # M7 history: JSONL at CONFIG_DIR/history.jsonl, pruned by file rewrite.
    # snippet == capture_max_chars so text-mode inputs are stored losslessly
    # (re-ask re-runs the stored input verbatim).
    "history_enabled": True,
    # per-mode sub-toggles under the master switch: text/followup records vs
    # region records (region saves the capture PNG to history_images/ so
    # 다시 질문 can re-send it)
    "history_save_text": True,
    "history_save_images": True,
    "history_max_items": 500,
    "history_snippet_chars": 4000,
    "history_window_floating": False,
}


# Old default values superseded by later versions. save() writes every key to
# disk, so an untouched default would otherwise be pinned forever; if the
# on-disk value still equals a stale default the user never customized it —
# drop it and let the current default apply. Customized values are never touched.
_SUPERSEDED_DEFAULTS = {
    # M8 폴리시: clear 전면 적용이 과해서 regular+틴트로 후퇴 (사용자 피드백)
    "glass_style": ("clear",),
    "panel_corner_radius": (16.0,),
    # M8 폴리시: 상자 1.3배 확대 — 옛 기본값이 저장돼 있으면 새 값으로
    "panel_width": (420.0,),
    "panel_height": (260.0,),
    "panel_min_height": (120.0,),
    "panel_height_expanded": (420.0,),
    "system_prompt_text": (
        "너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트의 핵심을 3~5문장으로 "
        "설명하고, 전문용어는 짧게 풀어줘. 군더더기 금지.",
    ),
    "system_prompt_image": (
        "너는 한국어로 답하는 간결한 해설가다. 이미지의 핵심 내용을 설명하고, "
        "표/코드/도식이면 의미를 풀어줘. 3~6문장.",
    ),
}


def _migrate_providers(on_disk):
    """M9: fold the pre-provider keys (server_base_url / explain_model /
    vision_model) into providers[0] so an existing setup keeps working.
    Returns True if the file should be rewritten."""
    if "providers" in on_disk:
        # already migrated — just drop stray legacy keys
        stray = [k for k in ("server_base_url", "explain_model", "vision_model")
                 if on_disk.pop(k, None) is not None]
        return bool(stray)
    legacy_map = {"server_base_url": "base_url", "explain_model": "explain_model",
                  "vision_model": "vision_model"}
    if not any(k in on_disk for k in legacy_map):
        return False  # fresh file without legacy keys: defaults apply
    seed = dict(DEFAULTS["providers"][0])
    for old_key, field in legacy_map.items():
        if old_key in on_disk:
            seed[field] = on_disk.pop(old_key)
    on_disk["providers"] = [seed]
    on_disk["active_provider"] = seed["name"]
    print("migrated config: server/model keys -> providers[0]", flush=True)
    return True


class ConfigStore:
    def __init__(self):
        _migrate_legacy_data()
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                on_disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                on_disk = {}
            for key, stale_values in _SUPERSEDED_DEFAULTS.items():
                if on_disk.get(key) in stale_values:
                    del on_disk[key]
            migrated = _migrate_providers(on_disk)
            self._data = {**DEFAULTS, **on_disk}
            if migrated:
                self.save()
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

    def active_provider(self):
        """The provider dict requests should use right now (M9). Resolved by
        name on every call so a Settings save / debug hook applies to the next
        request without restart. Returns a merged copy — hand-edited entries
        with missing fields must not KeyError; an unknown name or an empty
        list falls back to providers[0] / the shipped default."""
        fallback = DEFAULTS["providers"][0]
        providers = [p for p in self._data.get("providers", []) or []
                     if isinstance(p, dict)]
        if not providers:
            return dict(fallback)
        name = str(self._data.get("active_provider", ""))
        chosen = next((p for p in providers if p.get("name") == name),
                      providers[0])
        return {**fallback, **chosen}

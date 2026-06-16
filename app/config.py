"""ConfigStore — JSON-backed settings at ~/Library/Application Support/Macsist/.

Every tunable lives here (hard rule: no hardcoding in feature code).
Unknown keys in the file are preserved so manual edits survive upgrades.
"""

import json
import os
import shutil
from pathlib import Path

import i18n

CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Macsist"
CONFIG_PATH = CONFIG_DIR / "config.json"


def asset_dir() -> Path:
    """assets/ next to the modules (dev run) or Contents/Resources/assets
    inside the bundle (M12 — RESOURCEPATH is set by the py2app stub; module
    __file__ lives in site-packages.zip there, so it can't be used)."""
    rp = os.environ.get("RESOURCEPATH")
    if rp:
        return Path(rp) / "assets"
    return Path(__file__).resolve().parent / "assets"

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
    # First-run onboarding (M13): a fresh config (downloaded .app, no install.sh)
    # starts False so the app guides the user to pick a backend. install.sh marks
    # it True via cli/configure.py, and any pre-existing config is grandfathered
    # to True at load — so onboarding only ever shows a truly fresh download.
    "onboarded": False,
    "alt_model": "mlx-community/Gemma-4-12B-4bit",
    "agent_model": "mlx-community/Qwen3.6-27B-4bit",
    # M11: UI + LLM output language (i18n.LANGUAGES). The prompt keys
    # (system_prompt_text/image, user_prompt_image, detail_levels) are NOT in
    # DEFAULTS anymore — get() resolves them from i18n.PROMPT_DEFAULTS for the
    # current language unless the user customized them (then on-disk wins).
    "language": "ko",
    # Detail presets live in i18n per language; the selected key is
    # language-neutral.
    "explain_detail": "normal",
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
    # 메인/Settings 창 외형 — explain 패널과 분리(사용자 피드백): 패널은 커서
    # 위 떠다니는 작은 글래스라 투명해도 되지만, 본체 창은 글이 읽혀야 한다.
    # 기본은 거의 불투명(0.9)해 데스크톱이 비쳐 가독성을 해치지 않게 한다.
    "window_glass_enabled": True,
    "window_glass_style": "regular",        # regular(프로스트) | clear
    "window_tint_alpha": 0.9,               # 0=완전 투명 … 1=불투명

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
    # ── Assistant subsystem (M13+) — docs/ASSISTANT.md ────────────────────
    # Master switch for the read-only cockpit + live board polling. The
    # *proactive* engine (M14) is a SEPARATE opt-in (assistant_proactive_*),
    # so this can default on: it only mirrors an existing local kanban board.
    "assistant_enabled": True,
    # Agent backend (the external task board / agent the 비서 connects to).
    # "auto" = Hermes if its kanban.db/CLI is present, else local-only; "local"
    # = no external agent (clean local to-dos, the kanban section is hidden);
    # "hermes" = force Hermes. OpenClaw/Pi/custom connectors come later — local
    # is first-class so the assistant works with no agent installed at all.
    "assistant_backend": "auto",
    # The ONLY Hermes contact points (read-only DB + CLI). Keys never here.
    "assistant_kanban_db_path": "~/.hermes/kanban.db",
    "hermes_bin": "~/.local/bin/hermes",
    # board poll cadence (seconds); change detection diffs task_events.id
    "assistant_tick_interval": 300.0,
    # "" = all tenants; "remote" etc. to scope the cockpit (M16 remote jobs)
    "assistant_kanban_tenant": "",
    # ── Proactive engine (M14) — the real opt-in (propose-then-confirm) ───
    "assistant_proactive_enabled": False,   # OFF until the user trusts it
    "assistant_proactive_interval": 1800.0,
    # propose_only = never auto-execute (default, decision #8);
    # auto_safe = auto-run auto-class kinds in assistant_auto_safe_kinds
    "assistant_autonomy": "propose_only",
    "assistant_auto_safe_kinds": [],        # decision #8: everything via panel
    "assistant_quiet_hours": [22, 8],       # [start_h, end_h] — no nudges
    "assistant_model": "",                  # "" => active explain provider
    # work threads
    "assistant_thread_poll_interval": 60.0,
    "assistant_thread_stale_hours": 6,
    "assistant_nudge_max_per_cycle": 1,     # at most N resume nudges per cycle
    "assistant_nudge_cooldown_hours": 12,
    "assistant_thread_log_max": 5000,
    "assistant_proposal_max": 200,
    # assistant hotkeys (single HotkeyManager — rebind only, never new listener)
    "hotkey_open_inbox": "<cmd>+<shift>+i",
    "hotkey_capture_task": "<cmd>+<shift>+t",
}


# Old default values superseded by later versions. save() writes every key to
# disk, so an untouched default would otherwise be pinned forever; if the
# on-disk value still equals a stale default the user never customized it —
# drop it and let the current default apply. Customized values are never touched.
_SUPERSEDED_DEFAULTS = {
    # 창 가독성(사용자 피드백): 0.5는 옛 glass_window_tint_alpha 기본값이 새 키로
    # 새어든 것 — 사용자가 직접 고른 값이 아니면 0.9(불투명) 기본으로 끌어올린다.
    "window_tint_alpha": (0.5,),
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
        # M3-era 번역-지원 변형 ("긴 글이면 핵심 위주로" 추가 + 3~6→3~5 조정 전)
        # — M11 언어 전환 검증에서 라이브 config에 박혀 있던 채로 발견됨
        "너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트가 한국어가 아니면"
        "(영어/중국어/일본어 등) 먼저 '번역:'으로 시작하는 자연스러운 한국어 "
        "번역을 제시하고, 그다음 핵심을 3~6문장으로 설명해. 전문용어는 짧게 "
        "풀어줘. 군더더기 금지.",
        # M11 기본값 — "비서처럼 답하라 + 번역은 한 번" 문장 추가 전 (이 변경)
        "너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트가 한국어가 아니면"
        "(영어/중국어/일본어 등) 먼저 '번역:'으로 시작하는 자연스러운 한국어 "
        "번역을 제시하고(긴 글이면 핵심 위주로), 그다음 핵심을 3~5문장으로 "
        "설명해. 전문용어는 짧게 풀어줘. 군더더기 금지.",
    ),
    "system_prompt_image": (
        "너는 한국어로 답하는 간결한 해설가다. 이미지의 핵심 내용을 설명하고, "
        "표/코드/도식이면 의미를 풀어줘. 3~6문장.",
        # M11 기본값 — 같은 문장 추가 전 (이 변경)
        "너는 한국어로 답하는 간결한 해설가다. 이미지 속 텍스트가 한국어가 "
        "아니면 먼저 '번역:'으로 시작하는 한국어 번역을 제시한 뒤 설명해. "
        "이미지의 핵심 내용을 설명하고, 표/코드/도식이면 의미를 풀어줘. 3~6문장.",
    ),
}

# M11: prompt keys resolved per language at get() time. An on-disk value equal
# to ANY language's shipped default was never customized — dropped at load
# (every pre-M11 config has the Korean defaults pinned, since save() writes
# everything) and scrubbed again at save() so a settings save that writes the
# fields back verbatim can't re-pin them.
_LANG_KEYS = ("system_prompt_text", "system_prompt_image",
              "user_prompt_image", "detail_levels",
              # M14 assistant prompts (resolved per language at get() time)
              "assistant_propose_system", "assistant_digest_user",
              "assistant_resume_system", "assistant_resume_user")


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
            for key in _LANG_KEYS:
                if key in on_disk and on_disk[key] in i18n.all_prompt_defaults(key):
                    del on_disk[key]  # shipped default of some language, not custom
            # Grandfather pre-M13 configs: a config that already exists on disk
            # belongs to a set-up user — never show them onboarding.
            on_disk.setdefault("onboarded", True)
            migrated = _migrate_providers(on_disk)
            self._data = {**DEFAULTS, **on_disk}
            if migrated:
                self.save()
        else:
            self.save()

    def save(self):
        for key in _LANG_KEYS:  # anti-pinning scrub (see _LANG_KEYS comment)
            if key in self._data and self._data[key] in i18n.all_prompt_defaults(key):
                del self._data[key]
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self, key):
        if key not in self._data and key in _LANG_KEYS:
            return i18n.prompt_default(
                key, str(self._data.get("language", "ko"))
            )
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

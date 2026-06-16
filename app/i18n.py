"""i18n — UI strings + per-language prompt defaults (M11).

Pure data, stdlib-only, NO AppKit imports: cli/configure.py imports this from
any python3, same constraint as config.py / keychain.py.

- `t(key)` returns the current-language string (ko is the source of truth and
  the fallback). Parameterized strings use str.format named placeholders:
  `t("panel.thinking").format(n=count)`.
- `PROMPT_DEFAULTS[lang]` holds the language-resolved config defaults for
  system_prompt_text / system_prompt_image / user_prompt_image /
  detail_levels. ConfigStore.get() falls back here when the key is absent
  from config.json (i.e. the user never customized it); ConfigStore.save()
  scrubs values equal to ANY language's default so they never get pinned.
- The ko entries are byte-identical to the pre-M11 hardcoded literals — the
  equality checks above and zero-regression for existing users depend on it.
"""

LANGUAGES = {  # ordered: installer menu + settings popup order
    "ko": "한국어",
    "en": "English",
    "zh": "简体中文",
    "ja": "日本語",
    "fr": "Français",
    "de": "Deutsch",
}

_lang = "ko"


def set_language(code):
    global _lang
    code = str(code)
    if code not in LANGUAGES:
        code = "ko"
    _lang = code
    print(f"i18n: language={code}", flush=True)


def current_language():
    return _lang


def t(key):
    value = STRINGS.get(_lang, {}).get(key)
    if value is not None:
        return value
    # Fall back to Korean, then to the key itself — a missing string must never
    # raise (an NSException from a UI build crashes the whole app).
    return STRINGS["ko"].get(key, key)


def prompt_default(key, lang):
    table = PROMPT_DEFAULTS.get(str(lang), PROMPT_DEFAULTS["ko"])
    return table[key]


def all_prompt_defaults(key):
    return [table[key] for table in PROMPT_DEFAULTS.values()]


STRINGS = {
    "ko": {
        # menubar
        "menubar.server_unknown": "서버: 확인 중…",
        "menubar.server_ok": "서버: 정상",
        "menubar.server_loading": "서버: 모델 로딩 중…",
        "menubar.server_down": "서버: 연결 안 됨",
        "menubar.history": "History…",
        "menubar.settings": "Settings…",
        "menubar.quit": "Quit Macsist",
        # errors (explain_controller)
        "errors.no_accessibility": (
            "손쉬운 사용 권한이 필요합니다 — 방금 연 시스템 설정 창에서 이 앱"
            "(개발 중엔 터미널)을 허용하세요."
        ),
        "errors.no_selection": "선택된 텍스트가 없습니다.",
        "errors.no_screen_recording": (
            "화면 기록 권한이 필요합니다 — 방금 연 시스템 설정 창에서 허용한 뒤 "
            "앱을 재실행하세요."
        ),
        "errors.vision_hint": (
            " (이미지 미지원 모델일 수 있습니다 — Settings에서 Vision model을 "
            "확인하세요.)"
        ),
        "errors.no_content": "모델이 응답 내용을 내지 않았습니다.",
        "errors.no_content_thinking": (
            " 사고(thinking)에 {n}자를 쓰고 끝났습니다 — max_tokens를 늘려보세요."
        ),
        "errors.no_content_check": " 서버/모델 설정을 확인하세요.",
        "errors.empty_prev_response": "(이전 요청이 응답 없이 끝났습니다.)",
        # errors (llm_client)
        "errors.connect_failed": "{pname} 연결 실패 ({base_url}) — 서버/네트워크를 확인하세요.",
        "errors.timeout": "{pname} 응답 시간 초과 ({base_url}) — 서버 상태를 확인하세요.",
        "errors.comm_error": "{pname} 통신 오류: {exc}",
        "errors.model_loading": "{pname}: 모델 로딩 중입니다 — 잠시 후 다시 시도하세요.",
        "errors.auth_failed": "{pname} 인증 실패 (HTTP {status}) — API 키를 확인하세요.",
        "errors.http_error": "{pname} 오류 (HTTP {status})",
        "errors.bad_sse": "LLM 서버가 잘못된 SSE 형식을 보냈습니다.",
        # result panel
        "panel.followup_placeholder": "이어서 질문…",
        "panel.thinking": "생각 중… ({n}자)",
        # onboarding (M13 — first run of a downloaded .app)
        "onboard.title": "Macsist에 오신 걸 환영합니다",
        "onboard.body": "Macsist는 연결할 모델이 필요합니다. 어떻게 사용하시겠어요?",
        "onboard.external": "외부 API 사용",
        "onboard.local": "로컬 모델 실행",
        "onboard.later": "나중에",
        "onboard.local_title": "로컬 모델 설정",
        "onboard.local_body": (
            "로컬 모델은 Macsist 자체 서버로 동작합니다. 프로젝트에서 설치하세요:\n\n"
            "  git clone https://github.com/junidude/macsist.git\n"
            "  cd macsist && ./install.sh\n\n"
            "전체 안내: https://github.com/junidude/macsist"
        ),
        # history window
        "history.mode_text": "텍스트",
        "history.mode_region": "화면",
        "history.mode_followup": "추가질문",
        "history.transcript_q": "질문:",
        "history.transcript_a": "응답:",
        "history.nav_history": "기록",
        "history.nav_settings": "설정",
        "history.nav_assistant": "비서",
        "menubar.assistant": "비서",
        "menubar.assistant_tasks": "작업 보기…",
        "assistant.empty": "표시할 작업이 없습니다",
        "assistant.approve": "승인",
        "assistant.skip": "건너뛰기",
        "assistant.snooze": "나중에",
        "menubar.assistant_inbox": "받은 작업함",
        "assistant.threads_title": "할 일",
        "assistant.help_line": "비서가 제안 → 받은 작업함에서 승인 → 할 일로. '할 일'은 어디까지 했는지 기억합니다.",
        "assistant.tasks_title": "칸반 작업",
        "assistant.resume": "이어서",
        "assistant.no_threads": "할 일이 없어요 — 아래 입력창에 적고 '할 일 추가'를 누르세요",
        "assistant.input_placeholder": "할 일이나 메모 입력…",
        "assistant.new_thread": "할 일 추가",
        "assistant.propose": "제안",
        "assistant.scan": "스캔",
        "assistant.answer_btn": "답변",
        "assistant.inbox_empty": "받은 작업함이 비어 있습니다",
        "assistant.hermes_on": "Hermes 칸반 연결됨",
        "assistant.hermes_off": "Hermes 미연결",
        "assistant.local_only": "로컬 전용 비서 — 외부 에이전트 미연결 (Settings에서 백엔드 선택)",
        "assistant.gw_on": "게이트웨이 켜짐",
        "assistant.gw_off": "게이트웨이 꺼짐",
        "settings.section_assistant": "비서",
        "settings.assistant_backend_title": "비서 백엔드",
        "settings.assistant_backend_desc": "할 일을 맡길 외부 에이전트 (없으면 로컬 전용)",
        "settings.route_title": "답변 라우팅",
        "settings.route_desc": "쉬운 건 로컬 LLM, 어려운 건 Hermes 에이전트",
        "settings.route_auto": "자동 (어려우면 Hermes)",
        "settings.route_local": "항상 로컬",
        "settings.route_hermes": "항상 Hermes",
        "settings.backend_auto": "자동 (Hermes 감지)",
        "settings.backend_local": "로컬 전용",
        "settings.backend_hermes": "Hermes",
        "settings.assistant_proactive_title": "능동 제안",
        "settings.assistant_proactive_desc": "멈춘 작업을 스스로 찾아 먼저 제안합니다",
        "settings.assistant_autonomy_title": "신뢰 다이얼",
        "settings.assistant_autonomy_desc": "제안만 받을지, 안전한 작업은 자동 실행할지",
        "settings.autonomy_propose": "제안만 (확인 후 실행)",
        "settings.autonomy_auto": "안전한 건 자동 실행",
        "settings.assistant_interval_title": "제안 주기 (초)",
        "settings.assistant_interval_desc": "능동 제안을 점검하는 간격",
        "settings.section_window": "창 모양",
        "settings.window_glass_title": "창 유리 효과",
        "settings.window_glass_desc": "끄면 배경이 불투명해져 글이 더 잘 보입니다",
        "settings.window_opacity_title": "배경 불투명도",
        "settings.window_opacity_desc": "0=완전 투명 … 1=불투명 (가독성)",
        "history.search_placeholder": "검색 (질문/응답)",
        "history.save_master": "기록 저장",
        "history.save_images": "이미지 저장",
        "history.save_text": "텍스트 저장",
        "history.floating": "항상 위",
        "history.copy": "복사",
        "history.reask": "다시 질문",
        "history.empty_question": "(빈 질문)",
        "history.turns": "{n}턴",
        "history.empty": "기록이 없습니다.",
        "history.select_session": "세션을 선택하면 대화가 표시됩니다.",
        # settings — sections
        "settings.section_general": "일반",
        "settings.section_connection": "연결",
        "settings.section_response": "응답",
        "settings.section_hotkeys": "단축키",
        "settings.section_appearance": "모양",
        "settings.section_advanced": "고급",
        # settings — general
        "settings.language_title": "언어",
        "settings.language_desc": "UI와 답변 언어 — 저장 시 즉시 적용",
        # settings — connection
        "settings.active_provider_title": "활성 프로바이더",
        "settings.active_provider_desc": "요청에 사용할 엔드포인트 — 아래 필드로 편집, 저장 시 적용",
        "settings.manage_title": "프로바이더 관리",
        "settings.manage_desc": "추가는 OpenRouter 템플릿으로 — 삭제·추가 모두 저장 시 적용",
        "settings.add": "추가",
        "settings.delete": "삭제",
        "settings.name_label": "이름",
        "settings.name_placeholder": "프로바이더 표시 이름",
        "settings.url_label": "서버 주소",
        "settings.url_placeholder": "OpenAI 호환 엔드포인트 (예: https://openrouter.ai/api)",
        "settings.api_key_title": "API 키",
        "settings.local_title": "로컬 서버",
        "settings.local_desc": "켜면 /health 폴링 + chat_template_kwargs 전송",
        "settings.models_title": "모델 목록",
        "settings.models_desc": "서버 주소에서 /v1/models 조회해 자동완성 갱신",
        "settings.refresh": "새로고침",
        "settings.model_explain_title": "설명 모델",
        "settings.model_explain_desc": "텍스트 설명에 사용",
        "settings.model_vision_title": "비전 모델",
        "settings.model_vision_desc": "화면 캡처 설명에 사용 (멀티모달 모델 필요)",
        "settings.new_provider_name": "새 프로바이더",
        # settings — key status
        "settings.key_new": "새 키 입력됨 — 저장 시 Keychain에 보관",
        "settings.key_env": "환경변수 참조 ({ref})",
        "settings.key_stored": "키 저장됨 (Keychain) — 비워 두면 유지",
        "settings.key_none": "키 없음 — 입력하면 Keychain에 저장 (로컬 서버는 불필요)",
        # settings — provider status messages
        "settings.provider_added": "프로바이더 추가됨 — 저장 시 적용",
        "settings.provider_last": "⚠ 마지막 프로바이더는 삭제할 수 없습니다.",
        "settings.provider_delete_staged": "'{name}' 삭제 예약 — 저장 시 적용",
        # settings — response
        "settings.detail_title": "상세도",
        "settings.detail_desc": "답변 길이/깊이 프리셋",
        # settings — hotkeys
        "settings.hk_text_title": "텍스트 설명",
        "settings.hk_text_desc": "선택한 텍스트를 설명",
        "settings.hk_region_title": "영역 설명",
        "settings.hk_region_desc": "화면 영역을 캡처해 설명",
        "settings.hk_history_title": "기록 창",
        "settings.hk_history_desc": "History/Settings 창 토글",
        "settings.record_prompt": "단축키를 누르세요… (Esc 취소)",
        "settings.record_need_mod": "⌘/⌥/⌃/⇧ 와 함께 눌러주세요",
        # settings — appearance
        "settings.font_title": "패널 폰트 크기",
        "settings.font_desc": "결과 패널 본문/입력 글자 크기 (pt)",
        "settings.width_title": "패널 너비",
        "settings.width_desc": "결과 패널 가로 크기 (pt)",
        "settings.height_title": "패널 최대 높이",
        "settings.height_desc": "내용에 따라 이 높이까지 자라고, 그 뒤로는 스크롤",
        "settings.glass_title": "Glass 스타일",
        "settings.glass_desc": "패널/창 유리 효과 — Frosted가 가독성이 좋습니다",
        "settings.glass_regular": "Frosted (기본)",
        "settings.glass_clear": "투명 (Clear)",
        # settings — advanced
        "settings.prompt_text_label": "System prompt (텍스트)",
        "settings.prompt_image_label": "System prompt (이미지)",
        "settings.img_prompt_title": "이미지 질문 프롬프트",
        "settings.img_prompt_desc": "화면 캡처와 함께 보내는 사용자 메시지",
        "settings.temp_title": "Temperature",
        "settings.temp_desc": "샘플링 온도 (0~2)",
        "settings.maxtok_title": "Max tokens",
        "settings.maxtok_desc": "응답 길이 상한 (상세도 프리셋이 우선)",
        "settings.followup_title": "Follow-up 턴 수",
        "settings.followup_desc": "추가 질문 대화 깊이 (오래된 쌍부터 삭제)",
        "settings.kwargs_title": "Template kwargs",
        "settings.kwargs_desc": 'JSON — 로컬 서버 전용 (예: {"enable_thinking": false})',
        "settings.reset_title": "기본값 복원",
        "settings.reset_desc": "고급 필드를 출하 기본값으로 (저장 시 적용)",
        "settings.reset_btn": "복원",
        "settings.save_btn": "저장",
        "settings.reset_done": "기본값 복원됨 — 저장으로 적용",
        "settings.saved": "저장됨 ✓",
        # settings — validation
        "settings.v_font_num": "패널 폰트 크기는 숫자여야 합니다.",
        "settings.v_font_range": "패널 폰트 크기는 8~40 사이여야 합니다.",
        "settings.v_size_num": "패널 크기는 숫자여야 합니다.",
        "settings.v_size_small": "패널 크기가 너무 작습니다 (너비 200+, 높이 150+).",
        "settings.v_prompt_empty": "System prompt가 비어 있습니다.",
        "settings.v_img_prompt_empty": "이미지 질문 프롬프트가 비어 있습니다.",
        "settings.v_temp": "Temperature는 숫자여야 합니다.",
        "settings.v_maxtok": "Max tokens는 정수여야 합니다.",
        "settings.v_followup": "Follow-up 턴 수는 정수여야 합니다.",
        "settings.v_kwargs_json": 'Template kwargs는 JSON이어야 합니다 (예: {"enable_thinking": false})',
        "settings.v_kwargs_obj": "Template kwargs는 JSON 객체여야 합니다.",
        "settings.v_pname_empty": "프로바이더 이름이 비어 있습니다.",
        "settings.v_pname_dup": "프로바이더 이름이 중복됩니다.",
        "settings.v_url": "'{name}' 서버 주소는 http(s)://로 시작해야 합니다.",
        "settings.v_explain_empty": "활성 프로바이더의 설명 모델이 비어 있습니다.",
    },
    "en": {
        "menubar.server_unknown": "Server: checking…",
        "menubar.server_ok": "Server: OK",
        "menubar.server_loading": "Server: loading model…",
        "menubar.server_down": "Server: unreachable",
        "menubar.history": "History…",
        "menubar.settings": "Settings…",
        "menubar.quit": "Quit Macsist",
        "errors.no_accessibility": (
            "Accessibility permission is required — allow this app (the "
            "terminal during development) in the System Settings pane that "
            "just opened."
        ),
        "errors.no_selection": "No text is selected.",
        "errors.no_screen_recording": (
            "Screen Recording permission is required — allow it in the System "
            "Settings pane that just opened, then restart the app."
        ),
        "errors.vision_hint": (
            " (The model may not support images — check the Vision model in "
            "Settings.)"
        ),
        "errors.no_content": "The model produced no response content.",
        "errors.no_content_thinking": (
            " It spent {n} characters thinking and stopped — try raising "
            "max_tokens."
        ),
        "errors.no_content_check": " Check the server/model settings.",
        "errors.empty_prev_response": "(The previous request ended without a response.)",
        "errors.connect_failed": "{pname} connection failed ({base_url}) — check the server/network.",
        "errors.timeout": "{pname} timed out ({base_url}) — check the server status.",
        "errors.comm_error": "{pname} communication error: {exc}",
        "errors.model_loading": "{pname}: the model is loading — try again shortly.",
        "errors.auth_failed": "{pname} authentication failed (HTTP {status}) — check the API key.",
        "errors.http_error": "{pname} error (HTTP {status})",
        "errors.bad_sse": "The LLM server sent malformed SSE.",
        "panel.followup_placeholder": "Ask a follow-up…",
        "panel.thinking": "Thinking… ({n} chars)",
        "onboard.title": "Welcome to Macsist",
        "onboard.body": "Macsist needs a model to connect to. How would you like to run it?",
        "onboard.external": "Use an external API",
        "onboard.local": "Run a local model",
        "onboard.later": "Later",
        "onboard.local_title": "Set up a local model",
        "onboard.local_body": (
            "A local model runs through Macsist's own server. Install it from "
            "the project:\n\n"
            "  git clone https://github.com/junidude/macsist.git\n"
            "  cd macsist && ./install.sh\n\n"
            "Full guide: https://github.com/junidude/macsist"
        ),
        "history.mode_text": "Text",
        "history.mode_region": "Screen",
        "history.mode_followup": "Follow-up",
        "history.transcript_q": "Q:",
        "history.transcript_a": "A:",
        "history.nav_history": "History",
        "history.nav_settings": "Settings",
        "history.nav_assistant": "Assistant",
        "menubar.assistant": "Assistant",
        "menubar.assistant_tasks": "View Tasks…",
        "assistant.empty": "No tasks to show",
        "assistant.approve": "Approve",
        "assistant.skip": "Skip",
        "assistant.snooze": "Snooze",
        "menubar.assistant_inbox": "Inbox",
        "assistant.threads_title": "To-dos",
        "assistant.help_line": "Assistant proposes → approve in Inbox → becomes a To-do. To-dos remember where you left off.",
        "assistant.tasks_title": "Kanban tasks",
        "assistant.resume": "Resume",
        "assistant.no_threads": "No to-dos yet — type below and press 'Add to-do'",
        "assistant.input_placeholder": "Enter a task or note…",
        "assistant.new_thread": "Add to-do",
        "assistant.propose": "Propose",
        "assistant.scan": "Scan",
        "assistant.answer_btn": "Answer",
        "assistant.inbox_empty": "Inbox is empty",
        "assistant.hermes_on": "Hermes kanban connected",
        "assistant.hermes_off": "Hermes not connected",
        "assistant.local_only": "Local-only assistant — no external agent (pick a backend in Settings)",
        "assistant.gw_on": "gateway on",
        "assistant.gw_off": "gateway off",
        "settings.section_assistant": "Assistant",
        "settings.assistant_backend_title": "Assistant backend",
        "settings.assistant_backend_desc": "External agent for tasks (none = local-only)",
        "settings.route_title": "Answer routing",
        "settings.route_desc": "Easy → local LLM, hard → Hermes agent",
        "settings.route_auto": "Auto (Hermes if hard)",
        "settings.route_local": "Always local",
        "settings.route_hermes": "Always Hermes",
        "settings.backend_auto": "Auto (detect Hermes)",
        "settings.backend_local": "Local only",
        "settings.backend_hermes": "Hermes",
        "settings.assistant_proactive_title": "Proactive suggestions",
        "settings.assistant_proactive_desc": "Find stalled work and suggest it first",
        "settings.assistant_autonomy_title": "Trust dial",
        "settings.assistant_autonomy_desc": "Suggest only, or auto-run safe actions",
        "settings.autonomy_propose": "Suggest only (run after confirm)",
        "settings.autonomy_auto": "Auto-run safe actions",
        "settings.assistant_interval_title": "Suggestion interval (s)",
        "settings.assistant_interval_desc": "How often to check for suggestions",
        "settings.section_window": "Window appearance",
        "settings.window_glass_title": "Window glass effect",
        "settings.window_glass_desc": "Turn off for an opaque, more readable background",
        "settings.window_opacity_title": "Background opacity",
        "settings.window_opacity_desc": "0 = clear … 1 = opaque (readability)",
        "history.search_placeholder": "Search (question/answer)",
        "history.save_master": "Save history",
        "history.save_images": "Save images",
        "history.save_text": "Save text",
        "history.floating": "Always on top",
        "history.copy": "Copy",
        "history.reask": "Ask again",
        "history.empty_question": "(empty question)",
        "history.turns": "{n} turns",
        "history.empty": "No history yet.",
        "history.select_session": "Select a session to view the conversation.",
        "settings.section_general": "General",
        "settings.section_connection": "Connection",
        "settings.section_response": "Response",
        "settings.section_hotkeys": "Hotkeys",
        "settings.section_appearance": "Appearance",
        "settings.section_advanced": "Advanced",
        "settings.language_title": "Language",
        "settings.language_desc": "UI and answer language — applies on save",
        "settings.active_provider_title": "Active provider",
        "settings.active_provider_desc": "Endpoint used for requests — edit below, applies on save",
        "settings.manage_title": "Manage providers",
        "settings.manage_desc": "Add uses the OpenRouter template — add/delete apply on save",
        "settings.add": "Add",
        "settings.delete": "Delete",
        "settings.name_label": "Name",
        "settings.name_placeholder": "Provider display name",
        "settings.url_label": "Server URL",
        "settings.url_placeholder": "OpenAI-compatible endpoint (e.g. https://openrouter.ai/api)",
        "settings.api_key_title": "API key",
        "settings.local_title": "Local server",
        "settings.local_desc": "Enables /health polling + chat_template_kwargs",
        "settings.models_title": "Model list",
        "settings.models_desc": "Fetches /v1/models from the server URL for autocompletion",
        "settings.refresh": "Refresh",
        "settings.model_explain_title": "Explain model",
        "settings.model_explain_desc": "Used for text explanations",
        "settings.model_vision_title": "Vision model",
        "settings.model_vision_desc": "Used for screen captures (needs a multimodal model)",
        "settings.new_provider_name": "New provider",
        "settings.key_new": "New key entered — stored in Keychain on save",
        "settings.key_env": "Environment variable reference ({ref})",
        "settings.key_stored": "Key stored (Keychain) — leave empty to keep it",
        "settings.key_none": "No key — enter one to store it in Keychain (not needed for the local server)",
        "settings.provider_added": "Provider added — applies on save",
        "settings.provider_last": "⚠ The last provider cannot be deleted.",
        "settings.provider_delete_staged": "'{name}' marked for deletion — applies on save",
        "settings.detail_title": "Detail level",
        "settings.detail_desc": "Answer length/depth preset",
        "settings.hk_text_title": "Explain text",
        "settings.hk_text_desc": "Explain the selected text",
        "settings.hk_region_title": "Explain region",
        "settings.hk_region_desc": "Capture and explain a screen region",
        "settings.hk_history_title": "History window",
        "settings.hk_history_desc": "Toggle the History/Settings window",
        "settings.record_prompt": "Press a shortcut… (Esc to cancel)",
        "settings.record_need_mod": "Include ⌘/⌥/⌃/⇧ in the shortcut",
        "settings.font_title": "Panel font size",
        "settings.font_desc": "Result panel body/input text size (pt)",
        "settings.width_title": "Panel width",
        "settings.width_desc": "Result panel width (pt)",
        "settings.height_title": "Panel max height",
        "settings.height_desc": "Grows with content up to this height, then scrolls",
        "settings.glass_title": "Glass style",
        "settings.glass_desc": "Panel/window glass effect — Frosted reads best",
        "settings.glass_regular": "Frosted (default)",
        "settings.glass_clear": "Transparent (Clear)",
        "settings.prompt_text_label": "System prompt (text)",
        "settings.prompt_image_label": "System prompt (image)",
        "settings.img_prompt_title": "Image question prompt",
        "settings.img_prompt_desc": "User message sent along with screen captures",
        "settings.temp_title": "Temperature",
        "settings.temp_desc": "Sampling temperature (0–2)",
        "settings.maxtok_title": "Max tokens",
        "settings.maxtok_desc": "Response length cap (detail preset takes precedence)",
        "settings.followup_title": "Follow-up turns",
        "settings.followup_desc": "Follow-up conversation depth (oldest pairs dropped first)",
        "settings.kwargs_title": "Template kwargs",
        "settings.kwargs_desc": 'JSON — local server only (e.g. {"enable_thinking": false})',
        "settings.reset_title": "Restore defaults",
        "settings.reset_desc": "Reset the advanced fields to shipped defaults (applies on save)",
        "settings.reset_btn": "Restore",
        "settings.save_btn": "Save",
        "settings.reset_done": "Defaults restored — save to apply",
        "settings.saved": "Saved ✓",
        "settings.v_font_num": "Panel font size must be a number.",
        "settings.v_font_range": "Panel font size must be between 8 and 40.",
        "settings.v_size_num": "Panel size must be numbers.",
        "settings.v_size_small": "Panel size is too small (width 200+, height 150+).",
        "settings.v_prompt_empty": "System prompt is empty.",
        "settings.v_img_prompt_empty": "Image question prompt is empty.",
        "settings.v_temp": "Temperature must be a number.",
        "settings.v_maxtok": "Max tokens must be an integer.",
        "settings.v_followup": "Follow-up turns must be an integer.",
        "settings.v_kwargs_json": 'Template kwargs must be JSON (e.g. {"enable_thinking": false})',
        "settings.v_kwargs_obj": "Template kwargs must be a JSON object.",
        "settings.v_pname_empty": "Provider name is empty.",
        "settings.v_pname_dup": "Provider names must be unique.",
        "settings.v_url": "'{name}' server URL must start with http(s)://.",
        "settings.v_explain_empty": "The active provider's explain model is empty.",
    },
    "zh": {
        "menubar.server_unknown": "服务器：检查中…",
        "menubar.server_ok": "服务器：正常",
        "menubar.server_loading": "服务器：正在加载模型…",
        "menubar.server_down": "服务器：无法连接",
        "menubar.history": "历史记录…",
        "menubar.settings": "设置…",
        "menubar.quit": "退出 Macsist",
        "errors.no_accessibility": "需要辅助功能权限 — 请在刚打开的系统设置面板中允许此应用（开发时为终端）。",
        "errors.no_selection": "没有选中的文本。",
        "errors.no_screen_recording": "需要屏幕录制权限 — 请在刚打开的系统设置面板中允许后重启应用。",
        "errors.vision_hint": "（模型可能不支持图像 — 请在设置中检查视觉模型。）",
        "errors.no_content": "模型没有输出回答内容。",
        "errors.no_content_thinking": " 思考(thinking)消耗了 {n} 字后结束 — 请尝试提高 max_tokens。",
        "errors.no_content_check": " 请检查服务器/模型设置。",
        "errors.empty_prev_response": "（上一个请求没有返回回答。）",
        "errors.connect_failed": "{pname} 连接失败（{base_url}）— 请检查服务器/网络。",
        "errors.timeout": "{pname} 响应超时（{base_url}）— 请检查服务器状态。",
        "errors.comm_error": "{pname} 通信错误：{exc}",
        "errors.model_loading": "{pname}：模型加载中 — 请稍后重试。",
        "errors.auth_failed": "{pname} 认证失败（HTTP {status}）— 请检查 API 密钥。",
        "errors.http_error": "{pname} 错误（HTTP {status}）",
        "errors.bad_sse": "LLM 服务器发送了无效的 SSE 格式。",
        "panel.followup_placeholder": "继续提问…",
        "panel.thinking": "思考中…（{n} 字）",
        "onboard.title": "欢迎使用 Macsist",
        "onboard.body": "Macsist 需要一个可连接的模型。你想如何运行它？",
        "onboard.external": "使用外部 API",
        "onboard.local": "运行本地模型",
        "onboard.later": "稍后",
        "onboard.local_title": "设置本地模型",
        "onboard.local_body": (
            "本地模型通过 Macsist 自带的服务器运行。从项目安装：\n\n"
            "  git clone https://github.com/junidude/macsist.git\n"
            "  cd macsist && ./install.sh\n\n"
            "完整指南：https://github.com/junidude/macsist"
        ),
        "history.mode_text": "文本",
        "history.mode_region": "屏幕",
        "history.mode_followup": "追问",
        "history.transcript_q": "问：",
        "history.transcript_a": "答：",
        "history.nav_history": "记录",
        "history.nav_settings": "设置",
        "history.nav_assistant": "助手",
        "menubar.assistant": "助手",
        "menubar.assistant_tasks": "查看任务…",
        "assistant.empty": "暂无任务",
        "assistant.approve": "批准",
        "assistant.skip": "跳过",
        "assistant.snooze": "稍后",
        "menubar.assistant_inbox": "收件箱",
        "assistant.threads_title": "待办",
        "assistant.help_line": "助手建议 → 在收件箱批准 → 成为待办。待办会记住你做到哪儿了。",
        "assistant.tasks_title": "看板任务",
        "assistant.resume": "继续",
        "assistant.no_threads": "暂无待办 — 在下方输入并点击「添加待办」",
        "assistant.input_placeholder": "输入任务或备忘…",
        "assistant.new_thread": "添加待办",
        "assistant.propose": "建议",
        "assistant.scan": "扫描",
        "assistant.answer_btn": "回答",
        "assistant.inbox_empty": "收件箱为空",
        "assistant.hermes_on": "Hermes 看板已连接",
        "assistant.hermes_off": "Hermes 未连接",
        "assistant.local_only": "仅本地助手 — 未连接外部代理（在设置中选择后端）",
        "assistant.gw_on": "网关开启",
        "assistant.gw_off": "网关关闭",
        "settings.section_assistant": "助手",
        "settings.assistant_backend_title": "助手后端",
        "settings.assistant_backend_desc": "用于任务的外部代理（无则仅本地）",
        "settings.route_title": "回答路由",
        "settings.route_desc": "简单→本地 LLM，复杂→Hermes 代理",
        "settings.route_auto": "自动（难则 Hermes）",
        "settings.route_local": "始终本地",
        "settings.route_hermes": "始终 Hermes",
        "settings.backend_auto": "自动（检测 Hermes）",
        "settings.backend_local": "仅本地",
        "settings.backend_hermes": "Hermes",
        "settings.assistant_proactive_title": "主动建议",
        "settings.assistant_proactive_desc": "自动发现停滞的工作并先行建议",
        "settings.assistant_autonomy_title": "信任档位",
        "settings.assistant_autonomy_desc": "仅建议，或自动执行安全操作",
        "settings.autonomy_propose": "仅建议（确认后执行）",
        "settings.autonomy_auto": "自动执行安全操作",
        "settings.assistant_interval_title": "建议间隔（秒）",
        "settings.assistant_interval_desc": "检查建议的频率",
        "settings.section_window": "窗口外观",
        "settings.window_glass_title": "窗口玻璃效果",
        "settings.window_glass_desc": "关闭后背景不透明，更易阅读",
        "settings.window_opacity_title": "背景不透明度",
        "settings.window_opacity_desc": "0=透明 … 1=不透明（可读性）",
        "history.search_placeholder": "搜索（问题/回答）",
        "history.save_master": "保存记录",
        "history.save_images": "保存图像",
        "history.save_text": "保存文本",
        "history.floating": "总在最前",
        "history.copy": "复制",
        "history.reask": "再次提问",
        "history.empty_question": "（空问题）",
        "history.turns": "{n} 轮",
        "history.empty": "暂无记录。",
        "history.select_session": "选择会话以查看对话。",
        "settings.section_general": "通用",
        "settings.section_connection": "连接",
        "settings.section_response": "回答",
        "settings.section_hotkeys": "快捷键",
        "settings.section_appearance": "外观",
        "settings.section_advanced": "高级",
        "settings.language_title": "语言",
        "settings.language_desc": "界面与回答语言 — 保存后立即生效",
        "settings.active_provider_title": "活动提供方",
        "settings.active_provider_desc": "请求使用的端点 — 在下方编辑，保存后生效",
        "settings.manage_title": "管理提供方",
        "settings.manage_desc": "添加使用 OpenRouter 模板 — 增删均在保存后生效",
        "settings.add": "添加",
        "settings.delete": "删除",
        "settings.name_label": "名称",
        "settings.name_placeholder": "提供方显示名称",
        "settings.url_label": "服务器地址",
        "settings.url_placeholder": "OpenAI 兼容端点（例：https://openrouter.ai/api）",
        "settings.api_key_title": "API 密钥",
        "settings.local_title": "本地服务器",
        "settings.local_desc": "开启 /health 轮询 + 发送 chat_template_kwargs",
        "settings.models_title": "模型列表",
        "settings.models_desc": "从服务器地址获取 /v1/models 用于自动补全",
        "settings.refresh": "刷新",
        "settings.model_explain_title": "解释模型",
        "settings.model_explain_desc": "用于文本解释",
        "settings.model_vision_title": "视觉模型",
        "settings.model_vision_desc": "用于屏幕截图解释（需要多模态模型）",
        "settings.new_provider_name": "新提供方",
        "settings.key_new": "已输入新密钥 — 保存时存入钥匙串",
        "settings.key_env": "环境变量引用（{ref}）",
        "settings.key_stored": "密钥已保存（钥匙串）— 留空则保持不变",
        "settings.key_none": "无密钥 — 输入后存入钥匙串（本地服务器无需）",
        "settings.provider_added": "已添加提供方 — 保存后生效",
        "settings.provider_last": "⚠ 无法删除最后一个提供方。",
        "settings.provider_delete_staged": "已预定删除 '{name}' — 保存后生效",
        "settings.detail_title": "详细程度",
        "settings.detail_desc": "回答长度/深度预设",
        "settings.hk_text_title": "解释文本",
        "settings.hk_text_desc": "解释选中的文本",
        "settings.hk_region_title": "解释区域",
        "settings.hk_region_desc": "截取并解释屏幕区域",
        "settings.hk_history_title": "记录窗口",
        "settings.hk_history_desc": "切换历史/设置窗口",
        "settings.record_prompt": "请按下快捷键…（Esc 取消）",
        "settings.record_need_mod": "请同时按下 ⌘/⌥/⌃/⇧",
        "settings.font_title": "面板字号",
        "settings.font_desc": "结果面板正文/输入字号（pt）",
        "settings.width_title": "面板宽度",
        "settings.width_desc": "结果面板宽度（pt）",
        "settings.height_title": "面板最大高度",
        "settings.height_desc": "随内容增长到此高度，之后滚动",
        "settings.glass_title": "玻璃样式",
        "settings.glass_desc": "面板/窗口玻璃效果 — Frosted 可读性最佳",
        "settings.glass_regular": "Frosted（默认）",
        "settings.glass_clear": "透明（Clear）",
        "settings.prompt_text_label": "System prompt（文本）",
        "settings.prompt_image_label": "System prompt（图像）",
        "settings.img_prompt_title": "图像提问提示词",
        "settings.img_prompt_desc": "与屏幕截图一起发送的用户消息",
        "settings.temp_title": "Temperature",
        "settings.temp_desc": "采样温度（0~2）",
        "settings.maxtok_title": "Max tokens",
        "settings.maxtok_desc": "回答长度上限（详细程度预设优先）",
        "settings.followup_title": "追问轮数",
        "settings.followup_desc": "追问对话深度（从最旧的问答对开始删除）",
        "settings.kwargs_title": "Template kwargs",
        "settings.kwargs_desc": 'JSON — 仅本地服务器（例：{"enable_thinking": false}）',
        "settings.reset_title": "恢复默认",
        "settings.reset_desc": "将高级字段恢复为出厂默认（保存后生效）",
        "settings.reset_btn": "恢复",
        "settings.save_btn": "保存",
        "settings.reset_done": "已恢复默认 — 保存后生效",
        "settings.saved": "已保存 ✓",
        "settings.v_font_num": "面板字号必须是数字。",
        "settings.v_font_range": "面板字号必须在 8~40 之间。",
        "settings.v_size_num": "面板尺寸必须是数字。",
        "settings.v_size_small": "面板尺寸太小（宽 200+，高 150+）。",
        "settings.v_prompt_empty": "System prompt 为空。",
        "settings.v_img_prompt_empty": "图像提问提示词为空。",
        "settings.v_temp": "Temperature 必须是数字。",
        "settings.v_maxtok": "Max tokens 必须是整数。",
        "settings.v_followup": "追问轮数必须是整数。",
        "settings.v_kwargs_json": 'Template kwargs 必须是 JSON（例：{"enable_thinking": false}）',
        "settings.v_kwargs_obj": "Template kwargs 必须是 JSON 对象。",
        "settings.v_pname_empty": "提供方名称为空。",
        "settings.v_pname_dup": "提供方名称重复。",
        "settings.v_url": "'{name}' 服务器地址必须以 http(s):// 开头。",
        "settings.v_explain_empty": "活动提供方的解释模型为空。",
    },
    "ja": {
        "menubar.server_unknown": "サーバー: 確認中…",
        "menubar.server_ok": "サーバー: 正常",
        "menubar.server_loading": "サーバー: モデル読み込み中…",
        "menubar.server_down": "サーバー: 接続不可",
        "menubar.history": "履歴…",
        "menubar.settings": "設定…",
        "menubar.quit": "Macsist を終了",
        "errors.no_accessibility": "アクセシビリティ権限が必要です — 開いたシステム設定でこのアプリ（開発中はターミナル）を許可してください。",
        "errors.no_selection": "選択されたテキストがありません。",
        "errors.no_screen_recording": "画面収録の権限が必要です — 開いたシステム設定で許可し、アプリを再起動してください。",
        "errors.vision_hint": "（画像非対応のモデルかもしれません — 設定で Vision model を確認してください。）",
        "errors.no_content": "モデルが応答内容を返しませんでした。",
        "errors.no_content_thinking": " 思考(thinking)に{n}文字を使って終了しました — max_tokens を増やしてみてください。",
        "errors.no_content_check": " サーバー/モデル設定を確認してください。",
        "errors.empty_prev_response": "（前回のリクエストは応答なしで終了しました。）",
        "errors.connect_failed": "{pname} 接続失敗（{base_url}）— サーバー/ネットワークを確認してください。",
        "errors.timeout": "{pname} 応答タイムアウト（{base_url}）— サーバー状態を確認してください。",
        "errors.comm_error": "{pname} 通信エラー: {exc}",
        "errors.model_loading": "{pname}: モデル読み込み中です — しばらくして再試行してください。",
        "errors.auth_failed": "{pname} 認証失敗（HTTP {status}）— API キーを確認してください。",
        "errors.http_error": "{pname} エラー（HTTP {status}）",
        "errors.bad_sse": "LLM サーバーが不正な SSE 形式を送信しました。",
        "panel.followup_placeholder": "続けて質問…",
        "panel.thinking": "思考中…（{n}文字）",
        "onboard.title": "Macsist へようこそ",
        "onboard.body": "Macsist には接続するモデルが必要です。どのように動かしますか？",
        "onboard.external": "外部 API を使う",
        "onboard.local": "ローカルモデルを動かす",
        "onboard.later": "あとで",
        "onboard.local_title": "ローカルモデルの設定",
        "onboard.local_body": (
            "ローカルモデルは Macsist 自身のサーバーで動作します。プロジェクトから"
            "インストールしてください：\n\n"
            "  git clone https://github.com/junidude/macsist.git\n"
            "  cd macsist && ./install.sh\n\n"
            "詳しい手順：https://github.com/junidude/macsist"
        ),
        "history.mode_text": "テキスト",
        "history.mode_region": "画面",
        "history.mode_followup": "追加質問",
        "history.transcript_q": "質問:",
        "history.transcript_a": "回答:",
        "history.nav_history": "履歴",
        "history.nav_settings": "設定",
        "history.nav_assistant": "アシスタント",
        "menubar.assistant": "アシスタント",
        "menubar.assistant_tasks": "タスクを表示…",
        "assistant.empty": "表示するタスクがありません",
        "assistant.approve": "承認",
        "assistant.skip": "スキップ",
        "assistant.snooze": "あとで",
        "menubar.assistant_inbox": "受信箱",
        "assistant.threads_title": "やること",
        "assistant.help_line": "アシスタントが提案 → 受信箱で承認 → やることに。やることは「どこまでやったか」を覚えます。",
        "assistant.tasks_title": "カンバン タスク",
        "assistant.resume": "再開",
        "assistant.no_threads": "やることがありません — 下に入力して「やること追加」",
        "assistant.input_placeholder": "タスクやメモを入力…",
        "assistant.new_thread": "やること追加",
        "assistant.propose": "提案",
        "assistant.scan": "スキャン",
        "assistant.answer_btn": "回答",
        "assistant.inbox_empty": "受信箱は空です",
        "assistant.hermes_on": "Hermes カンバン接続済み",
        "assistant.hermes_off": "Hermes 未接続",
        "assistant.local_only": "ローカル専用アシスタント — 外部エージェント未接続（設定で選択）",
        "assistant.gw_on": "ゲートウェイ ON",
        "assistant.gw_off": "ゲートウェイ OFF",
        "settings.section_assistant": "アシスタント",
        "settings.assistant_backend_title": "アシスタント バックエンド",
        "settings.assistant_backend_desc": "タスクを任せる外部エージェント（無ければローカル専用）",
        "settings.route_title": "回答ルーティング",
        "settings.route_desc": "簡単→ローカルLLM、難しい→Hermesエージェント",
        "settings.route_auto": "自動（難しければHermes）",
        "settings.route_local": "常にローカル",
        "settings.route_hermes": "常にHermes",
        "settings.backend_auto": "自動（Hermes 検出）",
        "settings.backend_local": "ローカル専用",
        "settings.backend_hermes": "Hermes",
        "settings.assistant_proactive_title": "能動的な提案",
        "settings.assistant_proactive_desc": "停滞した作業を見つけて先に提案します",
        "settings.assistant_autonomy_title": "信頼ダイヤル",
        "settings.assistant_autonomy_desc": "提案のみか、安全な操作は自動実行か",
        "settings.autonomy_propose": "提案のみ（確認後に実行）",
        "settings.autonomy_auto": "安全な操作は自動実行",
        "settings.assistant_interval_title": "提案の間隔（秒）",
        "settings.assistant_interval_desc": "提案を確認する頻度",
        "settings.section_window": "ウインドウの外観",
        "settings.window_glass_title": "ウインドウのガラス効果",
        "settings.window_glass_desc": "オフにすると背景が不透明になり読みやすくなります",
        "settings.window_opacity_title": "背景の不透明度",
        "settings.window_opacity_desc": "0=透明 … 1=不透明（可読性）",
        "history.search_placeholder": "検索（質問/回答）",
        "history.save_master": "履歴を保存",
        "history.save_images": "画像を保存",
        "history.save_text": "テキストを保存",
        "history.floating": "常に手前",
        "history.copy": "コピー",
        "history.reask": "もう一度質問",
        "history.empty_question": "（空の質問）",
        "history.turns": "{n}ターン",
        "history.empty": "履歴がありません。",
        "history.select_session": "セッションを選択すると会話が表示されます。",
        "settings.section_general": "一般",
        "settings.section_connection": "接続",
        "settings.section_response": "応答",
        "settings.section_hotkeys": "ショートカット",
        "settings.section_appearance": "外観",
        "settings.section_advanced": "詳細",
        "settings.language_title": "言語",
        "settings.language_desc": "UI と回答の言語 — 保存時に即適用",
        "settings.active_provider_title": "アクティブプロバイダー",
        "settings.active_provider_desc": "リクエストに使うエンドポイント — 下のフィールドで編集、保存時に適用",
        "settings.manage_title": "プロバイダー管理",
        "settings.manage_desc": "追加は OpenRouter テンプレート — 追加・削除とも保存時に適用",
        "settings.add": "追加",
        "settings.delete": "削除",
        "settings.name_label": "名前",
        "settings.name_placeholder": "プロバイダー表示名",
        "settings.url_label": "サーバーアドレス",
        "settings.url_placeholder": "OpenAI 互換エンドポイント（例: https://openrouter.ai/api）",
        "settings.api_key_title": "API キー",
        "settings.local_title": "ローカルサーバー",
        "settings.local_desc": "有効にすると /health ポーリング + chat_template_kwargs 送信",
        "settings.models_title": "モデル一覧",
        "settings.models_desc": "サーバーから /v1/models を取得して自動補完を更新",
        "settings.refresh": "更新",
        "settings.model_explain_title": "説明モデル",
        "settings.model_explain_desc": "テキスト説明に使用",
        "settings.model_vision_title": "ビジョンモデル",
        "settings.model_vision_desc": "画面キャプチャ説明に使用（マルチモーダルモデルが必要）",
        "settings.new_provider_name": "新規プロバイダー",
        "settings.key_new": "新しいキーを入力済み — 保存時にキーチェーンへ保管",
        "settings.key_env": "環境変数参照（{ref}）",
        "settings.key_stored": "キー保存済み（キーチェーン）— 空欄なら維持",
        "settings.key_none": "キーなし — 入力するとキーチェーンに保存（ローカルサーバーは不要）",
        "settings.provider_added": "プロバイダーを追加 — 保存時に適用",
        "settings.provider_last": "⚠ 最後のプロバイダーは削除できません。",
        "settings.provider_delete_staged": "'{name}' を削除予約 — 保存時に適用",
        "settings.detail_title": "詳しさ",
        "settings.detail_desc": "回答の長さ/深さプリセット",
        "settings.hk_text_title": "テキスト説明",
        "settings.hk_text_desc": "選択したテキストを説明",
        "settings.hk_region_title": "領域説明",
        "settings.hk_region_desc": "画面領域をキャプチャして説明",
        "settings.hk_history_title": "履歴ウィンドウ",
        "settings.hk_history_desc": "履歴/設定ウィンドウの切り替え",
        "settings.record_prompt": "ショートカットを押してください…（Esc でキャンセル）",
        "settings.record_need_mod": "⌘/⌥/⌃/⇧ と一緒に押してください",
        "settings.font_title": "パネルフォントサイズ",
        "settings.font_desc": "結果パネル本文/入力の文字サイズ（pt）",
        "settings.width_title": "パネル幅",
        "settings.width_desc": "結果パネルの横幅（pt）",
        "settings.height_title": "パネル最大高さ",
        "settings.height_desc": "内容に応じてこの高さまで拡大、その後はスクロール",
        "settings.glass_title": "ガラススタイル",
        "settings.glass_desc": "パネル/ウィンドウのガラス効果 — Frosted が読みやすい",
        "settings.glass_regular": "Frosted（デフォルト）",
        "settings.glass_clear": "透明（Clear）",
        "settings.prompt_text_label": "System prompt（テキスト）",
        "settings.prompt_image_label": "System prompt（画像）",
        "settings.img_prompt_title": "画像質問プロンプト",
        "settings.img_prompt_desc": "画面キャプチャと一緒に送るユーザーメッセージ",
        "settings.temp_title": "Temperature",
        "settings.temp_desc": "サンプリング温度（0~2）",
        "settings.maxtok_title": "Max tokens",
        "settings.maxtok_desc": "応答長の上限（詳しさプリセットが優先）",
        "settings.followup_title": "追加質問ターン数",
        "settings.followup_desc": "追加質問の会話の深さ（古いペアから削除）",
        "settings.kwargs_title": "Template kwargs",
        "settings.kwargs_desc": 'JSON — ローカルサーバー専用（例: {"enable_thinking": false}）',
        "settings.reset_title": "デフォルトに戻す",
        "settings.reset_desc": "詳細フィールドを出荷時のデフォルトに（保存時に適用）",
        "settings.reset_btn": "戻す",
        "settings.save_btn": "保存",
        "settings.reset_done": "デフォルトに戻しました — 保存で適用",
        "settings.saved": "保存しました ✓",
        "settings.v_font_num": "パネルフォントサイズは数字である必要があります。",
        "settings.v_font_range": "パネルフォントサイズは 8~40 の範囲にしてください。",
        "settings.v_size_num": "パネルサイズは数字である必要があります。",
        "settings.v_size_small": "パネルサイズが小さすぎます（幅 200+、高さ 150+）。",
        "settings.v_prompt_empty": "System prompt が空です。",
        "settings.v_img_prompt_empty": "画像質問プロンプトが空です。",
        "settings.v_temp": "Temperature は数字である必要があります。",
        "settings.v_maxtok": "Max tokens は整数である必要があります。",
        "settings.v_followup": "追加質問ターン数は整数である必要があります。",
        "settings.v_kwargs_json": 'Template kwargs は JSON である必要があります（例: {"enable_thinking": false}）',
        "settings.v_kwargs_obj": "Template kwargs は JSON オブジェクトである必要があります。",
        "settings.v_pname_empty": "プロバイダー名が空です。",
        "settings.v_pname_dup": "プロバイダー名が重複しています。",
        "settings.v_url": "'{name}' のサーバーアドレスは http(s):// で始まる必要があります。",
        "settings.v_explain_empty": "アクティブプロバイダーの説明モデルが空です。",
    },
    "fr": {
        "menubar.server_unknown": "Serveur : vérification…",
        "menubar.server_ok": "Serveur : OK",
        "menubar.server_loading": "Serveur : chargement du modèle…",
        "menubar.server_down": "Serveur : injoignable",
        "menubar.history": "Historique…",
        "menubar.settings": "Réglages…",
        "menubar.quit": "Quitter Macsist",
        "errors.no_accessibility": "Autorisation d'accessibilité requise — autorisez cette app (le terminal en développement) dans le panneau Réglages Système qui vient de s'ouvrir.",
        "errors.no_selection": "Aucun texte sélectionné.",
        "errors.no_screen_recording": "Autorisation d'enregistrement d'écran requise — autorisez-la dans le panneau qui vient de s'ouvrir, puis relancez l'app.",
        "errors.vision_hint": " (Le modèle ne gère peut-être pas les images — vérifiez le modèle Vision dans les Réglages.)",
        "errors.no_content": "Le modèle n'a produit aucun contenu de réponse.",
        "errors.no_content_thinking": " Il a consommé {n} caractères de réflexion avant de s'arrêter — augmentez max_tokens.",
        "errors.no_content_check": " Vérifiez les réglages serveur/modèle.",
        "errors.empty_prev_response": "(La requête précédente s'est terminée sans réponse.)",
        "errors.connect_failed": "{pname} : connexion échouée ({base_url}) — vérifiez le serveur/réseau.",
        "errors.timeout": "{pname} : délai dépassé ({base_url}) — vérifiez l'état du serveur.",
        "errors.comm_error": "{pname} : erreur de communication : {exc}",
        "errors.model_loading": "{pname} : le modèle se charge — réessayez dans un instant.",
        "errors.auth_failed": "{pname} : échec d'authentification (HTTP {status}) — vérifiez la clé API.",
        "errors.http_error": "{pname} : erreur (HTTP {status})",
        "errors.bad_sse": "Le serveur LLM a envoyé un flux SSE invalide.",
        "panel.followup_placeholder": "Poser une question de suivi…",
        "panel.thinking": "Réflexion… ({n} caractères)",
        "onboard.title": "Bienvenue dans Macsist",
        "onboard.body": "Macsist a besoin d'un modèle auquel se connecter. Comment voulez-vous l'exécuter ?",
        "onboard.external": "Utiliser une API externe",
        "onboard.local": "Exécuter un modèle local",
        "onboard.later": "Plus tard",
        "onboard.local_title": "Configurer un modèle local",
        "onboard.local_body": (
            "Un modèle local fonctionne via le serveur de Macsist. Installez-le "
            "depuis le projet :\n\n"
            "  git clone https://github.com/junidude/macsist.git\n"
            "  cd macsist && ./install.sh\n\n"
            "Guide complet : https://github.com/junidude/macsist"
        ),
        "history.mode_text": "Texte",
        "history.mode_region": "Écran",
        "history.mode_followup": "Suivi",
        "history.transcript_q": "Q :",
        "history.transcript_a": "R :",
        "history.nav_history": "Historique",
        "history.nav_settings": "Réglages",
        "history.nav_assistant": "Assistant",
        "menubar.assistant": "Assistant",
        "menubar.assistant_tasks": "Voir les tâches…",
        "assistant.empty": "Aucune tâche à afficher",
        "assistant.approve": "Approuver",
        "assistant.skip": "Ignorer",
        "assistant.snooze": "Plus tard",
        "menubar.assistant_inbox": "Boîte de réception",
        "assistant.threads_title": "À faire",
        "assistant.help_line": "L'assistant propose → approuvez dans la boîte → devient une tâche. Les tâches retiennent où vous en étiez.",
        "assistant.tasks_title": "Tâches Kanban",
        "assistant.resume": "Reprendre",
        "assistant.no_threads": "Aucune tâche — saisissez ci-dessous et cliquez « Ajouter »",
        "assistant.input_placeholder": "Saisir une tâche ou une note…",
        "assistant.new_thread": "Ajouter une tâche",
        "assistant.propose": "Proposer",
        "assistant.scan": "Analyser",
        "assistant.answer_btn": "Répondre",
        "assistant.inbox_empty": "Boîte de réception vide",
        "assistant.hermes_on": "Kanban Hermes connecté",
        "assistant.hermes_off": "Hermes non connecté",
        "assistant.local_only": "Assistant local — aucun agent externe (choisir un backend dans Réglages)",
        "assistant.gw_on": "passerelle activée",
        "assistant.gw_off": "passerelle désactivée",
        "settings.section_assistant": "Assistant",
        "settings.assistant_backend_title": "Backend de l'assistant",
        "settings.assistant_backend_desc": "Agent externe pour les tâches (aucun = local)",
        "settings.route_title": "Routage des réponses",
        "settings.route_desc": "Facile → LLM local, difficile → agent Hermes",
        "settings.route_auto": "Auto (Hermes si difficile)",
        "settings.route_local": "Toujours local",
        "settings.route_hermes": "Toujours Hermes",
        "settings.backend_auto": "Auto (détecter Hermes)",
        "settings.backend_local": "Local uniquement",
        "settings.backend_hermes": "Hermes",
        "settings.assistant_proactive_title": "Suggestions proactives",
        "settings.assistant_proactive_desc": "Trouve le travail en pause et le propose",
        "settings.assistant_autonomy_title": "Niveau de confiance",
        "settings.assistant_autonomy_desc": "Suggérer seulement, ou exécuter le sûr",
        "settings.autonomy_propose": "Suggérer (exécuter après confirmation)",
        "settings.autonomy_auto": "Exécuter automatiquement le sûr",
        "settings.assistant_interval_title": "Intervalle de suggestion (s)",
        "settings.assistant_interval_desc": "Fréquence de vérification des suggestions",
        "settings.section_window": "Apparence de la fenêtre",
        "settings.window_glass_title": "Effet verre de la fenêtre",
        "settings.window_glass_desc": "Désactivez pour un fond opaque, plus lisible",
        "settings.window_opacity_title": "Opacité du fond",
        "settings.window_opacity_desc": "0 = transparent … 1 = opaque (lisibilité)",
        "history.search_placeholder": "Rechercher (question/réponse)",
        "history.save_master": "Enregistrer l'historique",
        "history.save_images": "Enregistrer les images",
        "history.save_text": "Enregistrer le texte",
        "history.floating": "Toujours devant",
        "history.copy": "Copier",
        "history.reask": "Redemander",
        "history.empty_question": "(question vide)",
        "history.turns": "{n} tours",
        "history.empty": "Aucun historique.",
        "history.select_session": "Sélectionnez une session pour afficher la conversation.",
        "settings.section_general": "Général",
        "settings.section_connection": "Connexion",
        "settings.section_response": "Réponse",
        "settings.section_hotkeys": "Raccourcis",
        "settings.section_appearance": "Apparence",
        "settings.section_advanced": "Avancé",
        "settings.language_title": "Langue",
        "settings.language_desc": "Langue de l'interface et des réponses — appliquée à l'enregistrement",
        "settings.active_provider_title": "Fournisseur actif",
        "settings.active_provider_desc": "Point d'accès utilisé — modifiez ci-dessous, appliqué à l'enregistrement",
        "settings.manage_title": "Gérer les fournisseurs",
        "settings.manage_desc": "Ajout via le modèle OpenRouter — ajout/suppression appliqués à l'enregistrement",
        "settings.add": "Ajouter",
        "settings.delete": "Supprimer",
        "settings.name_label": "Nom",
        "settings.name_placeholder": "Nom affiché du fournisseur",
        "settings.url_label": "Adresse du serveur",
        "settings.url_placeholder": "Point d'accès compatible OpenAI (ex. https://openrouter.ai/api)",
        "settings.api_key_title": "Clé API",
        "settings.local_title": "Serveur local",
        "settings.local_desc": "Active le polling /health + l'envoi de chat_template_kwargs",
        "settings.models_title": "Liste des modèles",
        "settings.models_desc": "Récupère /v1/models depuis le serveur pour l'autocomplétion",
        "settings.refresh": "Actualiser",
        "settings.model_explain_title": "Modèle d'explication",
        "settings.model_explain_desc": "Utilisé pour les explications de texte",
        "settings.model_vision_title": "Modèle vision",
        "settings.model_vision_desc": "Utilisé pour les captures d'écran (modèle multimodal requis)",
        "settings.new_provider_name": "Nouveau fournisseur",
        "settings.key_new": "Nouvelle clé saisie — stockée dans le trousseau à l'enregistrement",
        "settings.key_env": "Référence de variable d'environnement ({ref})",
        "settings.key_stored": "Clé stockée (trousseau) — laisser vide pour la conserver",
        "settings.key_none": "Aucune clé — saisissez-en une pour la stocker (inutile pour le serveur local)",
        "settings.provider_added": "Fournisseur ajouté — appliqué à l'enregistrement",
        "settings.provider_last": "⚠ Impossible de supprimer le dernier fournisseur.",
        "settings.provider_delete_staged": "'{name}' marqué pour suppression — appliqué à l'enregistrement",
        "settings.detail_title": "Niveau de détail",
        "settings.detail_desc": "Préréglage de longueur/profondeur des réponses",
        "settings.hk_text_title": "Expliquer le texte",
        "settings.hk_text_desc": "Explique le texte sélectionné",
        "settings.hk_region_title": "Expliquer une zone",
        "settings.hk_region_desc": "Capture et explique une zone de l'écran",
        "settings.hk_history_title": "Fenêtre d'historique",
        "settings.hk_history_desc": "Affiche/masque la fenêtre Historique/Réglages",
        "settings.record_prompt": "Appuyez sur un raccourci… (Échap pour annuler)",
        "settings.record_need_mod": "Combinez avec ⌘/⌥/⌃/⇧",
        "settings.font_title": "Taille de police du panneau",
        "settings.font_desc": "Taille du texte du panneau de résultat (pt)",
        "settings.width_title": "Largeur du panneau",
        "settings.width_desc": "Largeur du panneau de résultat (pt)",
        "settings.height_title": "Hauteur max du panneau",
        "settings.height_desc": "S'agrandit jusqu'à cette hauteur, puis défile",
        "settings.glass_title": "Style de verre",
        "settings.glass_desc": "Effet de verre du panneau/de la fenêtre — Frosted est le plus lisible",
        "settings.glass_regular": "Frosted (défaut)",
        "settings.glass_clear": "Transparent (Clear)",
        "settings.prompt_text_label": "System prompt (texte)",
        "settings.prompt_image_label": "System prompt (image)",
        "settings.img_prompt_title": "Prompt de question d'image",
        "settings.img_prompt_desc": "Message utilisateur envoyé avec les captures d'écran",
        "settings.temp_title": "Temperature",
        "settings.temp_desc": "Température d'échantillonnage (0–2)",
        "settings.maxtok_title": "Max tokens",
        "settings.maxtok_desc": "Plafond de longueur de réponse (le préréglage de détail prime)",
        "settings.followup_title": "Tours de suivi",
        "settings.followup_desc": "Profondeur de la conversation de suivi (les paires les plus anciennes sont supprimées)",
        "settings.kwargs_title": "Template kwargs",
        "settings.kwargs_desc": 'JSON — serveur local uniquement (ex. {"enable_thinking": false})',
        "settings.reset_title": "Restaurer les défauts",
        "settings.reset_desc": "Réinitialise les champs avancés (appliqué à l'enregistrement)",
        "settings.reset_btn": "Restaurer",
        "settings.save_btn": "Enregistrer",
        "settings.reset_done": "Défauts restaurés — enregistrez pour appliquer",
        "settings.saved": "Enregistré ✓",
        "settings.v_font_num": "La taille de police doit être un nombre.",
        "settings.v_font_range": "La taille de police doit être entre 8 et 40.",
        "settings.v_size_num": "Les dimensions du panneau doivent être des nombres.",
        "settings.v_size_small": "Panneau trop petit (largeur 200+, hauteur 150+).",
        "settings.v_prompt_empty": "Le system prompt est vide.",
        "settings.v_img_prompt_empty": "Le prompt de question d'image est vide.",
        "settings.v_temp": "Temperature doit être un nombre.",
        "settings.v_maxtok": "Max tokens doit être un entier.",
        "settings.v_followup": "Les tours de suivi doivent être un entier.",
        "settings.v_kwargs_json": 'Template kwargs doit être du JSON (ex. {"enable_thinking": false})',
        "settings.v_kwargs_obj": "Template kwargs doit être un objet JSON.",
        "settings.v_pname_empty": "Le nom du fournisseur est vide.",
        "settings.v_pname_dup": "Les noms de fournisseurs doivent être uniques.",
        "settings.v_url": "L'adresse de '{name}' doit commencer par http(s)://.",
        "settings.v_explain_empty": "Le modèle d'explication du fournisseur actif est vide.",
    },
    "de": {
        "menubar.server_unknown": "Server: wird geprüft…",
        "menubar.server_ok": "Server: OK",
        "menubar.server_loading": "Server: Modell wird geladen…",
        "menubar.server_down": "Server: nicht erreichbar",
        "menubar.history": "Verlauf…",
        "menubar.settings": "Einstellungen…",
        "menubar.quit": "Macsist beenden",
        "errors.no_accessibility": "Bedienungshilfen-Berechtigung erforderlich — erlauben Sie diese App (in der Entwicklung: das Terminal) im soeben geöffneten Systemeinstellungs-Bereich.",
        "errors.no_selection": "Kein Text ausgewählt.",
        "errors.no_screen_recording": "Bildschirmaufnahme-Berechtigung erforderlich — im geöffneten Bereich erlauben und die App neu starten.",
        "errors.vision_hint": " (Das Modell unterstützt evtl. keine Bilder — prüfen Sie das Vision-Modell in den Einstellungen.)",
        "errors.no_content": "Das Modell hat keinen Antwortinhalt geliefert.",
        "errors.no_content_thinking": " Es hat {n} Zeichen mit Nachdenken verbraucht — erhöhen Sie max_tokens.",
        "errors.no_content_check": " Prüfen Sie die Server-/Modelleinstellungen.",
        "errors.empty_prev_response": "(Die vorherige Anfrage endete ohne Antwort.)",
        "errors.connect_failed": "{pname}: Verbindung fehlgeschlagen ({base_url}) — Server/Netzwerk prüfen.",
        "errors.timeout": "{pname}: Zeitüberschreitung ({base_url}) — Serverstatus prüfen.",
        "errors.comm_error": "{pname}: Kommunikationsfehler: {exc}",
        "errors.model_loading": "{pname}: Modell wird geladen — bitte gleich erneut versuchen.",
        "errors.auth_failed": "{pname}: Authentifizierung fehlgeschlagen (HTTP {status}) — API-Schlüssel prüfen.",
        "errors.http_error": "{pname}: Fehler (HTTP {status})",
        "errors.bad_sse": "Der LLM-Server hat ungültiges SSE gesendet.",
        "panel.followup_placeholder": "Nachfrage stellen…",
        "panel.thinking": "Denkt nach… ({n} Zeichen)",
        "onboard.title": "Willkommen bei Macsist",
        "onboard.body": "Macsist braucht ein Modell zum Verbinden. Wie möchten Sie es betreiben?",
        "onboard.external": "Externe API verwenden",
        "onboard.local": "Lokales Modell ausführen",
        "onboard.later": "Später",
        "onboard.local_title": "Lokales Modell einrichten",
        "onboard.local_body": (
            "Ein lokales Modell läuft über Macsists eigenen Server. Installieren "
            "Sie es aus dem Projekt:\n\n"
            "  git clone https://github.com/junidude/macsist.git\n"
            "  cd macsist && ./install.sh\n\n"
            "Vollständige Anleitung: https://github.com/junidude/macsist"
        ),
        "history.mode_text": "Text",
        "history.mode_region": "Bildschirm",
        "history.mode_followup": "Nachfrage",
        "history.transcript_q": "F:",
        "history.transcript_a": "A:",
        "history.nav_history": "Verlauf",
        "history.nav_settings": "Einstellungen",
        "history.nav_assistant": "Assistent",
        "menubar.assistant": "Assistent",
        "menubar.assistant_tasks": "Aufgaben anzeigen…",
        "assistant.empty": "Keine Aufgaben",
        "assistant.approve": "Genehmigen",
        "assistant.skip": "Überspringen",
        "assistant.snooze": "Später",
        "menubar.assistant_inbox": "Eingang",
        "assistant.threads_title": "To-dos",
        "assistant.help_line": "Assistent schlägt vor → im Eingang genehmigen → wird ein To-do. To-dos merken sich, wo du warst.",
        "assistant.tasks_title": "Kanban-Aufgaben",
        "assistant.resume": "Fortsetzen",
        "assistant.no_threads": "Noch keine To-dos — unten eingeben und „To-do hinzufügen“",
        "assistant.input_placeholder": "Aufgabe oder Notiz eingeben…",
        "assistant.new_thread": "To-do hinzufügen",
        "assistant.propose": "Vorschlagen",
        "assistant.scan": "Scannen",
        "assistant.answer_btn": "Antworten",
        "assistant.inbox_empty": "Eingang ist leer",
        "assistant.hermes_on": "Hermes-Kanban verbunden",
        "assistant.hermes_off": "Hermes nicht verbunden",
        "assistant.local_only": "Nur-lokaler Assistent — kein externer Agent (Backend in Einstellungen wählen)",
        "assistant.gw_on": "Gateway an",
        "assistant.gw_off": "Gateway aus",
        "settings.section_assistant": "Assistent",
        "settings.assistant_backend_title": "Assistent-Backend",
        "settings.assistant_backend_desc": "Externer Agent für Aufgaben (keiner = nur lokal)",
        "settings.route_title": "Antwort-Routing",
        "settings.route_desc": "Einfach → lokales LLM, schwer → Hermes-Agent",
        "settings.route_auto": "Auto (Hermes wenn schwer)",
        "settings.route_local": "Immer lokal",
        "settings.route_hermes": "Immer Hermes",
        "settings.backend_auto": "Auto (Hermes erkennen)",
        "settings.backend_local": "Nur lokal",
        "settings.backend_hermes": "Hermes",
        "settings.assistant_proactive_title": "Proaktive Vorschläge",
        "settings.assistant_proactive_desc": "Findet pausierte Arbeit und schlägt sie vor",
        "settings.assistant_autonomy_title": "Vertrauensstufe",
        "settings.assistant_autonomy_desc": "Nur vorschlagen oder Sicheres automatisch",
        "settings.autonomy_propose": "Nur vorschlagen (nach Bestätigung)",
        "settings.autonomy_auto": "Sichere Aktionen automatisch",
        "settings.assistant_interval_title": "Vorschlagsintervall (s)",
        "settings.assistant_interval_desc": "Wie oft nach Vorschlägen gesucht wird",
        "settings.section_window": "Fensterdarstellung",
        "settings.window_glass_title": "Fenster-Glaseffekt",
        "settings.window_glass_desc": "Aus = undurchsichtiger, besser lesbarer Hintergrund",
        "settings.window_opacity_title": "Hintergrund-Deckkraft",
        "settings.window_opacity_desc": "0 = klar … 1 = undurchsichtig (Lesbarkeit)",
        "history.search_placeholder": "Suchen (Frage/Antwort)",
        "history.save_master": "Verlauf speichern",
        "history.save_images": "Bilder speichern",
        "history.save_text": "Text speichern",
        "history.floating": "Immer im Vordergrund",
        "history.copy": "Kopieren",
        "history.reask": "Erneut fragen",
        "history.empty_question": "(leere Frage)",
        "history.turns": "{n} Runden",
        "history.empty": "Noch kein Verlauf.",
        "history.select_session": "Wählen Sie eine Sitzung, um das Gespräch anzuzeigen.",
        "settings.section_general": "Allgemein",
        "settings.section_connection": "Verbindung",
        "settings.section_response": "Antwort",
        "settings.section_hotkeys": "Kurzbefehle",
        "settings.section_appearance": "Darstellung",
        "settings.section_advanced": "Erweitert",
        "settings.language_title": "Sprache",
        "settings.language_desc": "Sprache von UI und Antworten — gilt nach dem Sichern",
        "settings.active_provider_title": "Aktiver Anbieter",
        "settings.active_provider_desc": "Endpunkt für Anfragen — unten bearbeiten, gilt nach dem Sichern",
        "settings.manage_title": "Anbieter verwalten",
        "settings.manage_desc": "Hinzufügen nutzt die OpenRouter-Vorlage — gilt nach dem Sichern",
        "settings.add": "Hinzufügen",
        "settings.delete": "Löschen",
        "settings.name_label": "Name",
        "settings.name_placeholder": "Anzeigename des Anbieters",
        "settings.url_label": "Serveradresse",
        "settings.url_placeholder": "OpenAI-kompatibler Endpunkt (z. B. https://openrouter.ai/api)",
        "settings.api_key_title": "API-Schlüssel",
        "settings.local_title": "Lokaler Server",
        "settings.local_desc": "Aktiviert /health-Polling + chat_template_kwargs",
        "settings.models_title": "Modellliste",
        "settings.models_desc": "Lädt /v1/models vom Server für die Autovervollständigung",
        "settings.refresh": "Aktualisieren",
        "settings.model_explain_title": "Erklärmodell",
        "settings.model_explain_desc": "Für Texterklärungen",
        "settings.model_vision_title": "Vision-Modell",
        "settings.model_vision_desc": "Für Bildschirmaufnahmen (multimodales Modell nötig)",
        "settings.new_provider_name": "Neuer Anbieter",
        "settings.key_new": "Neuer Schlüssel eingegeben — wird beim Sichern im Schlüsselbund abgelegt",
        "settings.key_env": "Umgebungsvariablen-Referenz ({ref})",
        "settings.key_stored": "Schlüssel gespeichert (Schlüsselbund) — leer lassen, um ihn zu behalten",
        "settings.key_none": "Kein Schlüssel — Eingabe speichert ihn im Schlüsselbund (lokal nicht nötig)",
        "settings.provider_added": "Anbieter hinzugefügt — gilt nach dem Sichern",
        "settings.provider_last": "⚠ Der letzte Anbieter kann nicht gelöscht werden.",
        "settings.provider_delete_staged": "'{name}' zum Löschen vorgemerkt — gilt nach dem Sichern",
        "settings.detail_title": "Detailgrad",
        "settings.detail_desc": "Voreinstellung für Antwortlänge/-tiefe",
        "settings.hk_text_title": "Text erklären",
        "settings.hk_text_desc": "Erklärt den ausgewählten Text",
        "settings.hk_region_title": "Bereich erklären",
        "settings.hk_region_desc": "Bildschirmbereich aufnehmen und erklären",
        "settings.hk_history_title": "Verlaufsfenster",
        "settings.hk_history_desc": "Verlaufs-/Einstellungsfenster umschalten",
        "settings.record_prompt": "Kurzbefehl drücken… (Esc bricht ab)",
        "settings.record_need_mod": "Mit ⌘/⌥/⌃/⇧ kombinieren",
        "settings.font_title": "Panel-Schriftgröße",
        "settings.font_desc": "Textgröße im Ergebnispanel (pt)",
        "settings.width_title": "Panel-Breite",
        "settings.width_desc": "Breite des Ergebnispanels (pt)",
        "settings.height_title": "Maximale Panel-Höhe",
        "settings.height_desc": "Wächst mit dem Inhalt bis zu dieser Höhe, danach Scrollen",
        "settings.glass_title": "Glas-Stil",
        "settings.glass_desc": "Glaseffekt von Panel/Fenster — Frosted ist am lesbarsten",
        "settings.glass_regular": "Frosted (Standard)",
        "settings.glass_clear": "Transparent (Clear)",
        "settings.prompt_text_label": "System prompt (Text)",
        "settings.prompt_image_label": "System prompt (Bild)",
        "settings.img_prompt_title": "Bildfrage-Prompt",
        "settings.img_prompt_desc": "Nutzernachricht, die mit Bildschirmaufnahmen gesendet wird",
        "settings.temp_title": "Temperature",
        "settings.temp_desc": "Sampling-Temperatur (0–2)",
        "settings.maxtok_title": "Max tokens",
        "settings.maxtok_desc": "Obergrenze der Antwortlänge (Detailgrad-Preset hat Vorrang)",
        "settings.followup_title": "Nachfrage-Runden",
        "settings.followup_desc": "Tiefe des Nachfrage-Gesprächs (älteste Paare werden entfernt)",
        "settings.kwargs_title": "Template kwargs",
        "settings.kwargs_desc": 'JSON — nur lokaler Server (z. B. {"enable_thinking": false})',
        "settings.reset_title": "Standard wiederherstellen",
        "settings.reset_desc": "Erweiterte Felder auf Auslieferungszustand (gilt nach dem Sichern)",
        "settings.reset_btn": "Zurücksetzen",
        "settings.save_btn": "Sichern",
        "settings.reset_done": "Standard wiederhergestellt — zum Anwenden sichern",
        "settings.saved": "Gesichert ✓",
        "settings.v_font_num": "Die Panel-Schriftgröße muss eine Zahl sein.",
        "settings.v_font_range": "Die Panel-Schriftgröße muss zwischen 8 und 40 liegen.",
        "settings.v_size_num": "Die Panel-Größe muss aus Zahlen bestehen.",
        "settings.v_size_small": "Panel zu klein (Breite 200+, Höhe 150+).",
        "settings.v_prompt_empty": "Der System prompt ist leer.",
        "settings.v_img_prompt_empty": "Der Bildfrage-Prompt ist leer.",
        "settings.v_temp": "Temperature muss eine Zahl sein.",
        "settings.v_maxtok": "Max tokens muss eine Ganzzahl sein.",
        "settings.v_followup": "Nachfrage-Runden müssen eine Ganzzahl sein.",
        "settings.v_kwargs_json": 'Template kwargs muss JSON sein (z. B. {"enable_thinking": false})',
        "settings.v_kwargs_obj": "Template kwargs muss ein JSON-Objekt sein.",
        "settings.v_pname_empty": "Der Anbietername ist leer.",
        "settings.v_pname_dup": "Anbieternamen müssen eindeutig sein.",
        "settings.v_url": "Die Serveradresse von '{name}' muss mit http(s):// beginnen.",
        "settings.v_explain_empty": "Das Erklärmodell des aktiven Anbieters ist leer.",
    },
}


# Language-resolved config defaults. ko is byte-identical to the pre-M11
# DEFAULTS values in config.py; the others are written natively, not literal
# translations. detail key order (brief/normal/detailed) and max_tokens
# (256/512/1024) must be identical in every language — the settings segmented
# control derives segment order from the dict, and the saved `explain_detail`
# key is language-neutral. The `detailed` suffix intentionally overrides the
# base prompt's sentence range in every language ("This time, however, …").
PROMPT_DEFAULTS = {
    "ko": {
        "system_prompt_text": (
            "너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트가 한국어가 아니면"
            "(영어/중국어/일본어 등) 먼저 '번역:'으로 시작하는 자연스러운 한국어 "
            "번역을 제시하고(긴 글이면 핵심 위주로), 그다음 핵심을 3~5문장으로 "
            "설명해. 전문용어는 짧게 풀어줘. 군더더기 금지. 추가로 질문을 받을 "
            "때는 그에 성실하게 답하는 비서처럼 답하면 된다. 번역은 처음 한 번으로 "
            "충분하다."
        ),
        "system_prompt_image": (
            "너는 한국어로 답하는 간결한 해설가다. 이미지 속 텍스트가 한국어가 "
            "아니면 먼저 '번역:'으로 시작하는 한국어 번역을 제시한 뒤 설명해. "
            "이미지의 핵심 내용을 설명하고, 표/코드/도식이면 의미를 풀어줘. 3~6문장. "
            "추가로 질문을 받을 때는 그에 성실하게 답하는 비서처럼 답하면 된다. "
            "번역은 처음 한 번으로 충분하다."
        ),
        "user_prompt_image": "이 이미지를 한국어로 간결하게 설명해줘.",
        "assistant_propose_system": (
            "너는 능동적 업무 비서다. 아래 신호를 보고 사용자가 지금 하면 좋을 "
            "일을 제안해라. JSON 배열만 출력하고 다른 설명은 절대 쓰지 마라. 각 "
            "항목은 {\"kind\": \"todo_add\", \"title\": \"...\", "
            "\"rationale\": \"...\"} 형식이며 kind는 todo_add만 사용한다. 제안이 "
            "없으면 []을 출력해라. 모든 문장은 한국어로."
        ),
        "assistant_digest_user": "다음 신호를 보고 제안해라:\n<<DIGEST>>",
        "assistant_resume_system": (
            "너는 사용자가 멈춘 업무 스레드를 다시 이어받도록 돕는 비서다. 아래 "
            "스레드 정보를 보고 '어디까지 했는지(where_was_i)'와 '다음에 할 "
            "일(next_action)'을 각각 한국어 1~2문장으로 요약해라. 반드시 JSON "
            "객체 하나만 출력해라: {\"where_was_i\": \"...\", "
            "\"next_action\": \"...\"}"
        ),
        "assistant_resume_user": "스레드 정보:\n<<CONTEXT>>",
        "assistant_answer_system": (
            "너는 사용자를 돕는 유능한 비서다. 요청에 한국어로 간결하고 정확하게 "
            "답하라. 불필요한 군더더기는 빼라."
        ),
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
    },
    "en": {
        "system_prompt_text": (
            "You are a concise explainer who answers in English. If the "
            "selected text is not English, first give a natural English "
            "translation starting with 'Translation:' (focus on the gist for "
            "long passages), then explain the key points in 3–5 sentences. "
            "Briefly unpack jargon. No filler. When you get follow-up "
            "questions, answer them faithfully like an assistant. Translating "
            "once at the start is enough."
        ),
        "system_prompt_image": (
            "You are a concise explainer who answers in English. If the text "
            "in the image is not English, first give an English translation "
            "starting with 'Translation:', then explain. Describe the image's "
            "key content; for tables/code/diagrams, explain their meaning. "
            "3–6 sentences. When you get follow-up questions, answer them "
            "faithfully like an assistant. Translating once at the start is "
            "enough."
        ),
        "user_prompt_image": "Explain this image concisely in English.",
        "assistant_propose_system": (
            "You are a proactive work assistant. Given the signals below, "
            "propose what the user should do now. Output ONLY a JSON array, no "
            "other text. Each item is {\"kind\": \"todo_add\", "
            "\"title\": \"...\", \"rationale\": \"...\"}; use only the kind "
            "todo_add. Output [] if there is nothing to propose. Write in "
            "English."
        ),
        "assistant_digest_user": "Propose based on these signals:\n<<DIGEST>>",
        "assistant_resume_system": (
            "You help the user resume a stalled work thread. From the thread "
            "info below, summarize 'where_was_i' and 'next_action' in 1–2 "
            "English sentences each. Output exactly one JSON object: "
            "{\"where_was_i\": \"...\", \"next_action\": \"...\"}"
        ),
        "assistant_resume_user": "Thread info:\n<<CONTEXT>>",
        "assistant_answer_system": (
            "You are a capable assistant. Answer the request concisely and "
            "accurately in English. No filler."
        ),
        "detail_levels": {
            "brief": {
                "label": "Brief",
                "prompt_suffix": " Give just the gist in one or two sentences.",
                "max_tokens": 256,
            },
            "normal": {"label": "Normal", "prompt_suffix": "", "max_tokens": 512},
            "detailed": {
                "label": "Detailed",
                "prompt_suffix": (
                    " This time, however, explain in detail in 6–10 sentences, "
                    "including background, context, and examples."
                ),
                "max_tokens": 1024,
            },
        },
    },
    "zh": {
        "system_prompt_text": (
            "你是一个用简体中文回答的简洁讲解者。如果选中的文本不是中文，先给出以"
            "「翻译：」开头的自然中文翻译（长文只译要点），然后用 3~5 句话解释核心"
            "内容。专业术语简短说明。不要废话。之后收到追问时，像助手一样认真回答"
            "即可。翻译只需在开头做一次。"
        ),
        "system_prompt_image": (
            "你是一个用简体中文回答的简洁讲解者。如果图像中的文字不是中文，先给出以"
            "「翻译：」开头的中文翻译，再进行解释。说明图像的核心内容；如果是表格/"
            "代码/图表，解释其含义。3~6 句话。之后收到追问时，像助手一样认真回答"
            "即可。翻译只需在开头做一次。"
        ),
        "user_prompt_image": "请用简体中文简洁地解释这张图片。",
        "assistant_propose_system": (
            "你是主动型工作助手。根据下面的信号，提出用户现在适合做的事。只输出 "
            "JSON 数组，不要任何其他文字。每一项为 {\"kind\": \"todo_add\", "
            "\"title\": \"...\", \"rationale\": \"...\"}，kind 只能用 todo_add。"
            "没有建议时输出 []。用简体中文书写。"
        ),
        "assistant_digest_user": "请根据以下信号提出建议：\n<<DIGEST>>",
        "assistant_resume_system": (
            "你帮助用户重新接续已停滞的工作线程。根据下面的线程信息，用 1～2 句"
            "简体中文分别概括 'where_was_i' 与 'next_action'。只输出一个 JSON "
            "对象：{\"where_was_i\": \"...\", \"next_action\": \"...\"}"
        ),
        "assistant_resume_user": "线程信息：\n<<CONTEXT>>",
        "assistant_answer_system": (
            "你是得力的助手。用简体中文简洁、准确地回答请求，不要废话。"
        ),
        "detail_levels": {
            "brief": {
                "label": "简短",
                "prompt_suffix": " 只用一两句话说出要点。",
                "max_tokens": 256,
            },
            "normal": {"label": "普通", "prompt_suffix": "", "max_tokens": 512},
            "detailed": {
                "label": "详细",
                "prompt_suffix": " 不过这次请包含背景知识、上下文和例子，用 6~10 句话详细解释。",
                "max_tokens": 1024,
            },
        },
    },
    "ja": {
        "system_prompt_text": (
            "あなたは日本語で答える簡潔な解説者です。選択されたテキストが日本語で"
            "ない場合は、まず「翻訳:」で始まる自然な日本語訳を示し（長文は要点中心"
            "で）、その後に核心を3〜5文で説明してください。専門用語は短く"
            "かみくだいて。冗長表現は禁止。追加で質問を受けたときは、それに誠実に"
            "答える秘書のように応じてください。翻訳は最初の一度で十分です。"
        ),
        "system_prompt_image": (
            "あなたは日本語で答える簡潔な解説者です。画像内のテキストが日本語で"
            "ない場合は、まず「翻訳:」で始まる日本語訳を示してから説明してください。"
            "画像の核心内容を説明し、表/コード/図解なら意味を解説。3〜6文。"
            "追加で質問を受けたときは、それに誠実に答える秘書のように応じて"
            "ください。翻訳は最初の一度で十分です。"
        ),
        "user_prompt_image": "この画像を日本語で簡潔に説明してください。",
        "assistant_propose_system": (
            "あなたは能動的な業務アシスタントだ。以下のシグナルを見て、ユーザーが"
            "今やるとよいことを提案せよ。JSON配列のみを出力し、他の文章は書くな。"
            "各項目は {\"kind\": \"todo_add\", \"title\": \"...\", "
            "\"rationale\": \"...\"} 形式で、kind は todo_add のみ。提案が無ければ "
            "[] を出力。日本語で記述。"
        ),
        "assistant_digest_user": "次のシグナルから提案せよ:\n<<DIGEST>>",
        "assistant_resume_system": (
            "あなたは中断した業務スレッドの再開を助けるアシスタントだ。以下の"
            "スレッド情報から 'where_was_i' と 'next_action' をそれぞれ日本語 "
            "1〜2文で要約せよ。JSONオブジェクトを1つだけ出力: "
            "{\"where_was_i\": \"...\", \"next_action\": \"...\"}"
        ),
        "assistant_resume_user": "スレッド情報:\n<<CONTEXT>>",
        "assistant_answer_system": (
            "あなたは有能なアシスタントだ。要望に日本語で簡潔かつ正確に答えよ。"
            "無駄を省け。"
        ),
        "detail_levels": {
            "brief": {
                "label": "簡単",
                "prompt_suffix": " 1〜2文で要点だけ述べてください。",
                "max_tokens": 256,
            },
            "normal": {"label": "普通", "prompt_suffix": "", "max_tokens": 512},
            "detailed": {
                "label": "詳しく",
                "prompt_suffix": (
                    " ただし今回は背景知識・文脈・例を含め、6〜10文で詳しく説明して"
                    "ください。"
                ),
                "max_tokens": 1024,
            },
        },
    },
    "fr": {
        "system_prompt_text": (
            "Tu es un explicateur concis qui répond en français. Si le texte "
            "sélectionné n'est pas en français, donne d'abord une traduction "
            "française naturelle commençant par « Traduction : » (l'essentiel "
            "pour les longs passages), puis explique les points clés en 3 à 5 "
            "phrases. Vulgarise brièvement le jargon. Pas de remplissage. "
            "Lorsque tu reçois des questions de suivi, réponds-y fidèlement "
            "comme un assistant. Une seule traduction au début suffit."
        ),
        "system_prompt_image": (
            "Tu es un explicateur concis qui répond en français. Si le texte "
            "de l'image n'est pas en français, donne d'abord une traduction "
            "commençant par « Traduction : », puis explique. Décris le contenu "
            "clé de l'image ; pour les tableaux/code/schémas, explique leur "
            "sens. 3 à 6 phrases. Lorsque tu reçois des questions de suivi, "
            "réponds-y fidèlement comme un assistant. Une seule traduction au "
            "début suffit."
        ),
        "user_prompt_image": "Explique cette image de façon concise en français.",
        "assistant_propose_system": (
            "Tu es un assistant de travail proactif. À partir des signaux "
            "ci-dessous, propose ce que l'utilisateur devrait faire maintenant. "
            "Renvoie UNIQUEMENT un tableau JSON, sans autre texte. Chaque "
            "élément est {\"kind\": \"todo_add\", \"title\": \"...\", "
            "\"rationale\": \"...\"} ; n'utilise que le kind todo_add. Renvoie "
            "[] s'il n'y a rien à proposer. Écris en français."
        ),
        "assistant_digest_user": "Propose à partir de ces signaux :\n<<DIGEST>>",
        "assistant_resume_system": (
            "Tu aides l'utilisateur à reprendre un fil de travail interrompu. "
            "À partir des infos ci-dessous, résume 'where_was_i' et "
            "'next_action' en 1–2 phrases françaises chacun. Renvoie un seul "
            "objet JSON : {\"where_was_i\": \"...\", \"next_action\": \"...\"}"
        ),
        "assistant_resume_user": "Infos du fil :\n<<CONTEXT>>",
        "assistant_answer_system": (
            "Tu es un assistant compétent. Réponds à la demande de façon "
            "concise et exacte en français, sans superflu."
        ),
        "detail_levels": {
            "brief": {
                "label": "Bref",
                "prompt_suffix": " Donne seulement l'essentiel en une ou deux phrases.",
                "max_tokens": 256,
            },
            "normal": {"label": "Normal", "prompt_suffix": "", "max_tokens": 512},
            "detailed": {
                "label": "Détaillé",
                "prompt_suffix": (
                    " Cette fois cependant, explique en détail en 6 à 10 "
                    "phrases, avec contexte, arrière-plan et exemples."
                ),
                "max_tokens": 1024,
            },
        },
    },
    "de": {
        "system_prompt_text": (
            "Du bist ein prägnanter Erklärer, der auf Deutsch antwortet. Ist "
            "der ausgewählte Text nicht auf Deutsch, gib zuerst eine "
            "natürliche deutsche Übersetzung, beginnend mit „Übersetzung:“ "
            "(bei langen Texten das Wesentliche), und erkläre dann die "
            "Kernpunkte in 3–5 Sätzen. Fachbegriffe kurz erläutern. Kein "
            "Füllmaterial. Bei Nachfragen antworte gewissenhaft wie ein "
            "Assistent. Eine einmalige Übersetzung zu Beginn genügt."
        ),
        "system_prompt_image": (
            "Du bist ein prägnanter Erklärer, der auf Deutsch antwortet. Ist "
            "der Text im Bild nicht auf Deutsch, gib zuerst eine Übersetzung, "
            "beginnend mit „Übersetzung:“, und erkläre dann. Beschreibe den "
            "Kerninhalt des Bildes; bei Tabellen/Code/Diagrammen erkläre die "
            "Bedeutung. 3–6 Sätze. Bei Nachfragen antworte gewissenhaft wie "
            "ein Assistent. Eine einmalige Übersetzung zu Beginn genügt."
        ),
        "user_prompt_image": "Erkläre dieses Bild prägnant auf Deutsch.",
        "assistant_propose_system": (
            "Du bist ein proaktiver Arbeitsassistent. Schlage anhand der "
            "Signale unten vor, was der Nutzer jetzt tun sollte. Gib NUR ein "
            "JSON-Array aus, keinen weiteren Text. Jedes Element ist "
            "{\"kind\": \"todo_add\", \"title\": \"...\", "
            "\"rationale\": \"...\"}; verwende nur den kind todo_add. Gib [] "
            "aus, wenn es nichts vorzuschlagen gibt. Schreibe auf Deutsch."
        ),
        "assistant_digest_user": "Schlage anhand dieser Signale vor:\n<<DIGEST>>",
        "assistant_resume_system": (
            "Du hilfst dem Nutzer, einen unterbrochenen Arbeitsstrang wieder "
            "aufzunehmen. Fasse aus den Infos unten 'where_was_i' und "
            "'next_action' in je 1–2 deutschen Sätzen zusammen. Gib genau ein "
            "JSON-Objekt aus: {\"where_was_i\": \"...\", \"next_action\": \"...\"}"
        ),
        "assistant_resume_user": "Strang-Infos:\n<<CONTEXT>>",
        "assistant_answer_system": (
            "Du bist ein fähiger Assistent. Beantworte die Anfrage knapp und "
            "genau auf Deutsch, ohne Füllwörter."
        ),
        "detail_levels": {
            "brief": {
                "label": "Kurz",
                "prompt_suffix": " Nenne nur das Wesentliche in ein bis zwei Sätzen.",
                "max_tokens": 256,
            },
            "normal": {"label": "Normal", "prompt_suffix": "", "max_tokens": 512},
            "detailed": {
                "label": "Ausführlich",
                "prompt_suffix": (
                    " Diesmal jedoch erkläre ausführlich in 6–10 Sätzen, "
                    "einschließlich Hintergrund, Kontext und Beispielen."
                ),
                "max_tokens": 1024,
            },
        },
    },
}

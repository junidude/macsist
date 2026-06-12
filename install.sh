#!/usr/bin/env bash
# Macsist 온보딩 인스톨러 (M10a, SPEC §5.5)
#
# 대화형(한국어) 설치: 하드웨어 점검 → 로컬 모델 추천/선택 또는 외부 API →
# 서버·앱 배포 → macsist CLI → TCC 권한 안내 → 스모크 테스트.
# 멱등 — 재실행해도 안전하며, 끝난 단계는 "[건너뜀]"으로 표시됩니다.
#
# 사용:  ./install.sh        (레포 루트에서)

set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPPORT_DIR="$HOME/Library/Application Support/Macsist"
APP_DIR="$SUPPORT_DIR/app"
SERVER_DIR="$SUPPORT_DIR/server"
MODELS_ENV="$SERVER_DIR/models.env"
APP_LABEL=com.macsist.app
SERVER_LABEL=com.macsist.llm-server
DOMAIN="gui/$(id -u)"
APP_PLIST="$HOME/Library/LaunchAgents/$APP_LABEL.plist"
APP_LOG="$HOME/Library/Logs/Macsist/app.log"
CONDA_BASE=/opt/homebrew/Caskroom/miniforge/base
PY_BASE="$CONDA_BASE/bin/python3"
ENV_PY="$CONDA_BASE/envs/llm-server/bin/python"
CONFIGURE="$REPO_ROOT/cli/configure.py"
URL_PANE_SCREEN="x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"

BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; CYAN=$'\033[36m'

say()  { echo "${CYAN}${BOLD}== $*${RESET}"; }
ok()   { echo "  ${GREEN}✓${RESET} $*"; }
skip() { echo "  ${DIM}[건너뜀 — 이미 완료]${RESET} $*"; }
warn() { echo "  ${YELLOW}△${RESET} $*"; }
fail() { echo "  ${RED}✗${RESET} $*"; }
die()  { fail "$*"; exit 1; }

ask() {  # ask <변수명> <프롬프트> [기본값]
    local __var="$1" __prompt="$2" __default="${3:-}" __in
    if [[ -n "$__default" ]]; then
        read -r -p "  $__prompt [$__default]: " __in
        printf -v "$__var" '%s' "${__in:-$__default}"
    else
        read -r -p "  $__prompt: " __in
        printf -v "$__var" '%s' "$__in"
    fi
}

confirm() {  # confirm <프롬프트> → rc 0(yes)
    local __in
    read -r -p "  $1 (y/n): " __in
    [[ "$__in" == y || "$__in" == Y ]]
}

# 어떤 python으로 configure.py를 돌릴지 (config.py/keychain.py는 stdlib-only)
cfgpy() {
    if [[ -x "$PY_BASE" ]]; then echo "$PY_BASE"
    elif [[ -x "$APP_DIR/.venv/bin/python" ]]; then echo "$APP_DIR/.venv/bin/python"
    else command -v python3; fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 0. 사전 점검
# ─────────────────────────────────────────────────────────────────────────────
say "0/7 사전 점검"
[[ "$(uname -m)" == arm64 ]] || die "Apple Silicon 전용입니다 (현재: $(uname -m))"
RAM_GB=$(($(sysctl -n hw.memsize) / 1073741824))
DISK_GB=$(df -g / | awk 'NR==2{print $4}')
CHIP="$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo Apple Silicon)"
ok "$CHIP / RAM ${RAM_GB}GB / 디스크 여유 ${DISK_GB}GB / macOS $(sw_vers -productVersion)"
[[ -f "$APP_DIR/main.py" ]] && warn "기존 설치가 감지되었습니다 — 재실행은 안전합니다."

# ─────────────────────────────────────────────────────────────────────────────
# 언어 선택 (M11) — 앱 UI + 답변 언어. 인스톨러 TUI 자체는 한국어 유지.
# ─────────────────────────────────────────────────────────────────────────────
say "언어 선택 (Language)"
echo "  1) 한국어   2) English   3) 简体中文   4) 日本語   5) Français   6) Deutsch"
ask LANG_CHOICE "선택 (Language)" 1
case "$LANG_CHOICE" in
    1) LANG_CODE=ko ;;
    2) LANG_CODE=en ;;
    3) LANG_CODE=zh ;;
    4) LANG_CODE=ja ;;
    5) LANG_CODE=fr ;;
    6) LANG_CODE=de ;;
    *) die "1~6 중에서 선택하세요." ;;
esac
"$(cfgpy)" "$CONFIGURE" set-language "$LANG_CODE" >/dev/null || die "언어 설정 실패"
ok "언어: $LANG_CODE"

# ─────────────────────────────────────────────────────────────────────────────
# 1. 모델 카탈로그 + 추천  (Qwen 3.6 / Gemma 4 멀티모달, 성능순)
#    형식: id|크기GB|최소RAM  (단일 멀티모달, vlm-only 모드로 구동)
# ─────────────────────────────────────────────────────────────────────────────
CATALOG=(
    "mlx-community/Qwen3.6-35B-A3B-4bit|22|48"
    "mlx-community/gemma-4-31b-it-4bit|18|40"
    "mlx-community/gemma-4-26b-a4b-it-4bit|15|32"
    "mlx-community/gemma-4-12B-it-qat-4bit|7|16"
    "mlx-community/gemma-4-E4B-it-qat-4bit|4|8"
)
FULL_VLM="mlx-community/Qwen3.6-35B-A3B-4bit"   # 멀티모달 (vision)
FULL_LM="mlx-community/Qwen3.6-27B-4bit"        # 텍스트 전용 (explain)
FULL_SIZE=36                                     # 22+14GB

hf_exists() {  # 모델 repo가 HF에 실제로 존재하는지 (네트워크 없으면 통과)
    curl -fsS -o /dev/null --max-time 10 "https://huggingface.co/api/models/$1" 2>/dev/null
}

say "1/7 모델 추천 (RAM ${RAM_GB}GB 기준)"
HF_ONLINE=1
curl -fsS -o /dev/null --max-time 10 "https://huggingface.co/api/models/$FULL_VLM" \
    || { HF_ONLINE=0; warn "HuggingFace 접속 불가 — 모델 존재 확인을 생략합니다."; }

VERIFIED=()  # 사용 가능 카탈로그 (존재 확인 통과분)
for entry in "${CATALOG[@]}"; do
    id="${entry%%|*}"
    if [[ "$HF_ONLINE" == 0 ]] || hf_exists "$id"; then
        VERIFIED+=("$entry")
    else
        warn "HF에 없음 — 제외: $id"
    fi
done

RECO_KIND="" RECO_ENTRY=""
if [[ "$RAM_GB" -ge 96 ]]; then
    RECO_KIND="full"
    echo "  추천: ${BOLD}풀 스택${RESET} — 텍스트 $FULL_LM + 비전 $FULL_VLM (~${FULL_SIZE}GB)"
else
    for entry in "${VERIFIED[@]}"; do
        IFS='|' read -r id size min_ram <<< "$entry"
        if [[ "$RAM_GB" -ge "$min_ram" && "$DISK_GB" -ge $((size + 5)) ]]; then
            RECO_KIND="single"; RECO_ENTRY="$entry"
            echo "  추천: ${BOLD}$id${RESET} (~${size}GB, 단일 멀티모달)"
            break
        fi
    done
    if [[ -z "$RECO_KIND" ]]; then
        RECO_KIND="api"
        echo "  추천: RAM ${RAM_GB}GB — 로컬 모델 대신 ${BOLD}외부 API${RESET}를 권장합니다."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. 경로 선택
# ─────────────────────────────────────────────────────────────────────────────
say "2/7 설치 경로 선택"
echo "  1) 로컬 모델 — 추천 구성으로 진행"
echo "  2) 로컬 모델 — 목록에서 직접 선택"
echo "  3) 외부 API (OpenAI / OpenRouter 등)"
ask PATH_CHOICE "선택" "$([[ "$RECO_KIND" == api ]] && echo 3 || echo 1)"

INSTALL_LOCAL=0 MODE="" VLM_MODEL="" LM_MODEL="" DL_SIZE=0
case "$PATH_CHOICE" in
    1)
        if [[ "$RECO_KIND" == api ]]; then
            die "이 머신 RAM으로는 로컬 모델을 추천하지 않습니다 — 2(직접 선택) 또는 3(API)을 고르세요."
        fi
        INSTALL_LOCAL=1
        if [[ "$RECO_KIND" == full ]]; then
            MODE=full; VLM_MODEL="$FULL_VLM"; LM_MODEL="$FULL_LM"; DL_SIZE=$FULL_SIZE
        else
            IFS='|' read -r VLM_MODEL DL_SIZE _ <<< "$RECO_ENTRY"
            MODE=vlm-only
        fi
        ;;
    2)
        INSTALL_LOCAL=1
        echo "  0) 풀 스택: $FULL_LM + $FULL_VLM (~${FULL_SIZE}GB, RAM 96GB+ 권장)"
        i=1
        for entry in "${VERIFIED[@]}"; do
            IFS='|' read -r id size min_ram <<< "$entry"
            echo "  $i) $id (~${size}GB, RAM ${min_ram}GB+)"
            i=$((i + 1))
        done
        ask MODEL_CHOICE "모델 번호" ""
        [[ "$MODEL_CHOICE" =~ ^[0-9]+$ ]] || die "숫자를 입력하세요."
        if [[ "$MODEL_CHOICE" == 0 ]]; then
            MODE=full; VLM_MODEL="$FULL_VLM"; LM_MODEL="$FULL_LM"; DL_SIZE=$FULL_SIZE
            [[ "$RAM_GB" -lt 96 ]] && warn "RAM ${RAM_GB}GB — 풀 스택(두 모델 동시 로드)은 96GB+ 권장입니다."
        else
            entry="${VERIFIED[$((MODEL_CHOICE - 1))]:-}"
            [[ -n "$entry" ]] || die "잘못된 번호입니다."
            IFS='|' read -r VLM_MODEL DL_SIZE min_ram <<< "$entry"
            MODE=vlm-only
            [[ "$RAM_GB" -lt "$min_ram" ]] && warn "RAM ${RAM_GB}GB — 이 모델은 ${min_ram}GB+ 권장입니다."
        fi
        ;;
    3) INSTALL_LOCAL=0 ;;
    *) die "1/2/3 중에서 선택하세요." ;;
esac

# ─────────────────────────────────────────────────────────────────────────────
# 3. 로컬 경로: miniforge → conda env → HF 토큰 → 다운로드 → models.env → 배포
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$INSTALL_LOCAL" == 1 ]]; then
    say "3/7 로컬 LLM 서버 설치 ($MODE: $VLM_MODEL${LM_MODEL:+ + $LM_MODEL})"

    # 3-1 miniforge (deploy 스크립트들이 Caskroom 경로를 전제)
    if [[ -x "$PY_BASE" ]]; then
        skip "miniforge ($CONDA_BASE)"
    else
        command -v brew >/dev/null \
            || die "Homebrew가 필요합니다 — https://brew.sh 안내대로 설치 후 다시 실행하세요."
        echo "  miniforge를 설치합니다 (brew install --cask miniforge)…"
        brew install --cask miniforge || die "miniforge 설치 실패"
        ok "miniforge 설치됨"
    fi

    # 3-2 conda env llm-server (+ 패키지 — 멱등, 손상 복구 겸용)
    if [[ -x "$ENV_PY" ]]; then
        skip "conda env llm-server"
    else
        echo "  conda env(llm-server, python 3.11)를 생성합니다…"
        # shellcheck disable=SC1091
        source "$CONDA_BASE/etc/profile.d/conda.sh"
        conda create -n llm-server python=3.11 -y || die "conda env 생성 실패"
        ok "conda env 생성됨"
    fi
    echo "  ${DIM}서버 패키지 설치/확인 중 (mlx-lm, mlx-vlm, fastapi, …)${RESET}"
    "$CONDA_BASE/envs/llm-server/bin/pip" install -q -r "$REPO_ROOT/server/requirements.txt" \
        || die "패키지 설치 실패"
    ok "서버 패키지 준비됨"

    # 3-3 HF 토큰 (선택 — 공개 모델은 없어도 받지만, 속도 제한이 풀립니다)
    if [[ -f "$HOME/.cache/huggingface/token" ]]; then
        skip "HF 토큰 (캐시됨)"
    else
        echo "  HuggingFace 토큰(선택): 입력하면 속도 제한 없이 받습니다. 비워두면 익명으로 진행."
        read -rs -p "  HF 토큰 (없으면 Enter): " HF_TOK; echo
        if [[ -n "$HF_TOK" ]]; then
            HF_TOKEN="$HF_TOK" "$ENV_PY" -c \
                "import os; from huggingface_hub import login; login(token=os.environ['HF_TOKEN'])" \
                && ok "HF 토큰 저장됨 (~/.cache/huggingface)" \
                || warn "토큰 저장 실패 — 익명으로 진행합니다."
            unset HF_TOK HF_TOKEN
        fi
    fi

    # 3-4 모델 다운로드 (캐시된 모델은 즉시 통과)
    echo "  다운로드 ~${DL_SIZE}GB / 디스크 여유 ${DISK_GB}GB — 이미 캐시된 모델은 건너뜁니다."
    confirm "다운로드를 시작할까요?" || die "사용자 취소"
    if [[ "$MODE" == full ]]; then
        bash "$REPO_ROOT/server/download_models.sh" "$VLM_MODEL" "$LM_MODEL" || die "모델 다운로드 실패"
    else
        bash "$REPO_ROOT/server/download_models.sh" "$VLM_MODEL" || die "모델 다운로드 실패"
    fi
    ok "모델 준비됨"

    # 3-5 models.env (서버 모델 설정 — install.sh가 소유)
    NEW_ENV="MACSIST_SERVER_MODE=\"$MODE\"
MACSIST_VLM_MODEL=\"$VLM_MODEL\"
MACSIST_LM_MODEL=\"${LM_MODEL:-mlx-community/Qwen3.6-27B-4bit}\""
    mkdir -p "$SERVER_DIR"
    if [[ -f "$MODELS_ENV" ]] && [[ "$(cat "$MODELS_ENV")" == "$NEW_ENV" ]]; then
        skip "models.env (동일 설정)"
    else
        if [[ -f "$MODELS_ENV" ]]; then
            echo "  기존 models.env:"; sed 's/^/    /' "$MODELS_ENV"
            echo "  새 설정:"; echo "$NEW_ENV" | sed 's/^/    /'
            confirm "models.env를 새 설정으로 바꿀까요?" || die "사용자 취소"
        fi
        printf '%s\n' "$NEW_ENV" > "$MODELS_ENV"
        ok "models.env 작성됨"
    fi

    # 3-6 서버 배포 (+ LaunchAgent 재기동 — deploy.sh가 멱등 처리)
    bash "$REPO_ROOT/server/deploy.sh" || die "서버 배포 실패"
    ok "서버 LaunchAgent 가동"

    # 3-7 앱 설정 — 첫 부팅부터 올바른 모델을 보도록 앱 배포 전에 기록
    if [[ "$MODE" == full ]]; then
        "$(cfgpy)" "$CONFIGURE" set-local-provider --mode full \
            --vlm-model "$VLM_MODEL" --lm-model "$LM_MODEL" >/dev/null || die "앱 설정 실패"
    else
        "$(cfgpy)" "$CONFIGURE" set-local-provider --mode vlm-only \
            --vlm-model "$VLM_MODEL" >/dev/null || die "앱 설정 실패"
    fi
    ok "앱 설정(config.json): 로컬 서버 프로바이더 활성"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. 외부 API 경로
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$INSTALL_LOCAL" == 0 ]]; then
    say "3/7 외부 API 프로바이더 설정"
    echo "  1) OpenAI      (https://api.openai.com)"
    echo "  2) OpenRouter  (https://openrouter.ai/api)"
    echo "  3) 직접 입력   (OpenAI 호환, base URL은 /v1 제외)"
    ask API_CHOICE "선택" 1
    case "$API_CHOICE" in
        1) API_NAME="OpenAI"; API_URL="https://api.openai.com"; API_MODEL_DEF="gpt-4o-mini" ;;
        2) API_NAME="OpenRouter"; API_URL="https://openrouter.ai/api"; API_MODEL_DEF="openai/gpt-4o-mini" ;;
        3) ask API_NAME "프로바이더 이름" ""; ask API_URL "Base URL (/v1 제외)" ""; API_MODEL_DEF="" ;;
        *) die "1/2/3 중에서 선택하세요." ;;
    esac
    [[ -n "$API_NAME" && -n "$API_URL" ]] || die "이름/URL이 비었습니다."
    ask API_MODEL "텍스트 모델" "$API_MODEL_DEF"
    ask API_VISION "비전 모델" "$API_MODEL"
    [[ -n "$API_MODEL" ]] || die "모델이 비었습니다."

    # 키: 기존 키가 있으면 유지 가능 (멱등 재실행)
    KEY_PRESENT=0
    if "$(cfgpy)" "$CONFIGURE" status 2>/dev/null \
            | grep -q "\"name\": \"$API_NAME\""; then
        eval "$("$(cfgpy)" "$CONFIGURE" status --shell 2>/dev/null)" || true
        [[ "${P_NAME:-}" == "$API_NAME" && "${P_KEY_PRESENT:-}" == 1 ]] && KEY_PRESENT=1
    fi
    if [[ "$KEY_PRESENT" == 1 ]] && confirm "저장된 API 키가 있습니다 — 그대로 쓸까요?"; then
        "$(cfgpy)" "$CONFIGURE" set-api-provider --name "$API_NAME" --base-url "$API_URL" \
            --explain-model "$API_MODEL" --vision-model "$API_VISION" >/dev/null \
            || die "프로바이더 저장 실패"
    else
        while true; do
            read -rs -p "  API 키: " API_KEY; echo
            [[ -n "$API_KEY" ]] || { warn "키가 비었습니다."; continue; }
            printf '%s\n' "$API_KEY" | "$(cfgpy)" "$CONFIGURE" set-api-provider \
                --name "$API_NAME" --base-url "$API_URL" \
                --explain-model "$API_MODEL" --vision-model "$API_VISION" \
                --key-stdin >/dev/null || die "프로바이더 저장 실패"
            unset API_KEY
            if "$(cfgpy)" "$CONFIGURE" probe >/dev/null 2>&1; then
                ok "키 확인됨 ($API_NAME 응답 정상, 키는 Keychain에만 저장)"
                break
            fi
            warn "$API_NAME 인증 실패 — 키를 다시 확인하세요."
            confirm "키를 다시 입력할까요? (n = 그대로 진행)" || break
        done
    fi
    ok "프로바이더 설정됨: $API_NAME ($API_URL)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. 앱 배포 + macsist CLI
# ─────────────────────────────────────────────────────────────────────────────
say "4/7 메뉴 바 앱 배포"
bash "$REPO_ROOT/app/deploy.sh" || die "앱 배포 실패"
ok "앱 LaunchAgent 가동"

say "5/7 macsist CLI 설치"
CLI_SRC="$REPO_ROOT/cli/macsist"
if [[ "$(readlink "$(command -v macsist 2>/dev/null)" 2>/dev/null)" == "$CLI_SRC" ]]; then
    skip "macsist CLI ($(command -v macsist))"
else
    echo "  /usr/local/bin/macsist 심링크 생성에 관리자 권한(sudo)이 필요합니다."
    # 새 Apple Silicon 머신엔 /usr/local/bin 디렉토리 자체가 없다 (PATH엔 있음)
    if sudo -p "  암호: " /bin/sh -c \
            "mkdir -p /usr/local/bin && ln -sf '$CLI_SRC' /usr/local/bin/macsist" \
            2>/dev/null; then
        ok "CLI 설치됨: /usr/local/bin/macsist"
    else
        mkdir -p "$HOME/.local/bin"
        ln -sf "$CLI_SRC" "$HOME/.local/bin/macsist"
        ok "CLI 설치됨: ~/.local/bin/macsist"
        case ":$PATH:" in
            *":$HOME/.local/bin:"*) ;;
            *) warn "~/.local/bin 이 PATH에 없습니다 — 셸 설정에 추가하세요:"
               echo "      export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
        esac
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. TCC 권한 안내 (앱 로그의 "TCC:" 줄만 신뢰 — 터미널 명의 검사 금지)
# ─────────────────────────────────────────────────────────────────────────────
say "6/7 macOS 권한 (TCC)"

fresh_tcc() {  # fresh_tcc <로그 오프셋> → 그 이후의 최신 TCC: 줄
    [[ -f "$APP_LOG" ]] || return 0
    tail -c +"$(($1 + 1))" "$APP_LOG" | grep "^TCC: " | tail -1
}
app_kick() {
    LOG_OFS=$( [[ -f "$APP_LOG" ]] && wc -c < "$APP_LOG" || echo 0 )
    launchctl kickstart -k "$DOMAIN/$APP_LABEL"
}

app_kick
TCC_LINE=""
for _ in $(seq 1 10); do
    sleep 2; TCC_LINE="$(fresh_tcc "$LOG_OFS")"; [[ -n "$TCC_LINE" ]] && break
done
[[ -n "$TCC_LINE" ]] || warn "앱 로그에서 TCC 상태를 읽지 못했습니다 — 계속 진행합니다."

if [[ "$TCC_LINE" == *"accessibility=True"* ]]; then
    skip "손쉬운 사용 권한"
else
    echo "  ${BOLD}손쉬운 사용${RESET} 권한이 필요합니다 (핫키·텍스트 캡처)."
    echo "  방금 앱이 시스템 설정을 열고 권한을 요청했습니다 — 목록에서 ${BOLD}python${RESET}을 허용하세요."
    echo "  허용하면 앱이 자동으로 재시작됩니다. (s + Enter = 건너뛰기)"
    while [[ "$TCC_LINE" != *"accessibility=True"* ]]; do
        read -r -t 3 -p "" REPLY 2>/dev/null || true
        [[ "${REPLY:-}" == s ]] && { warn "건너뜀 — 권한 없이는 핫키가 동작하지 않습니다."; break; }
        TCC_LINE="$(fresh_tcc "$LOG_OFS")"
    done
    [[ "$TCC_LINE" == *"accessibility=True"* ]] && ok "손쉬운 사용 허용됨"
fi

if [[ "$TCC_LINE" == *"screen_recording=True"* ]]; then
    skip "화면 기록 권한"
elif [[ -n "$TCC_LINE" ]]; then
    echo "  ${BOLD}화면 기록${RESET} 권한은 영역 캡처 설명에 필요합니다 (텍스트 설명은 없어도 동작)."
    if confirm "지금 설정할까요?"; then
        open "$URL_PANE_SCREEN"
        echo "  목록에 python이 없으면 '+'로 다음 경로를 추가하세요:"
        echo "    $(readlink -f "$APP_DIR/.venv/bin/python")"
        while true; do
            read -r -p "  허용했으면 Enter (s + Enter = 건너뛰기): " REPLY
            [[ "$REPLY" == s ]] && { warn "건너뜀 — 첫 영역 캡처 때 다시 요청됩니다."; break; }
            app_kick
            sleep 3; TCC_LINE="$(fresh_tcc "$LOG_OFS")"
            [[ "$TCC_LINE" == *"screen_recording=True"* ]] && { ok "화면 기록 허용됨"; break; }
            warn "아직 허용이 감지되지 않습니다 — 설정 후 다시 Enter."
        done
    else
        warn "건너뜀 — 첫 영역 캡처 때 다시 요청됩니다."
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. 스모크 테스트
# ─────────────────────────────────────────────────────────────────────────────
say "7/7 스모크 테스트"

if [[ "$INSTALL_LOCAL" == 1 ]]; then
    echo -n "  서버 기동 대기 (첫 모델 로드는 60–90초) "
    HEALTH_OK=0
    for _ in $(seq 1 80); do
        if curl -s --max-time 2 http://127.0.0.1:8000/health | grep -q '"status":"ok"'; then
            HEALTH_OK=1; echo; break
        fi
        echo -n "."; sleep 3
    done
    [[ "$HEALTH_OK" == 1 ]] || die "서버가 준비되지 않았습니다 — macsist logs server 로 확인하세요."
    ok "서버 /health: ok"

    eval "$("$(cfgpy)" "$CONFIGURE" status --shell)" || die "설정을 읽지 못했습니다."
    CHAT=$(curl -s --max-time 120 http://127.0.0.1:8000/v1/chat/completions \
        -H 'Content-Type: application/json' -d "{
        \"model\": \"$P_EXPLAIN\", \"max_tokens\": 32, \"stream\": false,
        \"chat_template_kwargs\": {\"enable_thinking\": false},
        \"messages\": [{\"role\": \"user\", \"content\": \"안녕\"}]}")
    echo "$CHAT" | grep -q '"content"' || die "응답 생성 실패: $(echo "$CHAT" | head -c 200)"
    ok "텍스트 생성 1회 통과 ($P_EXPLAIN)"
else
    "$(cfgpy)" "$CONFIGURE" probe >/dev/null 2>&1 || warn "프로바이더 프로브 실패 — 키/URL을 확인하세요."
    ok "외부 프로바이더 연결 확인"
fi

# 앱 왕복: 패널까지의 전체 경로 (HE_DEBUG_FAKE_TEXT — TCC 불필요).
# HE_DEBUG_KEEP_PANEL: 디스미스 모니터를 끈다 — 설치 중 사용자가 키를
# 누르거나 클릭하면 패널이 닫히며 스트림이 취소되어(로컬 27B는 512토큰에
# ~30초) 테스트가 플레이크된다. 디스미스 훅도 같은 이유로 쓰지 않는다.
# 성공 판정 후 프로세스를 종료하면 패널도 함께 사라진다.
echo "  앱 왕복 테스트 (화면에 패널이 잠깐 나타납니다)…"
launchctl bootout "$DOMAIN/$APP_LABEL" 2>/dev/null || true
trap 'launchctl bootstrap "$DOMAIN" "$APP_PLIST" 2>/dev/null || true' EXIT
SMOKE_OUT=$(mktemp)
HE_DEBUG_SKIP_AX_PROMPT=1 HE_DEBUG_KEEP_PANEL=1 \
HE_DEBUG_FAKE_TEXT="안녕하세요. 맥시스트 설치 테스트입니다." \
HE_DEBUG_EXPLAIN_AFTER=2 \
    "$APP_DIR/.venv/bin/python" "$APP_DIR/main.py" > "$SMOKE_OUT" 2>&1 &
SMOKE_PID=$!
SMOKE_OK=0
for _ in $(seq 1 60); do
    grep -q "stream finished, panel text:" "$SMOKE_OUT" && { SMOKE_OK=1; break; }
    kill -0 "$SMOKE_PID" 2>/dev/null || break
    sleep 3
done
kill "$SMOKE_PID" 2>/dev/null; wait "$SMOKE_PID" 2>/dev/null
launchctl bootstrap "$DOMAIN" "$APP_PLIST" 2>/dev/null || true
trap - EXIT
if [[ "$SMOKE_OK" == 1 ]]; then
    ok "앱 왕복 통과: $(grep "stream finished" "$SMOKE_OUT" | head -1 | head -c 120)…"
    rm -f -- "$SMOKE_OUT" 2>/dev/null || true
else
    fail "앱 왕복 실패 — 로그 보존됨: $SMOKE_OUT (macsist doctor 도 실행해보세요)"
fi

# 마무리 안내
pretty_hotkey() {
    echo "$1" | sed -e 's/<cmd>/⌘/g' -e 's/<shift>/⇧/g' -e 's/<alt>/⌥/g' \
        -e 's/<ctrl>/⌃/g' -e 's/+//g' | tr '[:lower:]' '[:upper:]'
}
eval "$("$(cfgpy)" "$CONFIGURE" status --shell 2>/dev/null)" || true
echo
say "설치 완료 🎉"
echo "  아무 앱에서나 텍스트를 선택하고 ${BOLD}$(pretty_hotkey "${HK_TEXT:-<cmd>+<shift>+e}")${RESET} 를 눌러보세요."
echo "  화면 영역 설명: $(pretty_hotkey "${HK_REGION:-<cmd>+<shift>+r}") / 기록 창: $(pretty_hotkey "${HK_HISTORY:-<cmd>+<shift>+h}")"
echo "  상태 확인: ${BOLD}macsist status${RESET} · 진단: ${BOLD}macsist doctor${RESET} · 로그: ${BOLD}macsist logs${RESET}"

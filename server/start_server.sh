#!/usr/bin/env bash
# Start the three server processes for HotkeyExplain.
#
# Usage:
#   ./start_server.sh                 # start all, return to shell (manual/dev)
#   ./start_server.sh --supervise     # start all, then block (for launchd KeepAlive)
#   ./start_server.sh --vlm-only      # only the vision/explain backend + proxy
#   ./start_server.sh --lm-only       # only the dense backend + proxy
#
# Ports:
#   8000 — proxy (FastAPI, routes to 8001/8002)
#   8001 — mlx-vlm  backend  (Qwen3.6-35B-A3B-4bit, multimodal, explain default)
#   8002 — mlx-lm   backend  (Qwen3.6-27B-4bit, dense, agent backbone)
#
# Logs: ~/Library/Logs/llm-server/{proxy,vlm,lm}.log
#
# NOTE: This script must live OUTSIDE ~/Documents (a TCC-protected folder that
# launchd agents cannot read). It is deployed to
#   ~/Library/Application Support/HotkeyExplain/server/
# by deploy.sh. The HF model cache (~/.cache/huggingface) and logs
# (~/Library/Logs) are not TCC-protected, so backends load fine from there.

set -uo pipefail

CONDA_BASE="/opt/homebrew/Caskroom/miniforge/base"
ENV_NAME="llm-server"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/llm-server"
mkdir -p "$LOG_DIR"

VLM_MODEL="mlx-community/Qwen3.6-35B-A3B-4bit"
LM_MODEL="mlx-community/Qwen3.6-27B-4bit"

# server.py lives next to this script; uvicorn imports it as `server:app`.
cd "$SCRIPT_DIR"

# Activate conda env
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

MODE="${1:-}"

stop_existing() {
    # SIGTERM, then wait up to ~10s for each port to free, then SIGKILL.
    # Backends must fully release their port before we rebind, or the new
    # process exits on "address in use" and the supervisor loops forever.
    for port in 8000 8001 8002; do
        pid=$(lsof -ti tcp:$port 2>/dev/null || true)
        [[ -n "$pid" ]] && kill $pid 2>/dev/null && echo "Stopping PID(s) $pid on :$port"
    done
    for port in 8000 8001 8002; do
        for _ in $(seq 1 20); do
            pid=$(lsof -ti tcp:$port 2>/dev/null || true)
            [[ -z "$pid" ]] && break
            sleep 0.5
        done
        pid=$(lsof -ti tcp:$port 2>/dev/null || true)
        [[ -n "$pid" ]] && kill -9 $pid 2>/dev/null && echo "Force-killed $pid on :$port"
    done
    sleep 1
}

stop_existing

PIDS=()

if [[ "$MODE" != "--lm-only" ]]; then
    echo "Starting mlx-vlm backend on :8001 (model: $VLM_MODEL) ..."
    python3 -m mlx_vlm.server --model "$VLM_MODEL" --port 8001 --host 127.0.0.1 \
        >> "$LOG_DIR/vlm.log" 2>&1 &
    PIDS+=($!)
    echo "  vlm PID=$! log=$LOG_DIR/vlm.log"
fi

if [[ "$MODE" != "--vlm-only" ]]; then
    echo "Starting mlx-lm backend on :8002 (model: $LM_MODEL) ..."
    python3 -m mlx_lm.server --model "$LM_MODEL" --port 8002 --host 127.0.0.1 \
        >> "$LOG_DIR/lm.log" 2>&1 &
    PIDS+=($!)
    echo "  lm  PID=$! log=$LOG_DIR/lm.log"
fi

echo "Waiting for backends to load models (~60s first run, ~10s after cache)..."
sleep 5

# Tell the proxy which backends to count in /health (vlm-only/lm-only stacks
# must not report "loading" forever for the backend they never start).
case "$MODE" in
    --vlm-only) export HE_EXPECTED_BACKENDS="vlm" ;;
    --lm-only)  export HE_EXPECTED_BACKENDS="lm" ;;
    *)          export HE_EXPECTED_BACKENDS="vlm,lm" ;;
esac

echo "Starting proxy on :8000 (expected backends: $HE_EXPECTED_BACKENDS) ..."
uvicorn server:app --host 127.0.0.1 --port 8000 --log-level info \
    >> "$LOG_DIR/proxy.log" 2>&1 &
PIDS+=($!)
echo "  proxy PID=$! log=$LOG_DIR/proxy.log"

echo ""
echo "All servers started. HotkeyExplain endpoint: http://127.0.0.1:8000"

if [[ "$MODE" == "--supervise" ]]; then
    # Block as the launchd job's main process. If ANY child dies, exit non-zero
    # so launchd (KeepAlive=true) restarts the whole stack cleanly.
    # Poll-based so it works on macOS's stock bash 3.2 (no `wait -n`).
    echo "Supervising ${#PIDS[@]} processes (PIDs: ${PIDS[*]}); will exit if any dies."
    while true; do
        for pid in "${PIDS[@]}"; do
            if ! kill -0 "$pid" 2>/dev/null; then
                echo "PID $pid exited; shutting down the rest for a clean restart."
                for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done
                exit 1
            fi
        done
        sleep 5
    done
fi

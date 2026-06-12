#!/usr/bin/env bash
# Download MLX models from HuggingFace to the local HF cache.
# snapshot_download is idempotent/resumable — already-cached models are a
# near-instant no-op, so this is safe to re-run.
#
# Usage:
#   ./download_models.sh <hf-id> [<hf-id> ...]   # download exactly these
#   ./download_models.sh                          # models from models.env
#                                                 # (deploy dir), else the
#                                                 # historical defaults

set -uo pipefail

CONDA_BASE="/opt/homebrew/Caskroom/miniforge/base"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate llm-server

MODELS=("$@")
if [[ ${#MODELS[@]} -eq 0 ]]; then
    MODELS_ENV="$HOME/Library/Application Support/Macsist/server/models.env"
    # shellcheck disable=SC1090
    [[ -f "$MODELS_ENV" ]] && source "$MODELS_ENV"
    MODE="${MACSIST_SERVER_MODE:-full}"
    VLM="${MACSIST_VLM_MODEL:-mlx-community/Qwen3.6-35B-A3B-4bit}"
    LM="${MACSIST_LM_MODEL:-mlx-community/Qwen3.6-27B-4bit}"
    case "$MODE" in
        vlm-only) MODELS=("$VLM") ;;
        lm-only)  MODELS=("$LM") ;;
        *)        MODELS=("$VLM" "$LM") ;;
    esac
fi

for model in "${MODELS[@]}"; do
    echo "=== Downloading $model ==="
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('$model')
print('Done: $model')
" || exit 1
done

echo "All models downloaded."

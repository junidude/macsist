#!/usr/bin/env bash
# Download Qwen3.6 models from mlx-community to the local HF cache.
# Run once; subsequent starts load from cache (~/.cache/huggingface).

CONDA_BASE="/opt/homebrew/Caskroom/miniforge/base"
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate llm-server

echo "=== Downloading Qwen3.6-35B-A3B-4bit (~22 GB) ==="
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('mlx-community/Qwen3.6-35B-A3B-4bit')
print('Done: Qwen3.6-35B-A3B-4bit')
"

echo "=== Downloading Qwen3.6-27B-4bit (~14 GB) ==="
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('mlx-community/Qwen3.6-27B-4bit')
print('Done: Qwen3.6-27B-4bit')
"

echo "All models downloaded."

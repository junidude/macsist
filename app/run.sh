#!/usr/bin/env bash
# Run Macsist. Creates the venv + installs deps on first run.
set -euo pipefail
cd "$(dirname "$0")"

PY=/opt/homebrew/Caskroom/miniforge/base/bin/python3

if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python main.py

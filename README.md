# macsist — HotkeyExplain

Native macOS **menu-bar app**: press a global hotkey to get a **concise Korean
explanation** of whatever you have **selected** (any app) or of a **screen
region** you drag-select — streamed token-by-token into a small floating panel
near the cursor, from a **local** LLM (MLX). No cloud, no Electron.

- **Text explain** (default `⌘⇧E`): reads the selection via Accessibility,
  falling back to a clipboard-safe synthetic ⌘C (clipboard is always restored).
- **Region explain** (default `⌘⇧R`): ⌘⇧4-style crosshair → the image goes to a
  local vision model.
- Settings (menu-bar icon): server URL, explain/vision models (picker from the
  server's loaded models), hotkey recorder, detail level (간단/보통/자세히).
- Stack: Python 3.13 + PyObjC (AppKit), `pynput`, `httpx` SSE; server is
  MLX-backed (`mlx-lm` / `mlx-vlm`) behind a FastAPI proxy. Apple Silicon,
  macOS 26.2+.

## Install (two parts)

```bash
# 1. LLM server — one-time model download, then always-on via launchd
server/download_models.sh
server/deploy.sh

# 2. Menu-bar app — always-on via launchd
app/deploy.sh
```

On first launch grant **Accessibility** (prompted) and, on first region
capture, **Screen Recording**, then restart:
`launchctl kickstart -k "gui/$(id -u)/com.hotkeyexplain.app"`.
For development, run the app in the foreground instead with `app/run.sh`.
Full spec and architecture: [docs/SPEC.md](docs/SPEC.md).

## Roadmap (v2 — designs locked in [docs/SPEC.md](docs/SPEC.md) §5–6)

- **M5** ✅ server status in the menu bar + "model loading" awareness
- **M6** follow-up questions typed directly into the result panel
- **M7** persistent history window (searchable past Q/A) with embedded settings
- **M8** Liquid-Glass UI redesign (translucent, rounded, animated)
- **M9** external OpenAI-compatible API providers (for machines that can't host
  a local LLM; keys in the macOS Keychain)
- **M10** one-command onboarding installer + `macsist` CLI
  (`status / logs / doctor / restart / update`)

---

# Local LLM Server

The macOS app is a thin HTTP client. It assumes an OpenAI-compatible LLM server
is already running at `http://127.0.0.1:8000`. This document covers that server.

## What's installed

- **Miniforge3** (conda) at `/opt/homebrew/Caskroom/miniforge/base`
- conda env **`llm-server`** (Python 3.11) with `mlx-lm`, `mlx-vlm`, `fastapi`,
  `uvicorn`, `httpx`, `huggingface_hub`
- Models in the HF cache (`~/.cache/huggingface`):
  - `mlx-community/Qwen3.6-35B-A3B-4bit` — multimodal MoE, **explain default** (~19 GB)
  - `mlx-community/Qwen3.6-27B-4bit` — dense, **agent backbone** (future) (~15 GB)

## Architecture (3 processes)

```
app ──► :8000  proxy (FastAPI, server.py)
                 ├─ model id contains "Qwen3.6-27B" ─► :8002  mlx-lm  (dense)
                 └─ everything else                 ─► :8001  mlx-vlm (multimodal, text+vision)
```

The proxy streams SSE verbatim, so the app only ever talks to `:8000`. Switching
the `model` field in the request transparently routes to the right backend.

## Files

| Path | Role |
| --- | --- |
| `server/server.py` | FastAPI proxy: health, `/v1/models`, `/v1/chat/completions` routing |
| `server/start_server.sh` | Starts all 3 processes; `--supervise` mode for launchd |
| `server/download_models.sh` | One-time model download |
| `server/deploy.sh` | Copies scripts to a non-TCC location + (re)installs the LaunchAgent |
| `~/Library/LaunchAgents/com.hotkeyexplain.llm-server.plist` | Always-on at login |

> **Why deploy.sh exists:** `~/Documents` is a TCC-protected folder that launchd
> agents **cannot read** (`Operation not permitted`). `deploy.sh` copies the
> scripts to `~/Library/Application Support/HotkeyExplain/server/` (not protected)
> and points the LaunchAgent there. Re-run it after editing `server.py` or
> `start_server.sh`. The model cache (`~/.cache`) and logs (`~/Library/Logs`) are
> not TCC-protected, so backends load fine.

## Always-on (launchd)

Installed and running. The LaunchAgent starts the stack at login and, via
`KeepAlive`, restarts the whole stack if any backend dies (the `--supervise`
loop exits when a child dies). `ThrottleInterval` 30s prevents tight crash loops.

```bash
# status (column 1 = supervising bash PID; "-" means not running)
launchctl list | grep hotkeyexplain

# stop / start
launchctl bootout  "gui/$(id -u)/com.hotkeyexplain.llm-server"
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.hotkeyexplain.llm-server.plist

# re-deploy after editing scripts (does bootout+bootstrap for you)
~/Documents/macsist/server/deploy.sh
```

## Always-on (menu-bar app)

`app/deploy.sh` mirrors the server pattern: copies `app/*.py` to
`~/Library/Application Support/HotkeyExplain/app/` (launchd cannot read
`~/Documents`), builds a venv there, and installs
`~/Library/LaunchAgents/com.hotkeyexplain.app.plist` (RunAtLoad + KeepAlive).

TCC note: grants attach to the **deployed venv's python** — on first launch the
Accessibility prompt appears (startup check in `main.py`); grant it (plus Screen
Recording on first region capture) and restart:
`launchctl kickstart -k "gui/$(id -u)/com.hotkeyexplain.app"`. These grants are
one-time, unlike dev runs where they attach to the terminal host.

```bash
~/Documents/macsist/app/deploy.sh           # (re)deploy after editing app/*.py
tail -f ~/Library/Logs/HotkeyExplain/app.log
```

## Manual run (dev)

```bash
cd ~/Documents/macsist/server
./start_server.sh            # start all, return to shell
./start_server.sh --vlm-only # explain backend + proxy only (saves ~15 GB RAM)
```

First start loads both models into memory (~60–90 s). Subsequent starts are faster.

## Logs

```bash
tail -f ~/Library/Logs/llm-server/vlm.log     # 35B multimodal backend
tail -f ~/Library/Logs/llm-server/lm.log      # 27B dense backend
tail -f ~/Library/Logs/llm-server/proxy.log   # FastAPI proxy
tail -f ~/Library/Logs/llm-server/launchd.log # supervisor / launchd
```

## Smoke tests

```bash
# per-backend readiness: {"status":"ok"|"loading","backends":{"vlm":…,"lm":…}}
# (the menu-bar app polls this; "loading" while a backend loads its model)
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/v1/models

# text (explain default, 35B)
curl -sN http://127.0.0.1:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model":"mlx-community/Qwen3.6-35B-A3B-4bit","stream":true,"max_tokens":80,
  "messages":[{"role":"user","content":"트랜스포머 어텐션을 한 문장으로 설명해줘."}]}'
```

The vision path (OpenAI `image_url` with a `data:image/png;base64,...` URL) is
verified working against the 35B multimodal model — Option B (Python + mlx-vlm
fallback in the spec) is **not** needed.

## Notes / gotchas

- **27B is a thinking model** (emits `delta.reasoning` before any `content`).
  Handled: the app sends `chat_template_kwargs: {"enable_thinking": false}` by
  default *(config)*, renders thinking progress ("생각 중… N자") when reasoning
  deltas do arrive, and reports clearly if a stream ends content-less.
- **27B is text-only** — it rejects `image_url` content
  (`Only 'text' content type is supported`). Region capture therefore uses the
  separate `vision_model` config (default: the 35B).
- **HF auth:** logged in as `junidude14` (token cached in `~/.cache/huggingface`)
  for faster, rate-limit-free downloads.
- **Secrets:** `tokens_and_keys/` is chmod 700 and git-ignored. Never commit keys.
- **RAM:** both models loaded use a large share of the 128 GB. Use `--vlm-only`
  if you don't need the 27B.

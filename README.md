# Macsist

Native macOS **menu-bar assistant**. Its core feature, **HotkeyExplain**: press
a global hotkey to get a **concise Korean explanation** of whatever you have
**selected** (any app) or of a **screen region** you drag-select — streamed
token-by-token into a small floating panel near the cursor, from a **local**
LLM (MLX). No cloud, no Electron.

- **Text explain** (default `⌘⇧E`): reads the selection via Accessibility,
  falling back to a clipboard-safe synthetic ⌘C (clipboard is always restored).
- **Region explain** (default `⌘⇧R`): ⌘⇧4-style crosshair → the image goes to a
  local vision model.
- **Follow-up questions**: after an answer, type "이어서 질문…" directly in the
  panel — same conversation, same model (vision sessions keep the image).
- **Languages** (M11): 한국어/English/简体中文/日本語/Français/Deutsch — chosen
  during install, changeable in Settings (일반 → 언어), applies live to the UI
  and to the answer/translation language. Non-matching input gets a
  "번역:"/"Translation:"-style translation line first.
- **History** (menu-bar icon → History…, or `⌘⇧H` from anywhere): every
  completed explain is saved to
  `~/Library/Application Support/Macsist/history.jsonl`; region captures keep
  their screenshot in `history_images/` so they can be re-asked too. The
  window lists past Q/A newest-first with search; select a row for the full
  text, then 복사 or 다시 질문 (re-runs it with the current model — region
  rows re-send the saved screenshot), or delete a session with the ✕ on its
  card (immediate — removes its records and saved screenshot, M11). Saving is
  controlled by "기록 저장
  (전체)" with per-mode sub-toggles "이미지 저장" / "텍스트 저장"; "항상 위"
  keeps the window floating. While the window is open the app appears in
  Cmd-Tab (shown as "Python" until it ships as a bundle in M10).
- Settings (menu-bar icon, a tab of the History window): server URL,
  explain/vision models (picker from the server's loaded models), hotkey
  recorder, detail level (간단/보통/자세히), and a 고급 설정 flap (system
  prompts, temperature, max_tokens, …).
- Stack: Python 3.13 + PyObjC (AppKit), `pynput`, `httpx` SSE; server is
  MLX-backed (`mlx-lm` / `mlx-vlm`) behind a FastAPI proxy. Apple Silicon,
  macOS 26.2+.

## Install

```bash
./install.sh
```

One interactive (Korean) session does everything: hardware check → model
recommendation sized to your RAM (Qwen 3.6 / Gemma 4 multimodal tiers, or an
external OpenAI-compatible API for small machines) → miniforge/conda env →
model download (asks for an optional HF token) → server + app launchd agents →
`macsist` CLI → guided TCC grants → smoke test (a real explain round-trip).
Idempotent — re-run any time; finished steps are skipped.

Manual path (what the installer automates), for development or debugging:

```bash
server/download_models.sh   # one-time model download
server/deploy.sh            # server LaunchAgent
app/deploy.sh               # app LaunchAgent
```

On first launch grant **Accessibility** (prompted) and, on first region
capture, **Screen Recording**, then `macsist restart app`.
For development, run the app in the foreground instead with `app/run.sh`.
Full spec and architecture: [docs/SPEC.md](docs/SPEC.md).

## `macsist` CLI

Installed by `install.sh` as a symlink (`/usr/local/bin/macsist` or
`~/.local/bin/macsist`) pointing into the repo — works from any directory.

| Command | Does |
| --- | --- |
| `macsist` | ensure both agents are running, then status summary |
| `macsist start\|stop\|restart [app\|server]` | manage the launchd agents |
| `macsist status` | agents, server health, provider/models, TCC state |
| `macsist logs [app\|server] [-f]` | tail the right log files |
| `macsist settings` / `history` | open the main window (distributed notification) |
| `macsist doctor` | full ✓/✗ diagnosis: deploy, config, Keychain key, health, TCC, model cache |
| `macsist update` | `git pull --ff-only` + redeploy both agents |

## Roadmap (v2 — designs locked in [docs/SPEC.md](docs/SPEC.md) §5–6)

- **M5** ✅ server status in the menu bar + "model loading" awareness
- **M6** ✅ follow-up questions typed directly into the result panel
- **M7** ✅ persistent history window (searchable past Q/A) with embedded settings
- **M8** ✅ Liquid-Glass UI redesign (translucent, rounded, animated)
- **M9** ✅ external OpenAI-compatible API providers (for machines that can't
  host a local LLM; keys in the macOS Keychain)
- **M10** ✅ one-command onboarding installer + `macsist` CLI
  (`status / logs / doctor / restart / update`)
- **M11** ✅ per-card history deletion + 6-language support (UI + answer
  language, restart-free switching)

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
| `server/start_server.sh` | Starts the configured stack; `--supervise` mode for launchd |
| `server/download_models.sh` | Model download (`download_models.sh [<hf-id> …]`); resumable/idempotent |
| `server/deploy.sh` | Copies scripts to a non-TCC location + (re)installs the LaunchAgent |
| `~/Library/Application Support/Macsist/server/models.env` | Which models/stack to run (written by `install.sh`) |
| `~/Library/LaunchAgents/com.macsist.llm-server.plist` | Always-on at login |

Server models are **not hardcoded** (M10): `models.env` next to the deployed
`start_server.sh` sets `MACSIST_SERVER_MODE` (`full` = VLM+LM two-backend
stack, `vlm-only` = one multimodal model) plus `MACSIST_VLM_MODEL` /
`MACSIST_LM_MODEL`. No file → the historical defaults below. The proxy routes
a request to the LM backend only when that backend is part of the running
stack, so a stale model name in the app config degrades gracefully to the VLM.

> **Why deploy.sh exists:** `~/Documents` is a TCC-protected folder that launchd
> agents **cannot read** (`Operation not permitted`). `deploy.sh` copies the
> scripts to `~/Library/Application Support/Macsist/server/` (not protected)
> and points the LaunchAgent there. Re-run it after editing `server.py` or
> `start_server.sh`. The model cache (`~/.cache`) and logs (`~/Library/Logs`) are
> not TCC-protected, so backends load fine.

## Always-on (launchd)

Installed and running. The LaunchAgent starts the stack at login and, via
`KeepAlive`, restarts the whole stack if any backend dies (the `--supervise`
loop exits when a child dies). `ThrottleInterval` 30s prevents tight crash loops.

```bash
# status (column 1 = supervising bash PID; "-" means not running)
launchctl list | grep macsist

# stop / start
launchctl bootout  "gui/$(id -u)/com.macsist.llm-server"
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.macsist.llm-server.plist

# re-deploy after editing scripts (does bootout+bootstrap for you)
~/Documents/macsist/server/deploy.sh
```

## Always-on (menu-bar app)

`app/deploy.sh` (M12) builds a real **signed app bundle**: py2app standalone
build (requires `brew install python@3.13` — a framework-build Python; the
miniforge one is static and can't be embedded), signs it with the self-signed
"Macsist Signing" identity (created automatically on first deploy, no sudo),
installs it at `~/Library/Application Support/Macsist/Macsist.app` (launchd
cannot read `~/Documents`), and installs
`~/Library/LaunchAgents/com.macsist.app.plist` (RunAtLoad + KeepAlive) running
the bundle executable. Dock/Cmd-Tab and the TCC permission lists show
**Macsist** with its icon.

TCC note: grants attach to the **signed bundle** (bundle id + certificate, both
fixed) — so they survive every redeploy/`macsist update`. On first launch the
Accessibility prompt appears (startup check in `main.py`); grant it (plus Screen
Recording on first region capture) and restart:
`launchctl kickstart -k "gui/$(id -u)/com.macsist.app"`. These grants are
one-time, unlike dev runs where they attach to the terminal host.

```bash
~/Documents/macsist/app/deploy.sh           # (re)deploy after editing app/*.py
tail -f ~/Library/Logs/Macsist/app.log
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

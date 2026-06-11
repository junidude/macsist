# CLAUDE.md

> Kept intentionally lean (loaded every session). Full spec + milestones live in `docs/SPEC.md` — read it before planning any milestone.

## Project
Native macOS **menu-bar app** ("Hotkey Explain"). On a global hotkey it captures **selected text** or a **screen region (image)** and streams a **concise Korean explanation** from a **local OpenAI-compatible LLM server** (`http://127.0.0.1:8000`) into a floating panel near the cursor. Local-only; no cloud.

## Stack (locked — revised 2026-06: no Xcode on this machine; user chose Python over Swift)
- macOS **26.2+**, Apple Silicon. **Python 3.13 (miniforge) + PyObjC** (AppKit direct, no rumps).
- Menu bar via `NSStatusBar`; no Dock icon via `NSApp.setActivationPolicy_(Accessory)` (LSUIElement equivalent).
- Thin HTTP client (`httpx` SSE streaming) → separate local server (`/v1/chat/completions`, `stream: true`). **No** in-process MLX.
- Global hotkey: `pynput`.
- v1 modalities: text + vision. **No audio.** Output language: **Korean**.

## Models (config, not hardcoded)
- Explain default: `Qwen3.6-35B-A3B` (MLX 4-bit, multimodal). Alt for A/B: `Gemma-4-12B`.
- Future agent backbone: `Qwen3.6-27B`. Model id is a Settings field.

## Hard rules (do not violate)
- Save **and restore** `NSPasteboard` around any synthetic ⌘C. Never leave the clipboard clobbered.
- AX `kAXSelectedTextAttribute` first; **fall back to ⌘C** when AX is empty (Electron/web/Java apps).
- Result window: `.nonactivatingPanel` + `.floating`; must **never** steal focus from the source app.
- `screencapture -i` cancel (Esc / non-zero exit) = silent no-op, no error panel.
- New hotkey press cancels any in-flight request.
- Keep every tunable (server URL, model id, prompts, hotkeys, max_tokens) in Settings.

## Build / run
- Run: `app/run.sh` (creates `app/.venv` + installs `app/requirements.txt` on first run).
- The app assumes the LLM server is already running — see `README.md` (launchd LaunchAgent, always-on). Start it before testing M1+.
- Permissions needed at runtime: Accessibility + Screen Recording (handle missing grants gracefully). Dev caveat: TCC grants attach to the python host (terminal) when run from a shell.

## Workflow for this repo
- Use **plan mode** before each milestone (M0–M5 in `docs/SPEC.md`); propose the approach, then implement.
- Implement milestones **in order**; verify each milestone's acceptance criteria against a live `localhost:8000` server before moving on.
- `/clear` between milestones to keep context clean (project memory persists).

## Pointers
- Full spec, architecture diagram, API contract, milestones + acceptance criteria, gotchas: **`docs/SPEC.md`**.
- Server setup (Option A macMLX / Option B mlx-vlm): **`README.md`**.

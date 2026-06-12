# CLAUDE.md

> Kept intentionally lean (loaded every session). Full spec — current state,
> v2 feature designs, milestones, all gotchas — lives in `docs/SPEC.md`; read it
> before planning any milestone.

## Project
Native macOS **menu-bar app** ("macsist / HotkeyExplain"). Global hotkey →
captures **selected text** or a **screen region** → streams a **concise Korean
explanation** from an LLM (local MLX server at `http://127.0.0.1:8000` by
default; external OpenAI-compatible providers planned in M9) into a floating
panel near the cursor. **M0–M5 are shipped and running** (M5: menu-bar server
status, 서버 다운/모델 로딩 중 distinction, permission deep links); remaining
v2 work = M6–M10 (follow-up questions, history window, glass UI, providers,
onboarding installer + `macsist` CLI) — designs in `docs/SPEC.md` §5–6.

## Stack (locked)
- macOS **26.2+**, Apple Silicon. **Python 3.13 (miniforge) + PyObjC** (AppKit
  direct, no rumps). Menu bar via `NSStatusBar`, Accessory activation policy.
- Thin HTTP client (`httpx` SSE) → separate server (FastAPI proxy → mlx-lm /
  mlx-vlm). **No in-process MLX.** Global hotkeys: `pynput`.
- v1 modalities: text + vision. No audio. Output: **Korean**.
- Models are config, never hardcoded (defaults: Qwen3.6-35B-A3B multimodal;
  27B dense is **text-only** — vision uses the separate `vision_model`).

## Hard rules (do not violate — full list & rationale in SPEC §7)
- Key matching/recording by **virtual keycode only** (Korean layout: 'e'→'ㄷ').
- **Never start a new pynput listener after startup** (TIS APIs are
  main-thread-only on macOS 26 → SIGTRAP); use `HotkeyManager.rebind()`.
- Pasteboard: snapshot all items → ⌘C → poll changeCount → restore **only if
  changed**; captures serialized by lock. Never leave the clipboard clobbered.
- AX `kAXSelectedTextAttribute` first; fall back to synthetic ⌘C.
- Result panel never steals focus: `canBecomeKeyWindow` override +
  `setHidesOnDeactivate_(False)` + `orderFrontRegardless()` only.
- Cancel streams only via `StreamHandle.cancel()` (raw socket shutdown —
  `response.close()` cross-thread hangs).
- `screencapture` cancel = silent no-op (check returncode AND file size).
- New hotkey press preempts everything in flight (stream + region overlay).
- Staleness checks (request generation) happen on the **main thread**.
- Every tunable (URLs, models, prompts, hotkeys, tokens, sizes) in config.
- API keys (M9) go in the **Keychain**, never in config.json.

## Build / run / deploy
- Dev (foreground): `app/run.sh`. Prod: both app and server run as launchd
  agents — redeploy with `app/deploy.sh` / `server/deploy.sh`; restart with
  `launchctl kickstart -k "gui/$(id -u)/com.hotkeyexplain.app"`.
  Logs: `~/Library/Logs/HotkeyExplain/app.log`, `~/Library/Logs/llm-server/`.
- TCC: grants attach to the **deployed venv python** (dev runs: to the
  terminal/host). After granting Accessibility/Screen Recording → restart app.
- Verification: use the `HE_DEBUG_*` env hooks (SPEC §1) — computer-use cannot
  screenshot/type into this bundle-less app; see project memory
  `verify-ui-without-screenshots`.

## Workflow
- **Plan mode before each milestone** (M5–M10 in `docs/SPEC.md` §6); verify
  each milestone's acceptance criteria against the live setup before moving on.
- `/clear` between milestones (project memory persists).
- Repo: `github.com/junidude/macsist` (private). Commit/push after milestones.

## Pointers
- Spec, v2 designs, milestones, gotchas: **`docs/SPEC.md`**
- Server setup/ops, install, troubleshooting: **`README.md`**

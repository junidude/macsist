# CLAUDE.md

> Kept intentionally lean (loaded every session). Full spec — current state,
> v2 feature designs, milestones, all gotchas — lives in `docs/SPEC.md`; read it
> before planning any milestone.

## Project
Native macOS **menu-bar app** — product name **Macsist**; "HotkeyExplain" is
its hotkey-explain feature (legacy codename — `HE_DEBUG_*` hooks keep the
initialism; launchd labels/dirs are `com.macsist.*`, `…/Macsist/`). Global hotkey →
captures **selected text** or a **screen region** → streams a **concise
explanation in the configured language** (ko/en/zh/ja/fr/de — M11; UI strings
+ prompts via `app/i18n.py`, prompt keys resolve per `language` in config)
from an LLM (local MLX server at `http://127.0.0.1:8000` by
default, or any external OpenAI-compatible provider — M9) into a floating
panel near the cursor. **M0–M12 are shipped and running — v2 complete**
(M7: JSONL history +
History/Settings main window; M8 + M8.1: Liquid Glass UI — `NSGlassEffectView`
panel (`glass_enabled`/`glass_style` in config), 150ms fade, auto-height,
chatbot-style main window (chat bubbles + session cards + glass sidebar
island), Codex-style Settings sections, custom icons in `app/assets/`, ⌘W
close, region panel centered on the captured selection; M9: `providers` list
+ `active_provider` in config, keys in Keychain via `app/keychain.py`,
provider picker in Settings 연결, restart-free switching, provider-named
errors; M10: `install.sh` Korean-TUI onboarding installer — RAM-tiered model
recommendation with HF-verified catalog, server models in `models.env` — and
the `macsist` CLI: status/start/stop/restart/logs/settings/history/doctor/
update; M11: per-card history deletion + 6-language i18n with restart-free
switching; M12: real signed **Macsist.app** bundle — py2app standalone build
(brew python@3.13 framework build; the miniforge python is static → build-only
unusable), fixed self-signed "Macsist Signing" identity so TCC survives every
redeploy, installed at `…/Application Support/Macsist/Macsist.app`, launchd
runs the bundle executable — as-built notes in `docs/SPEC.md` §5.5–5.8).
**M13–M14 shipped** — the **Assistant** subsystem (`app/assistant/`): M13
read-only kanban cockpit over Hermes (`hermes_bridge` = RO `~/.hermes/kanban.db`
+ `hermes` CLI, never writes the DB) + 작업 tab + menu-bar badge; M14
propose-then-confirm engine (local M9 brain, zero Hermes-gateway dependency) —
work threads ("어디까지 했더라"), deterministic `kind→risk` + structural
`assert_approved` gate (no side effect without a user approval row),
ProposalPanel, `macsist propose|approve|scan|inbox|tasks`. Full design + the
M15–M18 roadmap (Telegram / remote Claude Code·Codex / Gmail / Calendar):
**`docs/ASSISTANT.md`**.

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
  Same root cause: keep `NSSystemDefined` stripped from the tap mask
  (M11.1 — 한/A·caps-lock NSEvent conversion SIGTRAPs the listener thread).
- Pasteboard: snapshot all items → ⌘C → poll changeCount → restore **only if
  changed**; captures serialized by lock. Never leave the clipboard clobbered.
- AX `kAXSelectedTextAttribute` first; fall back to synthetic ⌘C.
- Result panel never steals focus: `canBecomeKeyWindow` override (M6: True
  only while the follow-up input is focused — app still never activates) +
  `setHidesOnDeactivate_(False)` + `orderFrontRegardless()` only.
- Cancel streams only via `StreamHandle.cancel()` (raw socket shutdown —
  `response.close()` cross-thread hangs).
- `screencapture` cancel = silent no-op (check returncode AND file size).
- New hotkey press preempts everything in flight (stream + region overlay).
- Staleness checks (request generation) happen on the **main thread**.
- Every tunable (URLs, models, prompts, hotkeys, tokens, sizes) in config.
- API keys (M9) go in the **Keychain**, never in config.json.
- Bundle (M12): **never ad-hoc sign** (per-build CDHash resets TCC), never
  change `CFBundleIdentifier`; assets via `config.asset_dir()` (RESOURCEPATH),
  self-relaunch via `EXECUTABLEPATH` env (in-bundle `sys.executable` is the
  embedded CLI python, not the app stub); copy bundles with `ditto` only.
  Full packaging gotchas: SPEC §7.13.

## Build / run / deploy
- Dev (foreground): `app/run.sh`. Prod: both app and server run as launchd
  agents. Preferred ops (M10): `macsist restart|status|logs|doctor` and
  `macsist update`; redeploy directly with `app/deploy.sh` / `server/deploy.sh`.
  Fresh machine: `./install.sh`.
  Logs: `~/Library/Logs/Macsist/app.log`, `~/Library/Logs/llm-server/`.
  Server models/stack: `…/Application Support/Macsist/server/models.env`
  (absent = historical defaults; owned by install.sh, preserved by deploy).
  App deploys build the bundle: prerequisite `brew install python@3.13`
  (deploy.sh dies with that hint if missing; install.sh installs it).
- TCC: grants attach to the **signed bundle** (M12 — csreq: bundle id + the
  "Macsist Signing" leaf cert, so redeploys keep them; dev runs still attach
  to the terminal/host). After granting → restart app (`macsist restart app`).
- Verification: use the `HE_DEBUG_*` env hooks (SPEC §1) — computer-use still
  cannot reach the app even after M12 (allowlist resolver doesn't index apps
  outside /Applications); see project memory `verify-ui-without-screenshots`.

## Workflow
- **Plan mode before each milestone** (M5–M10 in `docs/SPEC.md` §6); verify
  each milestone's acceptance criteria against the live setup before moving on.
- `/clear` between milestones (project memory persists).
- Repo: `github.com/junidude/macsist` (private). Commit/push after milestones.

## Pointers
- Spec, v2 designs, milestones, gotchas: **`docs/SPEC.md`**
- Server setup/ops, install, troubleshooting: **`README.md`**

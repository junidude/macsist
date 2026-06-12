# SPEC.md — "macsist / HotkeyExplain" (local-LLM macOS assistant)

> v2 spec, revised **2026-06-12**. v1 (M0–M4) is **shipped and running**; this
> document records what exists, the engineering invariants learned while
> building it, and the design for the v2 feature set (M5–M10).
> Decisions below are **locked** — implement them, do not relitigate. Where a
> value is marked *(config)*, expose it in Settings instead of hardcoding.

---

## 0. One-paragraph brief

A native macOS **menu-bar app**. On a global hotkey it captures the user's
**selected text** in any app, or a **screen region as an image**, sends it to an
**LLM server** (local MLX by default, external OpenAI-compatible API optional in
v2), and **streams a concise Korean explanation** into a small floating glass
panel near the cursor. v2 adds **follow-up questions** in the panel, a
**persistent history window** (with embedded settings), an **onboarding
installer**, and a **`macsist` CLI launcher**. No Electron.

---

## 1. Current state (v1, shipped)

### Working features
- **Text explain** — hotkey → AX `kAXSelectedTextAttribute` → fallback synthetic
  ⌘C with full clipboard snapshot/restore → streamed Korean explanation in a
  non-activating floating panel near the cursor.
- **Region explain** — hotkey → `screencapture -i` (⌘⇧4-style) → PNG → sips
  downscale (>`region_max_dim`) → base64 `image_url` → vision model → panel.
- **Streaming panel** — never steals focus, Esc/click-away dismiss, thinking
  progress ("생각 중… N자") for reasoning models, clean one-line Korean errors.
- **Cancellation** — any hotkey press preempts everything in flight (stream +
  pending region overlay). Panel dismiss also cancels.
- **Settings window** — server URL; explain/vision model comboboxes populated
  live from `/v1/models` (free text works when server is down); hotkey
  recorder (click → press combo, keyCode-based); detail level (간단/보통/자세히)
  changing prompt suffix + max_tokens. **고급 설정 flap**: both system prompts
  (default is translate-first — non-Korean input gets a '번역:' line before
  the explanation), image user prompt, temperature, max_tokens, follow-up turn
  cap, `chat_template_kwargs` as JSON — validated on Save (invalid input
  blocks the whole save with a ⚠ message), "고급 기본값 복원" resets the
  fields to shipped defaults. Stale-default migration: if an on-disk value
  still equals a superseded old default the user never touched, the new
  default wins (`config._SUPERSEDED_DEFAULTS`).
- **Thinking models** — `delta.reasoning` handled; `chat_template_kwargs:
  {"enable_thinking": false}` sent by default *(config)*.
- **Always-on** — both the LLM server and the app run as launchd LaunchAgents
  (`com.hotkeyexplain.llm-server`, `com.hotkeyexplain.app`), auto-start at
  login, auto-restart on crash. `app/deploy.sh` / `server/deploy.sh` redeploy.
- **Server status (M5)** — proxy `/health` probes both backends
  (`{"status":"ok"|"loading","backends":{"vlm":…,"lm":…}}`; expected set via
  `HE_EXPECTED_BACKENDS`, set by `start_server.sh` per mode). Menu bar shows a
  3-state icon (`text.bubble` / `ellipsis.bubble` / `exclamationmark.bubble`)
  + a disabled "서버: …" status line, fed by `ServerHealthMonitor` (daemon
  thread polling every `health_poll_interval`; `poke()` re-polls right after a
  request error). Proxy answers `503 {"error":{"code":"model_loading"}}` when
  the routed backend isn't accepting connections → panel says "모델 로딩 중",
  vs ConnectError → "서버 다운". Permission onboarding: missing-permission
  errors auto-open the exact System Settings pane (once per run per pane), and
  at startup without Accessibility the app polls the grant every 2 s and
  exec-relaunches itself once granted.
- **Follow-up questions (M6)** — after an explanation finishes (or errors), a
  bottom input row ("이어서 질문…") appears in the panel. Clicking it makes the
  panel key Spotlight-style (conditional `canBecomeKeyWindow`, app never
  activates); Return streams a contextual answer into the same transcript
  (❯-prefixed question lines); conversation retained per session
  (`followup_max_turns` cap, same model as the original request — vision
  sessions keep the image). First Esc leaves the field (key handed back via
  orderOut+orderFrontRegardless), second Esc dismisses; first follow-up grows
  the panel to `panel_height_expanded`; any hotkey press starts a fresh session.

### File map (`app/`)
| File | Role |
| --- | --- |
| `main.py` | NSApplication entry (Accessory policy), startup AX-permission prompt, wiring |
| `menubar.py` | status item + menu |
| `hotkeys.py` | pynput listener; **vk-based matching** (`_VkHotKey`), `format_binding`, pause/rebind, TIS main-thread patch |
| `text_capture.py` | AX read → synthetic-⌘C fallback (capture lock, restore-only-if-changed, Maccy modifier recipe) |
| `region_capture.py` | `screencapture -i` subprocess, PNG IHDR dims, `sips -Z` downscale, data-URL |
| `llm_client.py` | httpx SSE client; `StreamHandle.cancel()` (raw socket shutdown); `on_reasoning`; per-call `model`/`max_tokens` override; 503 `model_loading` → "모델 로딩 중" |
| `health.py` | `ServerHealthMonitor` — `/health` polling thread, ok/loading/down, `poke()` |
| `result_panel.py` | floating panel — never-key except while the follow-up input is focused (`_allow_key` gate, M6); NSEvent monitors for dismiss/click-to-focus/two-stage Esc; streaming transcript + bottom input row |
| `explain_controller.py` | hotkey → worker thread → `callAfter`; generation counter (main-thread staleness check); global preemption; M6 follow-up session (`_session`, `submitFollowUp`, turn capping) |
| `settings_window.py` | settings UI (combos / recorders / detail segments) |
| `config.py` | JSON store at `~/Library/Application Support/HotkeyExplain/config.json` |
| `run.sh` / `deploy.sh` | dev run / launchd deploy |

### Config reference (all tunables live here)
`server_base_url`, `explain_model`, `vision_model`, `alt_model`, `agent_model`,
`system_prompt_text`, `system_prompt_image`, `user_prompt_image`,
`explain_detail` + `detail_levels` (label / prompt_suffix / max_tokens),
`hotkey_explain_text` (default `<cmd>+<shift>+e`), `hotkey_explain_region`
(default `<cmd>+<shift>+r`), `max_tokens`, `temperature`,
`chat_template_kwargs`, `request_connect_timeout`, `request_read_timeout`,
`capture_copy_timeout`, `capture_modifier_release_timeout`, `capture_max_chars`,
`region_max_dim`, `panel_width`, `panel_height`, `panel_height_expanded`,
`panel_cursor_offset`, `followup_max_turns`,
`health_poll_interval`, `health_poll_timeout`.

### Debug hooks (env vars, kept for agent-driven verification)
`HE_DEBUG_EXPLAIN_AFTER` / `HE_DEBUG_EXPLAIN_REGION_AFTER` (comma-separated
seconds — fire hotkey paths programmatically), `HE_DEBUG_FAKE_TEXT` (bypass
capture), `HE_DEBUG_REGION_RECT="x,y,w,h"` (bypass interactive overlay),
`HE_DEBUG_KEEP_PANEL` (don't install dismiss monitors — note: also disables
M6 click-to-focus, which lives in the local monitor), `HE_DEBUG_FRAME`,
`HE_DEBUG_OPEN_MENU`, `HE_DEBUG_OPEN_SETTINGS` (seconds — open the settings
window), `HE_DEBUG_WIN_ORIGIN="x,y"`,
`HE_DEBUG_FOLLOWUP_AFTER` (comma-separated seconds — submit a follow-up
programmatically) + `HE_DEBUG_FOLLOWUP_TEXT` (its question),
`HE_DEBUG_FOLLOWUP_KEYCYCLE` (seconds — focus the input, log key/first-responder
state, unfocus, log handback state).

---

## 2. Locked platform decisions

- **Target:** macOS **26.2+**, Apple Silicon only. Dev machine: M5 Max / 128 GB.
- **Language/UI:** **Python 3.13 + PyObjC** (AppKit direct, no rumps). Menu bar
  via `NSStatusBar`; `NSApp.setActivationPolicy_(Accessory)` (no Dock icon).
  *(v2: a thin compiled launcher for the `macsist` CLI is allowed; the app
  itself stays Python.)*
- **Serving model:** thin HTTP client → separate server process, OpenAI-compatible
  `http://127.0.0.1:8000` (FastAPI proxy → `mlx-lm` :8002 / `mlx-vlm` :8001).
  **No in-process MLX.** v2 adds external OpenAI-compatible providers (§5.4).
- **Modalities:** text + vision. No audio.
- **Output:** Korean, concise, streamed.
- **Hotkeys:** `pynput`, but **matching MUST be by virtual keycode** — see §7.1.

### Models (config, with defaults)
- Explain default: `mlx-community/Qwen3.6-35B-A3B-4bit` (multimodal MoE).
- Vision default: same 35B (`vision_model` is separate config — the explain
  model may be a text-only pick like the 27B).
- Alt explain (A/B): `Gemma-4-12B` (not yet in the server pool).
- Agent backbone (future): `Qwen3.6-27B` dense — **text-only**, rejects
  `image_url` content.

---

## 3. Architecture (v2)

```
[Global hotkey (pynput, vk-match)]
   |
   +-- explainText  --> TextCapture  (AX | synthetic-⌘C + restore)
   +-- explainRegion --> RegionCapture (screencapture -i → PNG → ≤1600px → b64)
                              |
                    ExplainController (worker thread/request, gen counter,
                              |        global preemption, callAfter marshal)
                              |
                    LLMClient --(SSE)--> Provider (§5.4)
                              |            ├─ local proxy :8000 → mlx-lm / mlx-vlm
                              |            └─ external OpenAI-compatible API
                              v
                    ResultPanel (glass, non-activating, streaming)
                              |  └─ follow-up input (§5.1) → same conversation
                              v
                    HistoryStore (§5.2) ←→ History/Main window (+ Settings tab)
```

---

## 4. API contract

`POST {base_url}/v1/chat/completions`, `stream: true`. Parse SSE `data:` lines;
`choices[0].delta.content` → render; `delta.reasoning` (or
`reasoning_content`) → thinking progress, never rendered as content;
`data: [DONE]` → end. Ignore non-`data:` lines (keepalives).

- **Text mode:** `[{role: system, content: system_prompt_text + detail suffix},
  {role: user, content: <captured text>}]`
- **Vision mode:** user content is the OpenAI multimodal array
  (`{"type":"image_url","image_url":{"url":"data:image/png;base64,…"}}`),
  model = `vision_model`.
- **Follow-up (v2):** append `{role: assistant, content: <answer so far>}` +
  `{role: user, content: <question>}` to the same message list; model unchanged
  from the session that started it.
- `chat_template_kwargs` *(config)* is sent when non-empty (local MLX servers;
  **strip it for external providers** — they reject unknown fields. §5.4).
- Errors are raised as `LLMError` with a clean one-line Korean message; never
  show tracebacks in UI.

---

## 5. v2 feature designs

### 5.1 Follow-up questions (M6)
After an explanation finishes (or errors), the panel shows a **single-line text
input** pinned to its bottom edge ("이어서 질문…"). Typing requires key status:
the panel's `canBecomeKeyWindow` returns **True only while the input field is
the intended first responder** (Spotlight-style: NonactivatingPanel + key gives
typing without activating our app; the source app keeps visual focus).
- Submit (Return) → append Q to the transcript view, stream the answer below;
  conversation = original explain messages + assistant answer + follow-ups
  (capped by `followup_max_turns` *(config)*, oldest dropped).
- Esc in the input: first clears/leaves the field (panel back to never-key),
  second dismisses the panel. Click-away still dismisses (and ends the session).
- New hotkey press = new session (preempts, as today).
- The panel grows to `panel_height_expanded` *(config)* when a follow-up session
  starts.

### 5.2 History + main window (M7)
- **Store:** JSONL at `~/Library/Application Support/HotkeyExplain/history.jsonl`
  (append-only; one record per completed request: ts, mode
  text/region/followup, model, input snippet ≤`history_snippet_chars`, full
  response, detail level). Region mode stores the prompt + response, **not the
  image** (size). `history_enabled` + `history_max_items` *(config)*; pruning
  rewrites the file.
- **Window:** a regular activating window (toggled from the menu bar, optional
  "항상 위" floating toggle), list of past Q/A newest-first with search field;
  click a row → expand full text, buttons: copy, re-ask (re-runs with current
  model). Sidebar or tab switches to **Settings** — the existing settings
  controls move here (server/provider, models, hotkeys, detail, and the
  advanced flap — system prompts/temperature/max_tokens etc., already
  shipped in the settings window; M7 only relocates it).
- The menu bar menu gains: History/Settings 열기, server status line (M5).

### 5.3 Glass UI (M8)
- Adopt the macOS 26 **Liquid Glass** look: `NSGlassEffectView` where available
  (PyObjC `objc.lookUpClass` guard), falling back to `NSVisualEffectView`
  (`.hudWindow` material) — the panel already uses the latter.
- Panel: continuous-corner radius (16pt), thin 1px `separatorColor` border,
  SF Pro text (13pt body), subtle shadow, fade-in/out (`NSAnimationContext`,
  150ms), auto-height up to `panel_height` before scrolling.
- History window: translucent sidebar (source-list material), glass toolbar.
- All chrome respects light/dark via semantic colors (`labelColor` etc. — never
  hardcoded RGB).

### 5.4 External API providers (M9)
For users whose machines can't host a local LLM.
- Config: `providers` — ordered list of `{name, base_url, api_key_env_or_value,
  explain_model, vision_model, is_local}` + `active_provider`. The current
  local setup becomes the first entry (`is_local: true`).
- Any **OpenAI-compatible** endpoint works (OpenAI, Gemini-OpenAI-compat,
  OpenRouter, Groq, Together…). `Authorization: Bearer <key>` header when a key
  is set. `chat_template_kwargs` is sent **only** to `is_local` providers.
- API keys: stored in the **macOS Keychain** (`security add-generic-password`),
  config holds only the item name. Never write keys to config.json.
- Settings UI: provider picker + add/edit form (base URL, key, models w/ the
  live `/v1/models` fetch when the endpoint supports it); per-provider model
  fields. Switching provider applies to the next request (no restart).
- Errors must say which provider failed.

### 5.5 Onboarding installer (M10a)
`install.sh` at repo root (curl-able one-liner once public):
interactive TUI (plain bash + read prompts; Korean) that walks through:
1. Hardware check — Apple Silicon? RAM? (`sysctl hw.memsize`) → recommend
   **local** (≥48 GB), **lighter local model** (16–48 GB), or **external API**
   (<16 GB / user choice).
2. Local path: miniforge check/install → `server/download_models.sh` (with
   size warnings) → `server/deploy.sh`. API path: provider/key prompt → write
   config via a small python helper.
3. `app/deploy.sh`, then guided TCC grants (open the exact System Settings
   panes, wait-and-recheck loop, `launchctl kickstart` when granted).
4. Smoke test: scripted explain round-trip; print "⌥E를 눌러보세요" equivalent
   for the user's bindings.
Idempotent — safe to re-run; each step detects "already done".

### 5.6 `macsist` CLI (M10b)
A launcher command on PATH (installed by `install.sh` into
`/usr/local/bin/macsist` or `~/.local/bin`): a small **bash/Python** dispatcher
(Rust single-binary is allowed later if distribution demands it; not required).
```
macsist            # ensure server+app launchd agents are running; status summary
macsist start|stop|restart [app|server]
macsist status     # agents, /health, model list, TCC grants
macsist logs [app|server] [-f]
macsist settings   # open the Settings/History window (via a distributed
                   # notification or a tiny localhost control endpoint)
macsist doctor     # diagnose: TCC, launchd, server health, config validity
macsist update     # git pull + redeploy both agents
```

---

## 6. Milestones

Each must pass its acceptance criteria against a live setup before moving on.
Workflow per milestone: `/clear` → plan mode → implement → verify (use the
debug hooks; computer-use cannot type into the bundle-less app — see project
memory `verify-ui-without-screenshots`).

- **M0–M4 — DONE** (scaffold, client, text explain, region explain,
  settings/model picker/hotkey recorder/detail levels).
- **M5 — Robust status. DONE.** Proxy `/health` reports per-backend readiness;
  menu bar shows server state (ok / loading / down); panel messages distinguish
  "서버 다운" from "모델 로딩 중". Permission onboarding polish (deep links,
  poll-and-relaunch on grant — Accessory apps get no focus events, so the
  "re-check on focus" became a 2 s poll).
  *AC verified live (2026-06-12):* kill → app saw `down` ≤10 s, hotkey panel
  says "서버 다운 —…"; restart → `/health` reports `loading` during model load
  (warm-cache window is ~3 s, so the in-app `loading` flip was verified at the
  mapping level), then `ok`; chat during load gets a clean
  `503 model_loading` → "모델 로딩 중입니다".
- **M6 — Follow-up questions** (§5.1). **DONE (2026-06-12).**
  *AC verified:* automated (HE_DEBUG hooks) — follow-up streams a contextual
  answer into the same panel for text AND vision sessions; conversation capped
  (`followup_max_turns`, oldest pair dropped, system kept); errors show the
  input too and follow-up errors append without wiping the transcript
  (synthetic assistant message keeps user/assistant alternation); new hotkey
  resets to a fresh session at default panel size; key cycle — focus → panel
  key (field editor first responder), unfocus → key returns to source app
  (orderOut+orderFrontRegardless handback), panel stays visible. Live human
  input confirmed (2026-06-12): click-to-focus, typed Korean + Return submit,
  source app keeps working during the follow-up, Esc/Esc two-stage dismiss,
  IME-composition Esc (cancels the 조합, not the field). **Fully verified.**
- **M7 — History + main window** (§5.2). System-prompt/advanced editing already
  ships in the settings window (고급 설정 flap) — M7 relocates the existing
  settings controls into this window's Settings tab, no new editing UI.
  *AC:* past explains searchable in the window; settings edits there apply
  without restart; history survives app restart; disable toggle works.
- **M8 — Glass UI** (§5.3).
  *AC:* panel + history window render with glass material, rounded corners,
  fade animations, correct light/dark; no regression in never-steal-focus.
- **M9 — External providers** (§5.4).
  *AC:* add an OpenRouter (or OpenAI) provider with a key → explain works with
  the local server stopped; key lives in Keychain; switching back needs no
  restart.
- **M10 — Onboarding + CLI** (§5.5–5.6).
  *AC:* on a machine state simulating "nothing installed", `install.sh` reaches
  a working explain in one session (both the local and the API path);
  `macsist status|logs|doctor|restart` work from any directory.

---

## 7. Engineering invariants & gotchas (learned the hard way — do not regress)

1. **Korean input source:** pynput delivers layout-mapped chars (`e` → `ㄷ`) —
   any key matching/recording MUST use `key.vk` / `keyCode()`, never the
   character. (`hotkeys.py` `_VkHotKey`, settings recorder.)
2. **TIS/TSM APIs are main-thread-only on macOS 26** (`dispatch_assert_queue`
   SIGTRAP). pynput's listener startup touches them off-main → the layout
   context is snapshotted once on the main thread and patched in
   (`_warm_keyboard_layout_cache`). **Never create/start a new pynput listener
   after startup** — `HotkeyManager.rebind()` swaps matchers on the live
   listener instead.
3. **Clipboard hard rule:** snapshot ALL pasteboard items (data copied before
   ⌘C), restore **only if changeCount actually changed**, serialize captures
   with a lock (concurrent captures clobber the user's clipboard).
4. **Synthetic ⌘C vs held hotkey modifiers:** wait for Shift release (≤300 ms),
   suppression filter + explicit `CGEventSetFlags` on down AND up (Maccy
   recipe). No synthetic modifier key-ups, no private event source.
5. **Never-steal-focus panel:** `NonactivatingPanel` mask alone is NOT enough —
   override `canBecomeKeyWindow` (False in v1; conditional for §5.1).
   `setHidesOnDeactivate_(False)` is mandatory (Accessory apps deactivate
   constantly). Show with `orderFrontRegardless()` only. Dismiss via global +
   local NSEvent monitors (panel gets no keyDown).
6. **Thinking models** stream `delta.reasoning` first and can burn the whole
   `max_tokens` with zero content — handle the field, disable thinking via
   `chat_template_kwargs` for local servers, and message clearly when a stream
   ends content-less.
7. **Cross-thread stream cancel:** `response.close()` from another thread hangs;
   `StreamHandle` does a raw `socket.shutdown()` (llm_client.py docstring).
   Do not bypass it.
8. **launchd + TCC:** agents cannot read `~/Documents` → deploy copies to
   `~/Library/Application Support/HotkeyExplain/`. TCC grants attach to the
   **deployed venv python**; Accessibility/Screen Recording grants require an
   app **restart** to take effect (`launchctl kickstart -k`). Dev-shell runs
   attach grants to the terminal/host app instead.
9. **`screencapture -i`:** Esc → exit ≠ 0, no file; ^C-to-clipboard → exit 0,
   no file → success check is returncode AND file-size. Cancel = silent no-op.
   Without Screen Recording it writes wallpaper-only images with exit 0 —
   preflight with `CGPreflightScreenCaptureAccess()`, don't capture-and-detect.
10. **Hotkeys are listen-only** (no suppression): the chord also reaches the
    front app — document defaults that collide (⌘⇧R = Chrome hard-reload), let
    users re-record.
11. **Staleness:** every UI update carries its request generation and is checked
    on the **main thread**; worker-side checks alone race the next hotkey.
12. **macOS 26 `screencapture` thumbnails/flags:** `-u` opts INTO UI (never
    pass); `-o` only affects window-mode shadows; CLI has no thumbnail.

---

## 8. Repo layout

```
macsist/
  app/                  menu-bar app (PyObjC) — see §1 file map
  server/               FastAPI proxy + mlx backends, launchd deploy
  docs/SPEC.md          this file
  README.md             user-facing: install, server ops, troubleshooting
  CLAUDE.md             agent instructions (lean)
  install.sh            (M10) onboarding installer
  cli/macsist           (M10) CLI dispatcher
```

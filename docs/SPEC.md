# SPEC.md — "Macsist" (local-LLM macOS assistant)

> Naming (since 2026-06-12): **Macsist** is the product — window title, menu,
> launchd labels `com.macsist.*`, data dir `~/Library/Application Support/
> Macsist/`, logs `~/Library/Logs/Macsist/`. **HotkeyExplain** is its
> hotkey-explain *feature* (and the pre-M8 codename — the `HE_DEBUG_*` hook
> prefix and `HE_EXPECTED_BACKENDS` keep that initialism on purpose).
> `config.py` auto-migrates config.json/history.jsonl from the legacy
> HotkeyExplain dir on first run.

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
- **Settings** (M7: a tab of the History/main window — `SettingsPaneController`
  builds into the tab's view, no standalone window) — server URL; explain/vision
  model comboboxes populated
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
  (`com.macsist.llm-server`, `com.macsist.app`), auto-start at
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
- **History + main window (M7)** — every completed request (text/region/
  followup, success or partial; content-less errors skipped) appends one JSONL
  record to `~/Library/Application Support/Macsist/history.jsonl`
  (ts/mode/model/input/response/detail; region records also save their capture
  PNG to `history_images/` and reference it by filename — base64 never enters
  the JSONL). Written from `_commitSession` (main thread); pruned by
  atomic file rewrite past `history_max_items` (orphaned images deleted). The
  menu bar's History…/
  Settings… open a regular activating window (NSTabView): History tab =
  master-detail (search field filtering input+response, newest-first table,
  full Q/A detail pane, 복사 / 다시 질문 — re-ask re-runs the stored input
  with the current model; region records re-send their saved PNG through the
  vision pipeline, disabled only when no image file exists), save toggles
  "기록 저장 (전체)" (`history_enabled`, master) with per-mode sub-toggles
  "이미지 저장" (`history_save_images`) / "텍스트 저장" (`history_save_text`),
  and "항상 위" (`history_window_floating` → NSFloatingWindowLevel); the list
  live-refreshes while visible (`HistoryStore.on_appended`). Cmd-Tab: while
  the window is open the app switches to the **Regular** activation policy
  (Dock + Cmd-Tab; name shows as "Python" until the M10 bundle) and reverts to
  Accessory on close; a global hotkey (`hotkey_open_history`, default ⌘⇧H,
  recordable in Settings) toggles the window from anywhere.

### File map (`app/`)
| File | Role |
| --- | --- |
| `main.py` | NSApplication entry (Accessory policy), startup AX-permission prompt, wiring |
| `menubar.py` | status item + menu |
| `hotkeys.py` | pynput listener; **vk-based matching** (`_VkHotKey`), `format_binding`, pause/rebind, TIS main-thread patch |
| `text_capture.py` | AX read → synthetic-⌘C fallback (capture lock, restore-only-if-changed, Maccy modifier recipe) |
| `region_capture.py` | `screencapture -i` subprocess, PNG IHDR dims, `sips -Z` downscale, data-URL |
| `llm_client.py` | httpx SSE client; `StreamHandle.cancel()` (raw socket shutdown); `on_reasoning`; per-call `model`/`max_tokens` override; M9: resolves `active_provider()` per request (Bearer auth via keychain, `chat_template_kwargs` local-only, provider-named errors, 503 `model_loading` → "모델 로딩 중") |
| `health.py` | `ServerHealthMonitor` — polling thread, ok/loading/down, `poke()`; M9: local providers `GET /health`, external authed `GET /v1/models` |
| `keychain.py` | M9 — `security` CLI wrapper (`set/get/delete_key`, `resolve_key`: ""/`env:VAR`/account); keys never in config/logs |
| `result_panel.py` | floating panel — never-key except while the follow-up input is focused (`_allow_key` gate, M6); NSEvent monitors for dismiss/click-to-focus/two-stage Esc; streaming transcript + bottom input row |
| `explain_controller.py` | hotkey → worker thread → `callAfter`; generation counter (main-thread staleness check); global preemption; M6 follow-up session (`_session`, `submitFollowUp`, turn capping); M7 history commit + `resubmit_text` (re-ask) |
| `settings_window.py` | `SettingsPaneController` — settings controls built into a host view (combos / recorders / detail segments / 고급 flap); window-less since M7 |
| `main_window.py` | `MainWindowController` — History/Settings window (NSTabView, master-detail history list, search, copy/re-ask, 기록 저장·항상 위 toggles) |
| `history_store.py` | `HistoryStore` — append-only JSONL, main-thread-only, atomic prune/rewrite + `delete_records` (M11) |
| `i18n.py` | M11 — UI strings (6 languages) + per-language prompt defaults; `t()` / `set_language()`; pure data, stdlib-only |
| `config.py` | JSON store at `~/Library/Application Support/Macsist/config.json`; prompt keys resolve per `language` (M11, §5.7) |
| `run.sh` / `deploy.sh` | dev run / launchd deploy |

### Config reference (all tunables live here)
`providers` (M9 — ordered `{name, base_url, api_key_env_or_value,
explain_model, vision_model, is_local}` entries; pre-M9 `server_base_url`/
`explain_model`/`vision_model` are auto-migrated into `providers[0]`),
`active_provider` (name), `alt_model`, `agent_model`,
`system_prompt_text`, `system_prompt_image`, `user_prompt_image`,
`explain_detail` + `detail_levels` (label / prompt_suffix / max_tokens),
`hotkey_explain_text` (default `<cmd>+<shift>+e`), `hotkey_explain_region`
(default `<cmd>+<shift>+r`), `hotkey_open_history` (default `<cmd>+<shift>+h`
— toggles the History window), `max_tokens`, `temperature`,
`chat_template_kwargs`, `request_connect_timeout`, `request_read_timeout`,
`capture_copy_timeout`, `capture_modifier_release_timeout`, `capture_max_chars`,
`region_max_dim`, `panel_width`, `panel_height`, `panel_height_expanded`,
`panel_cursor_offset`, `followup_max_turns`,
`health_poll_interval`, `health_poll_timeout`,
`health_poll_timeout_external` (M9 — external providers are health-checked
via authed `GET /v1/models` over the internet),
`history_enabled` (master) / `history_save_text` / `history_save_images`
(per-mode), `history_max_items`, `history_snippet_chars`
(= `capture_max_chars` by default so text inputs are stored losslessly for
re-ask), `history_window_floating`.

### Debug hooks (env vars, kept for agent-driven verification)
`HE_DEBUG_EXPLAIN_AFTER` / `HE_DEBUG_EXPLAIN_REGION_AFTER` (comma-separated
seconds — fire hotkey paths programmatically), `HE_DEBUG_FAKE_TEXT` (bypass
capture), `HE_DEBUG_REGION_RECT="x,y,w,h"` (bypass interactive overlay),
`HE_DEBUG_KEEP_PANEL` (don't install dismiss monitors — note: also disables
M6 click-to-focus, which lives in the local monitor), `HE_DEBUG_FRAME`,
`HE_DEBUG_OPEN_MENU`, `HE_DEBUG_OPEN_SETTINGS` / `HE_DEBUG_OPEN_HISTORY`
(seconds — open the main window on that tab), `HE_DEBUG_WIN_ORIGIN="x,y"`
(main-window origin),
`HE_DEBUG_FOLLOWUP_AFTER` (comma-separated seconds — submit a follow-up
programmatically) + `HE_DEBUG_FOLLOWUP_TEXT` (its question),
`HE_DEBUG_FOLLOWUP_KEYCYCLE` (seconds — focus the input, log key/first-responder
state, unfocus, log handback state).
M8: `HE_DEBUG_DISMISS_AFTER` (comma-separated seconds — call `panel.dismiss()`,
fade-out verification), `HE_DEBUG_FORCE_APPEARANCE=light|dark` (pin NSApp
appearance for reproducible light/dark runs), `HE_DEBUG_UI_AUDIT=<sec>`
(repeating structured `ui-audit panel:`/`ui-audit window:` lines — backdrop
class, cornerRadius, border RGBA, alpha, visible/key, toolbar items, sidebar
material, tab type).
M9: `HE_DEBUG_SET_PROVIDER="<sec>:<name>[,<sec>:<name>…]"` (switch
`active_provider` in memory at each delay, like a Settings save —
restart-free provider-switch verification).

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
- **Store:** JSONL at `~/Library/Application Support/Macsist/history.jsonl`
  (append-only; one record per completed request: ts, mode
  text/region/followup, model, input snippet ≤`history_snippet_chars`, full
  response, detail level). Region records save the capture PNG to
  `history_images/<uuid>.png` (referenced by filename — base64 never enters
  the JSONL) so 다시 질문 can re-send it; pruning deletes unreferenced images.
  Saving is gated per mode: `history_enabled` (master) +
  `history_save_text` (text/followup records) + `history_save_images`
  (region records incl. PNG); `history_max_items` *(config)*; pruning
  rewrites the file.
- **Window:** a regular activating window (toggled from the menu bar, optional
  "항상 위" floating toggle), list of past Q/A newest-first with search field;
  click a row → expand full text, buttons: copy, re-ask (re-runs with current
  model). Sidebar or tab switches to **Settings** — the existing settings
  controls move here (server/provider, models, hotkeys, detail, and the
  advanced flap — system prompts/temperature/max_tokens etc., already
  shipped in the settings window; M7 only relocates it).
- The menu bar menu gains: History/Settings 열기, server status line (M5).

### 5.3 Glass UI (M8) — shipped
- Adopt the macOS 26 **Liquid Glass** look: `NSGlassEffectView` where available
  (PyObjC `objc.lookUpClass` guard — only resolves after AppKit is imported),
  falling back to `NSVisualEffectView` (`.hudWindow` material). Config
  `glass_enabled` is the kill-switch. Glass path: content lives in a wrapper
  NSView handed to `setContentView_` (never addSubview on the glass directly).
- Panel: continuous-corner radius (`panel_corner_radius`, 26pt Spotlight-like);
  thin 1px `separatorColor` border **on the fallback only** — Liquid Glass
  draws its own rim highlight, a CALayer border would fight it (border color
  re-resolved in `viewDidChangeEffectiveAppearance`); SF Pro text
  (`panel_font_size`, 15pt); shadow; fade-in/out (`NSAnimationContext`,
  `panel_fade_duration` 150ms — but a key-window dismiss stays instant:
  `orderOut_` is what hands the keyboard back, and
  `_unfocusInput`/`_resetSessionUI` flips never animate); auto-height
  from `panel_min_height` up to `panel_height` (`panel_height_expanded` once a
  follow-up starts) before scrolling — grow-only, top edge fixed. Region mode
  centers the panel on the captured selection's midpoint (drag tracked via
  read-only HID polling during `screencapture -i`; window-mode/click falls
  back to the cursor). Settings saves mark the panel dirty → rebuilt at the
  next session start (never mid-stream).
- Main window (user-directed chatbot redesign, several polish rounds):
  full-size-content titled window, non-opaque, body = frosted glass sheet
  (`glass_style` regular/clear + `glass_window_tint_alpha`) with 26pt rounded
  corners (edges genuinely transparent); floating glass **sidebar island**
  (SF-Symbol items 기록/설정 with self-drawn accent selection pills — the
  system source-list capsule re-tiled rows and wobbled — plus NSSwitch
  toggles for history saving / 항상 위); unified icon-only glass toolbar
  hosting the search field (`NSSearchToolbarItem`). History pane = chat
  transcript (user bubbles right/accent via NSBox — `contentViewMargins`
  must be zeroed and heights measured with `cellSizeForBounds`, or labels
  clip — AI bubbles left), sessions = rounded card list on the right
  (a session = text/region record + its follow-ups). Settings pane =
  Codex-style scrollable sections of card rows (연결/응답/단축키/모양/고급)
  with rounded borderless input fields (`ui_kit.make_round_field`) and pill
  buttons (`ui_kit.PillButton`, hover tint). 모양 section edits
  panel font/width/height + glass style live. ⌘W closes (keyCode 13 in
  `performKeyEquivalent_` — no main menu in an Accessory app); first open
  is screen-centered.
- Icons (`app/assets/`, copied by deploy.sh): menu-bar template PDF (18pt,
  healthy state only — loading/down keep the SF-Symbol alert bubbles, M5 AC)
  and `macsist.icns` Dock icon via `setApplicationIconImage_`.
- All chrome respects light/dark via semantic colors (`labelColor` etc. — never
  hardcoded RGB); layer-color users re-resolve in
  `viewDidChangeEffectiveAppearance`, NSBox fills re-resolve natively.

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
- *(As built, M9)* `base_url` excludes `/v1` — the client appends
  `/v1/chat/completions` (so OpenAI = `https://api.openai.com`, OpenRouter =
  `https://openrouter.ai/api`). `api_key_env_or_value` forms: `""` (no auth),
  `env:VAR`, else a Keychain account under service `com.macsist`
  (`keychain.py`; accounts are `provider-<slug>`, stable across renames).
  External health = authed `GET /v1/models` (`health_poll_timeout_external`);
  `loading` state stays local-only.

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

*(As built, M10)* Hardware tiering: `sysctl hw.memsize` → 128GB+ recommends the
full 2-model stack; below that, the best single **multimodal** model whose
min-RAM fits (Qwen3.6-35B-A3B 48GB+ → gemma-4-31b-it 40+ → gemma-4-26b-a4b-it
32+ → gemma-4-12B-it-qat 16+ → gemma-4-E4B-it-qat 8+); <16GB recommends the
API path. Every catalog id is verified against the HF API before being offered
(404 → tier dropped with a warning), so guessed ids self-heal at runtime.
Server models live in `models.env` next to the deployed `start_server.sh`
(`MACSIST_SERVER_MODE=full|vlm-only|lm-only`, `MACSIST_VLM_MODEL`,
`MACSIST_LM_MODEL`) — sourced by `start_server.sh`, exported to the proxy;
`--supervise` now combines with the stack mode. `server.py` routes to the LM
backend only when that backend is expected, and `/v1/models` reflects the
running stack. Config/Keychain writes go through `cli/configure.py`
(stdlib-only; reuses `app/config.py` + `app/keychain.py`; `set-api-provider`
takes the key on **stdin**). TCC probing: `main.py` logs
`TCC: accessibility=<bool> screen_recording=<bool>` at startup — the installer
and `doctor` kickstart the app and read only log bytes written after the
kickstart offset. App round-trip smoke: `HE_DEBUG_SKIP_AX_PROMPT=1
HE_DEBUG_KEEP_PANEL=1 HE_DEBUG_FAKE_TEXT=… HE_DEBUG_EXPLAIN_AFTER=2`,
foreground deployed-venv run, success = the `stream finished, panel text:`
line; KEEP_PANEL is required — a user keystroke/click mid-install would
otherwise dismiss the panel and cancel the stream (and never use a dismiss
timer shorter than the stream: the local 27B needs ~30s for 512 tokens).

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

*(As built, M10)* `cli/macsist`, symlinked from `/usr/local/bin` (sudo) or
`~/.local/bin` (fallback); resolves its own symlink to find the repo for
`update`. `settings`/`history` post distributed notifications
`com.macsist.showSettings` / `com.macsist.showHistory` (observer:
`_RemoteCommandRelay` in `main.py`, logs `remote: …`), posted via the deployed
app venv python (has PyObjC). `status`/`doctor` read config through
`configure.py status --shell` (eval-able KEY=VALUE — no jq) and the last
`TCC:` line in app.log; external providers are probed by `configure.py probe`
(auth header stays inside python). `update` redeploys the server only when its
plist exists (API-only installs have no server agent). Both deploy.sh scripts
retry `launchctl bootstrap` up to 5× — bootstrap immediately after bootout
intermittently fails with I/O error 5.

### 5.7 History deletion + 6-language support (M11, as built)

**History deletion.** Each session card in the History window carries an
always-visible `xmark.circle.fill` button (right-middle, tertiaryLabel tint);
click = immediate delete, no confirmation (user decision). The button's tag is
the *filtered* row index (cells are rebuilt on every reload, so tags can't go
stale) → `deleteSession_` → `HistoryStore.delete_records(session["records"])`
→ `refreshHistory()`. The store refactored `_prune` into a shared atomic
`_rewrite(keep_newest_first)`; `delete_records` Counter-matches
`(ts, mode, input, response)` tuples against a **fresh** `load()` (ts is
second-resolution — identical records may coexist; delete exactly the
requested copies) and the rewrite's orphan sweep removes the session's PNG.
Log hooks: `history: deleted N records, M remain`,
`history: session deleted row=…`.

**i18n.** `app/i18n.py` (pure data, stdlib-only — `cli/configure.py` imports
it): `LANGUAGES` (ko/en/zh/ja/fr/de, native names), `STRINGS[lang][key]`
(~131 keys: `menubar.* errors.* panel.* history.* settings.*`; ko is
byte-identical to the pre-M11 literals), `t(key)` with ko fallback,
`set_language()` (logs `i18n: language=…`), and `PROMPT_DEFAULTS[lang]` —
per-language `system_prompt_text/image`, `user_prompt_image`,
`detail_levels` (labels + suffixes localized; key order brief/normal/detailed
and max_tokens 256/512/1024 identical everywhere; the detailed suffix keeps
its explicit-override phrasing — the 상세도 feature was reviewed and KEPT, the
"6–10 sentences" suffix intentionally overrides the base 3–5 rule).

**Config semantics** (`config.py`): new `"language"` key (default ko). The
four prompt keys left `DEFAULTS`; `get()` resolves them from
`i18n.PROMPT_DEFAULTS[language]` unless present on disk (customized wins).
Load-time migration drops an on-disk value equal to ANY language's default
(every pre-M11 config had the Korean defaults pinned — save() used to write
everything); `save()` re-scrubs the same way so a Settings save can't re-pin
them. Trade-off (by design): a genuinely customized prompt survives language
switches — LLM output language follows the custom prompt until 기본값 복원,
which now resets to the *current* language's defaults. Gotcha found live: a
pre-M4 prompt variant was pinned in the real config and blocked the switch —
historical default variants must be listed in `_SUPERSEDED_DEFAULTS`.

**Live apply.** `main.py` calls `i18n.set_language(config)` before any
controller builds labels. On Settings save with a language change:
`set_language` → `menubar.relabel()` (synchronous) →
`AppHelper.callAfter(main_window.rebuildContent)` — NEVER synchronously: the
Save button lives inside the hierarchy being torn down. `rebuildContent()`
strips the contentView, re-runs `_buildContent()` (split out of
`_buildWindow`), restores tab/search placeholder, re-runs `refreshHistory()`
(switch states live there). The result panel picks the language up via the
existing `markDirty()` rebuild. Settings gained a 일반 section with an
NSPopUpButton of native language names (never translated). Debug hook:
`HE_DEBUG_SET_LANGUAGE="<sec>:<code>,…"` switches like a Settings save.
`install.sh` asks the language right after step 0 (installer TUI itself stays
Korean) → `configure.py set-language <code>`. Log hooks: `menubar relabeled
lang=…`, `window content rebuilt lang=…`. NSTabView keeps only the selected
tab's view in the hierarchy — harness assertions on the other tab must use
direct references (e.g. `mw.copy_button`), not a view walk.

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
- **M7 — History + main window** (§5.2). **DONE (2026-06-12).** System-prompt/
  advanced editing already shipped in the settings window (고급 설정 flap) —
  M7 relocated the existing settings controls into this window's Settings tab
  (container-injection refactor: `SettingsPaneController.buildInView_`, flap
  is pure show/hide), no new editing UI. History list is master-detail (table
  + fixed detail pane) by design — inline row expansion was rejected because
  this bundle-less app cannot be verified by screenshots.
  *AC verified:* standalone store tests (append/load order, snippet truncation,
  atomic prune, corrupt-line skip, restart survival) + live dev run with debug
  hooks wrote text/followup/region records to history.jsonl (schema exact, no
  base64, vision model recorded for region) + window harness (M6-style,
  /tmp/m7_history_harness.py): search filters input AND response (AC:
  searchable), row select → full Q/A detail, copy → pasteboard, re-ask fires
  with the stored input and is disabled for region rows, 기록 저장 off →
  appends become no-ops (AC: disable toggle), on_appended live-refresh, 항상 위
  flips the window level, Settings tab loads/saves config with validation and
  fires on_saved (AC: edits apply without restart), flap toggles without
  resizing the window.
  *M7.1 follow-up (2026-06-12, verified):* region captures saved to
  `history_images/` + re-ask re-sends the PNG (store tests: image file/ref,
  per-mode gating, orphan-image prune; harness: image-row re-ask passes
  prompt+bytes, imageless region row stays disabled, sub-toggle gating; live
  e2e: capture → PNG on disk → resubmit_image streamed a new region record);
  save toggles split into master + 이미지/텍스트 sub-toggles; Cmd-Tab via
  Regular-policy switch while the window is open (harness-verified both
  directions) + ⌘⇧H global toggle hotkey (recordable; registered binding seen
  in the listener log).
- **M8 — Glass UI** (§5.3). **DONE (2026-06-12).**
  *AC:* panel + history window render with glass material, rounded corners,
  fade animations, correct light/dark; no regression in never-steal-focus.
  *AC verified (HE_DEBUG runs + ui-audit):* panel backdrop=NSGlassEffectView
  radius 16 (fallback `_HairlineEffectView` borderWidth 1, cornerCurve
  continuous when `glass_enabled:false`); fade-in/out logs in order, dismiss
  fade leaves alpha restored + invisible, re-present 50 ms into a fade-out
  cancels the pending orderOut (generation token); auto-height grew 120→172
  on a real stream and a follow-up raised the cap and stopped exactly at 420
  (`panel_height_expanded`), top edge fixed (y+h constant), no decreasing
  heights; forced light/dark runs resolved separatorColor to different RGBA
  (0.902 vs 0.137 grey) with matching appearance names; M6 keycycle rerun —
  `input focused, key = True` / `input unfocused, key = False`, panel never
  key during streaming; window audit: toolbar=[flexspace, search]
  style=unified(3), sidebar NSVisualEffectView material=Sidebar(7),
  tabType=NoTabsNoBorder(6); window harness: toolbar search filters
  (25→2 rows), sidebar swaps panes + refreshes settings, row-select detail
  + copy enable intact; OPEN_HISTORY/OPEN_SETTINGS/WIN_ORIGIN hooks
  unchanged. Deployed; user eyeballed the live windows across the polish
  rounds below.
  *M8.1 polish (2026-06-12, user-directed iterations, all verified by harness
  + user screenshots):* chatbot main-window redesign (chat bubbles + session
  cards + sidebar switches, §5.3); frosted glass sheet body with 26pt
  transparent edges after a too-clear round (`glass_style` superseded
  clear→regular, `glass_window_tint_alpha`); boxes ×1.3 / fonts ×1.15
  (`panel_*` superseded-default migration since old defaults were pinned in
  config.json); Codex-style Settings sections incl. 모양 (panel font/size +
  glass style, live via `panel.markDirty()` rebuild-on-next-session); ⌘W
  close; window first-open centered; region panel centered on the captured
  selection (pixel-exact in e2e: rect (600,300,400,300) → panel center
  (800,450)); custom icons (menu bar template PDF + Dock icns); bubble
  pixel-verification harness (offscreen `cacheDisplayInRect` — white text
  pixels counted on the accent bubble) caught the NSBox
  `contentViewMargins`/`cellSizeForBounds` clipping bugs.
- **M9 — External providers** (§5.4). **Shipped 2026-06-12.**
  *AC:* add an OpenRouter (or OpenAI) provider with a key → explain works with
  the local server stopped; key lives in Keychain; switching back needs no
  restart.
  *AC verified (HE_DEBUG runs, OpenAI gpt-4o-mini):* with
  `com.macsist.llm-server` booted out, text + region explains streamed Korean
  answers via `api.openai.com` and the menubar health went `ok` through the
  authed `/v1/models` probe; key stored as Keychain item
  `com.macsist`/`provider-openai` (config.json holds only that account name —
  grep for key material: 0 hits); `HE_DEBUG_SET_PROVIDER="6:로컬 서버"` mid-run
  switched request 2 back to `127.0.0.1:8000` in the same process (local
  proxy log shows the POST); bogus key → panel error "OpenAI 인증 실패
  (HTTP 401) — API 키를 확인하세요" (provider-named, per spec); pre-M9 config
  auto-migrated (`server_base_url`+models → `providers[0]`, customized 27B
  explain model preserved, second load idempotent); `keychain.py` CLI
  round-trip + `-U` update + missing→None + idempotent delete all pass.
  Settings 연결 section rebuilt as provider picker + add/delete pills +
  per-provider fields (name / URL / secure key with Keychain-status line /
  로컬 서버 switch / model combos / authed 모델 새로고침) — staged in memory,
  committed on Save; typed keys go Keychain-only via a `_pending_key`
  staging slot stripped before `config.set`.
- **M10 — Onboarding + CLI** (§5.5–5.6). **DONE (2026-06-12).**
  *AC:* on a machine state simulating "nothing installed", `install.sh` reaches
  a working explain in one session (both the local and the API path);
  `macsist status|logs|doctor|restart` work from any directory.
  *AC verified (move-aside simulation: agents booted out, `…/Application
  Support/Macsist` + both plists moved to `*.m10bak`, then restored):*
  **API path** — bare state → scripted `install.sh` (외부 API → OpenAI,
  existing Keychain account referenced by name only) → app round-trip streamed
  a Korean answer via `api.openai.com` (`stream finished, panel text:`);
  `doctor` all-✓ with the server section correctly skipped; key material in
  config.json: 0 grep hits. **Local path** — bare state → scripted
  `install.sh` (full stack recommended for 128GB) → conda env/HF token/models
  detected as already-done, `models.env` written, server deployed, smoke ✓
  (health ok → 27B chat probe → app round-trip streamed). **Idempotency** —
  immediate rerun: every step `[건너뜀]`, `config.json` diff empty.
  **CLI from /tmp** — `status`, `doctor` (rc 0), `logs server`, `restart app`
  (fresh `TCC:` line), `settings`/`history` (`remote: showSettings` /
  `remote: showHistory` in app.log), `update` (ff-only no-op + both
  redeploys), via the `~/.local/bin` fallback symlink. **vlm-only
  regression** — with a vlm-only `models.env`: `/health` counts only the vlm,
  `/v1/models` lists one model, a request naming the 27B falls through to the
  VLM backend and answers 200. Live setup restored afterwards; `doctor` all-✓
  on the user's original config. Debugging notes that became invariants:
  smoke needs `HE_DEBUG_KEEP_PANEL` (user input dismisses the panel →
  cancels the stream) and no dismiss timer shorter than the stream.
- **M11 — History deletion + 6-language i18n** (§5.7). **DONE (2026-06-13).**
  *AC:* per-card delete control removes the session (records + region PNG)
  immediately; language chosen at install / changed in Settings applies
  without restart to all UI strings AND the LLM output/translation language;
  상세도 reviewed — kept (suffixes are intentional overrides), localized.
  *AC verified:* store unit tests (delete mid-session orig+followups, region
  PNG unlink + referenced-PNG survival, duplicate-record exact-count delete,
  delete-all → empty, `_prune` regression post-refactor) + config unit tests
  (fresh config has no prompt keys on disk; pinned Korean defaults dropped;
  customized prompt survives load+save; `language=en` flips resolved
  defaults; save-scrub removes default-equal values incl. other languages;
  pre-M9 superseded variants still dropped) + i18n completeness (6 languages
  × 131 identical keys, placeholder parity, detail order/tokens identical,
  ko byte-identity) + window harness (delete click → row gone/disk
  shrunk/reselect; delete under active search filter; delete-all → empty
  state; ko build → en `rebuildContent()` flips labels/detail
  segments/search placeholder; delete button still wired post-rebuild) +
  live e2e (foreground deployed run: ko explain streamed Korean →
  `HE_DEBUG_SET_LANGUAGE` 30s:en → `menubar relabeled lang=en` → second
  explain streamed English with "Translation:" prefix → back to ko) +
  installer `set-language de` sandbox + invalid-code rejection. Live debugging
  found a pre-M4 prompt variant pinned in the real config blocking the
  switch → added to `_SUPERSEDED_DEFAULTS` (gotcha recorded in §5.7).

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
   listener instead. Second leg (M11.1): pynput converts `NSSystemDefined`
   CGEvents to NSEvent on the LISTENER thread for media-key detection; the
   caps-lock / **한-A toggle** makes that conversion run
   `TSMAdjustCapsLockPressAndHold` → TIS off-main → the app dies with SIGTRAP
   on a single 한/A press. Fixed by stripping `CGEventMaskBit(NSSystemDefined)`
   from the listener's tap mask in `HotkeyManager.__init__` (media keys
   unused) — keep that mask override if pynput is ever upgraded.
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
   `~/Library/Application Support/Macsist/`. TCC grants attach to the
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
  install.sh            (M10) onboarding installer (Korean TUI, idempotent)
  cli/macsist           (M10) CLI dispatcher (symlinked onto PATH)
  cli/configure.py      (M10) config/Keychain helper (stdlib-only)
  server/requirements.txt  (M10) conda env package pins
```

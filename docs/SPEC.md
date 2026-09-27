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
  (Dock + Cmd-Tab; M12부터 Macsist 이름+아이콘으로 표시) and reverts to
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
| `explain_controller.py` | hotkey → worker thread → `callAfter`; generation counter (main-thread staleness check); global preemption; M6 follow-up session (`_session`, `submitFollowUp`, turn capping); M7 history commit + `resubmit_text` (re-ask); M20 `_memoryBlock()` pre-stream recall + `_remember()` post-commit enqueue |
| `settings_window.py` | `SettingsPaneController` — settings controls built into a host view (combos / recorders / detail segments / 고급 flap); window-less since M7 |
| `main_window.py` | `MainWindowController` — main window (NSTabView: 기록/기억/비서/설정, master-detail lists, shared search field dispatched per tab, copy/re-ask, 기록 저장·항상 위 toggles) |
| `history_store.py` | `HistoryStore` — append-only JSONL, main-thread-only, atomic prune/rewrite + `delete_records` (M11); **M20: a short rolling buffer** (`memory_history_rolling`), not the long-term record |
| `memory/store.py` | M20 — `MemoryStore`: `notes/*.md` (source of truth) + derived `index.json`, ingestion queue (`pending.jsonl` + cursor), and the LLM-free IDF/query-coverage `recall()` that runs in the hotkey path |
| `memory/recall.py` | M20 — `recall_block()`: the advisory system-prompt suffix (related notes + reader profile), budget-capped |
| `memory/distiller.py` | M20 — `MemoryDistiller`: readings → concepts as strict JSON on the **local** LLM (`ForceLocalConfig`), `upsert` per concept, `profile.md` rewrite |
| `memory/monitor.py` | M20 — `MemoryMonitor` (`health.py` clone): drains the queue every `memory_tick_interval`, resumable `backfill()` from `history.jsonl` |
| `memory/tab.py` | M20 — `MemoryTabController`: the 기억 tab (note cards + note markdown / 관심사 프로필, forget, reveal folder) |
| `i18n.py` | M11 — UI strings (6 languages) + per-language prompt defaults; `t()` / `set_language()`; pure data, stdlib-only |
| `config.py` | JSON store at `~/Library/Application Support/Macsist/config.json`; prompt keys resolve per `language` (M11, §5.7); `asset_dir()` (M12 — RESOURCEPATH/번들 분기) |
| `setup.py` | M12 — py2app 빌드 설정 (Info.plist, packages, extra_scripts) |
| `macsist_notify.py` | M12 — 분산 알림 포스터 (`Contents/MacOS/macsist_notify`) |
| `run.sh` / `deploy.sh` | dev run (리포 venv, 번들 없음) / py2app 빌드+서명+번들 launchd 배포 (M12, §5.8) |

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
M20 기억: `memory_enabled` (master), `memory_recall_enabled` /
`memory_inject_profile` (prompt injection), `memory_local_only` (distil only on
an `is_local` provider — the reading history must not follow a provider switch
out to the internet), `memory_model`, `memory_tick_interval`,
`memory_batch_size`, `memory_max_batches_per_tick`, `memory_snippet_chars`,
`memory_distill_input_chars` / `memory_distill_response_chars` /
`memory_distill_max_tokens`, `memory_max_concepts`, `memory_summary_chars`,
`memory_known_notes`, `memory_recall_top_k`, `memory_recall_min_score`
(query-coverage 0~1 — scale-free, so the cutoff means the same at 5 notes and
at 500) + `memory_recall_min_mass` (absolute IDF floor — kills the 2-char
Korean-prefix false positive), `memory_recall_summary_chars`,
`memory_recall_max_chars`, `memory_profile_domains` / `_notes` / `_every` /
`_max_tokens`, `memory_history_rolling`. The 7 prompts
(`memory_distill_system`/`_user`, `memory_profile_system`/`_user`,
`memory_recall_preamble`/`_line`/`_profile`) are `_LANG_KEYS` — resolved from
`i18n.PROMPT_DEFAULTS` per language.

### Debug hooks (env vars, kept for agent-driven verification)
`HE_DEBUG_EXPLAIN_AFTER` / `HE_DEBUG_EXPLAIN_REGION_AFTER` (comma-separated
seconds — fire hotkey paths programmatically), `HE_DEBUG_FAKE_TEXT` (bypass
capture), `HE_DEBUG_REGION_RECT="x,y,w,h"` (bypass interactive overlay),
`HE_DEBUG_KEEP_PANEL` (don't install dismiss monitors — note: also disables
M6 click-to-focus, which lives in the local monitor), `HE_DEBUG_FRAME`,
`HE_DEBUG_OPEN_MENU`, `HE_DEBUG_OPEN_SETTINGS` / `HE_DEBUG_OPEN_HISTORY` /
`HE_DEBUG_OPEN_ASSISTANT` / `HE_DEBUG_OPEN_MEMORY`
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
- Explain / vision / agent default: `mlx-community/Qwen3.8-27B-bf16` — one
  model for all three. Qwen3.8-27B is a **native VLM** (dense 27B, hybrid
  Gated DeltaNet 3:1 Gated Full Attention over 64 layers, native 256K ctx),
  so text and `image_url` content go to the same backend and the stack runs
  **vlm-only** (`:8001` only; `:8002` never binds).
- `vision_model` stays a separate config key: an external provider (or a
  text-only local pick) may still need a different id for region capture.
- Alt explain (A/B): `Gemma-4-12B` (not in the server pool — inert default).
- Precision is the only local tier knob (weights only, + KV cache):
  `-bf16` 54.4GB / `-8bit` 29.5GB / `-4bit` 16.1GB. bf16 decode is memory
  bandwidth bound — roughly ½ the tok/s of 8bit, ⅓ of 4bit.
- Requires **mlx-vlm ≥ 0.6.8** (the mlx-community conversions were made with
  0.6.8; the Gated DeltaNet blocks don't load on older builds).

**History:** through Qwen3.6 this was a 2-model stack — `Qwen3.6-35B-A3B-4bit`
(multimodal, `:8001`) + `Qwen3.6-27B-4bit` (dense **text-only**, rejected
`image_url`, `:8002`). Qwen3.8 collapses both into one, which is why
`install.sh` no longer offers a "풀 스택" tier. `full` mode itself is still
supported by `start_server.sh` / `server.py` for a hand-written `models.env`.

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

*(As built, M10; retiered for Qwen3.8)* Hardware tiering: `sysctl hw.memsize`
→ the best single **multimodal** model whose min-RAM fits (Qwen3.8-27B-bf16
96GB+ → -8bit 48+ → -4bit 32+ → gemma-4-12B-it-qat 16+ → gemma-4-E4B-it-qat
8+); <8GB recommends the API path. Every tier is now the same model at a
different precision, so the recommendation is a quality/speed dial rather
than a model swap, and the old 2-model "풀 스택" tier is gone. Every catalog id is verified against the HF API before being offered
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

### 5.8 .app 번들화 (M12, as built)

**What.** `app/deploy.sh`가 "py 복사 + venv" 대신 **py2app standalone 빌드 +
고정 자체서명 + 번들 설치**를 수행한다. 산출물
`~/Library/Application Support/Macsist/Macsist.app`을 launchd가 직접 실행
(`ProgramArguments = [...Contents/MacOS/Macsist]`) — Dock/Cmd-Tab/TCC 목록에
"Python" 대신 Macsist 이름+아이콘이 뜬다. 셸 런처/심링크 금지: 프로세스 실행
파일이 `Contents/MacOS/` 밖이면 `NSBundle.mainBundle`이 번들을 못 찾는다.

**Build python.** miniforge base는 **정적 빌드**(`Py_ENABLE_SHARED=0`,
`libpython3.13.a`)라 py2app 런타임으로 쓸 수 없다 → **brew `python@3.13`**
(framework 빌드)로 빌드 venv(`$SUPPORT_DIR/build-venv`, 깨지면 자동 재생성)를
만들어 `python setup.py py2app` (py2app 0.28.10 고정). 서버 conda 스택 무관.
`app/setup.py` OPTIONS 요점: `resources: ["assets"]`,
`extra_scripts: ["macsist_notify.py"]` (→ `Contents/MacOS/macsist_notify`,
번들 런타임 공유 — CLI의 분산 알림 포스터), `packages`에 pynput/httpx 계열
+certifi+PyObjC 패키지(전부 site-packages.zip 밖 실디렉토리로 — pynput 런타임
백엔드 import, certifi cacert.pem 실경로, PyObjC lazy-load 보호).
**PyObjCTools는 packages에 넣으면 안 됨** — 네임스페이스 패키지라 modulegraph가
죽는다 (main.py의 정적 import로는 정상 수집). `LSUIElement: True`는 초기
정책일 뿐, 런타임 Regular 전환(M7)은 그대로 동작; Dock 아이콘은 번들 icns가
공급하고 `setApplicationIconImage_`는 dev-run 폴백으로 유지.

**Signing / TCC 영속.** CN "Macsist Signing" 자체서명 인증서(RSA-2048, 10년,
codeSigning EKU critical)를 deploy.sh가 최초 1회 생성: openssl로 키/인증서 →
**PEM으로 따로 import** (OpenSSL 3.x pkcs12 기본 알고리즘은
SecKeychainItemImport MAC 검증 실패 — p12 금지) + `-T /usr/bin/codesign` →
`security add-trusted-cert -r trustRoot -p codeSign`을 **login keychain
사용자 도메인**에 — sudo 불필요 (macOS 26.2 실증). 서명은 inside-out:
`xattr -cr` → 내장 Python.framework → Resources 하위 `*.so`/`*.dylib`(--deep이
Resources는 안 내려감) → `--deep` 외부 서명 → verify. 산출 csreq
`identifier "com.macsist.app" and certificate leaf = H"…"` — 번들 ID·인증서
고정이므로 재빌드마다 동일 → TCC 유지. **ad-hoc 서명 금지**: CDHash 기반 DR이
빌드마다 바뀌어 재배포 시 TCC가 풀린다. 설치 복사는 **`ditto`** (cp -R은 서명
메타데이터를 깨뜨릴 수 있음). launchd 교체 순서: bootout → 번들 스왑+재검증 →
plist → bootstrap(5회 재시도) → 성공 후에만 구 `…/Macsist/app` venv 배포 제거.

**코드 적응 3곳.** ① `config.asset_dir()` — py2app 스텁이 export하는
`RESOURCEPATH` env 있으면 `Resources/assets`, 없으면 `__file__` 옆 (dev run);
main.py icns / menubar.py 템플릿 PDF가 사용 (번들 안 모듈 `__file__`은
site-packages.zip 내부라 직접 못 씀). ② AX 허용 후 자가 재실행: 번들 안
`sys.executable`은 앱 스텁이 아니라 **동봉 CLI 인터프리터**
(`Contents/MacOS/python`) → `EXECUTABLEPATH` env(스텁이 export)로
`os.execv` (PID 유지, KeepAlive 무관; dev run은 기존 sys.executable 폴백).
③ `cli/macsist`: `pybin()` 1순위가 번들 `Contents/MacOS/python`(stdlib-only
configure.py 실행 — 단독 실행 가능 실증), 알림은 `macsist_notify`, doctor에
번들 존재 + `codesign --verify --deep --strict` 검사 추가. install.sh는
4단계 직전 brew python@3.13 자동 설치, 6단계 문구 Macsist 기준(화면 기록 '+'
는 `$APP_BUNDLE` 경로 + ⌘⇧G 힌트), 7단계 스모크 `"$APP_EXE"` 직접 실행
(HE_DEBUG_* env는 스텁을 그대로 통과).

**Found while building.** httpx 0.28은 sniffio에 의존하지 않는다 (packages에
넣으면 modulegraph가 죽음 — venv에 실제 설치된 것만 나열). 번들을
`lsregister -f`로 등록해도 computer-use의 앱 allowlist resolver는
/Applications 밖 앱을 못 찾는다 — 스크린샷 검증은 M12 이후에도 불가, HE_DEBUG
훅 체계 유지 (프로젝트 메모리 `verify-ui-without-screenshots`). 기존 설치
이행: 번들 = 새 TCC 정체성이라 일회성 재허용 필요 — 앱이 스스로 프롬프트해
목록에 등록되고, grant 즉시 `_AXGrantWaiter`가 EXECUTABLEPATH 재실행으로
이벤트 탭을 붙인다 (라이브 이행에서 그대로 관찰됨).

### 5.9 기억(Memory) — 읽은 것에서 자라는 파일시스템 기억 (M20, as built)

**문제.** 3개월 동안 173건을 설명받았는데, 앱은 그것을 `history.jsonl`이라는
**죽은 캐시**로만 갖고 있었다. 같은 개념(GAE, OMOP CDM…)을 두 번째로 선택해도
앱은 처음 본 것처럼 설명한다. 사용자가 원한 것: 읽은 것이 쌓여 **관심사가
파일로 형성**되고, 비슷한 것을 만나면 **이전에 본 것과 이어서** 설명하며, 그
다음에는 **옛 캐시를 버리는** 것. 전부 로컬 Qwen3.8-27B로.

**두 속도로 쪼갠다 (핵심 결정).** 핫키→패널 지연은 제품의 심장이므로 읽기
경로에는 LLM을 절대 넣지 않는다.

| | 핫패스 (핫키 누른 순간) | 콜드패스 (백그라운드) |
|---|---|---|
| 하는 일 | `MemoryStore.recall(text)` → 시스템 프롬프트에 블록 주입 | 끝난 읽기를 개념으로 증류해 노트에 접기 |
| 비용 | 마이크로초, 네트워크 0회 (인메모리 인덱스) | 배치당 LLM 1회 (로컬, 약 90초) |
| 실행 | explain 워커 스레드 | `MemoryMonitor` 데몬 (`memory_tick_interval`) |

임베딩은 쓰지 않는다 — 스택이 vlm-only라 `/v1/embeddings`가 아예 없다. 대신
**IDF 항목겹침 + 질의 커버리지**로 검색한다. 한국어는 **접두사 색인**으로
푼다: "강화학습을"은 강화/강화학/강화학습을 낸다(조사가 뒤에 붙으니 접두사가
곧 어간). 질의측과 색인측이 **같은 `terms_of()`** 를 쓴다 — 토크나이저가
비대칭이면 어휘 검색은 조용히 안 맞기 시작한다.

점수 = **질의 커버리지**: "이 기억이 아는 질의 항목들의 IDF 질량 중 이 노트가
덮는 비율". 문서측이 아니라 질의측으로 정규화하는 이유는 임계값이 노트 5개일
때와 500개일 때 **같은 뜻**을 갖게 하기 위해서다(절대 IDF 합은 코퍼스와 함께
자라서 컷오프가 "너무 느슨함"에서 "아무것도 안 걸림"으로 표류한다). 기억이 한
번도 못 본 낱말은 분모에서 제외한다 — 캡처에 섞인 무관한 단어가 나머지를
제대로 덮는 노트를 희석해서는 안 된다. 2차 관문 `memory_recall_min_mass`가
"한글 2글자 접두사 하나만 맞은" 오탐을 막는다.

**주입은 조언이다, 사실이 아니다.** 프롬프트 블록은 "정말 관련 있을 때만 한
줄로 이어 언급하고, 아니면 이 블록을 완전히 무시하라"고 지시한다. 어휘 검색의
오탐이 설명 속 **틀린 단정**으로 승격되어서는 안 되기 때문이다. 블록 어디에도
"이 노트들이 관련 있다"는 주장은 없다.

**파일 레이아웃** (`…/Application Support/Macsist/memory/`):
```
notes/<slug>.md   개념 하나 = 파일 하나. frontmatter(title/aliases/terms/
                  seen/first_ts/last_ts/links) + 한 줄 요약 + "## seen in"
                  (마주친 맥락, 최신 8개). ASCII slug — 한글 파일명은 NFC/NFD
                  정규화가 쓰는 쪽마다 달라 "같은 노트"가 두 파일이 된다.
index.json        파생 캐시. 노트 mtime이 움직인 것만 재파싱 → 사용자가
                  에디터로 고친 노트가 다음 로드에 그대로 반영된다.
pending.jsonl     수집 큐(append-only + state.json 커서). 설명이 끝나면 한 줄
                  추가가 핫패스가 내는 유일한 비용. 서버가 죽어 있어도 읽은
                  것은 사라지지 않는다.
profile.md        관심사 프로필(LLM). 기억이 스스로를 요약한 것.
```
**노트가 진실원천, index.json은 캐시** — 사용자가 직접 읽고 고칠 수 있는
마크다운이어야 한다는 게 "file system으로 형성"의 요구였다.

**불변식 / 게이트**
- **로컬 전용** (`memory_local_only`, 기본 True): 증류는 첫 `is_local`
  프로바이더에 고정된다(`llm_util.ForceLocalConfig` — M17 Gmail triage와 공유).
  읽은 기록은 앱이 가진 가장 사적인 데이터다. **설명 프로바이더를 외부로
  바꿨다는 이유로 독서 이력이 인터넷으로 나가서는 안 된다.**
- **실패해도 항목을 잃지 않는다:** 서버 다운·응답 절단·JSON 파싱 실패는 0을
  반환하고 **커서를 전진시키지 않는다** → 다음 틱에 재시도. 커서는 배치 단위로
  움직이므로 백필은 중간에 앱이 죽어도 이어서 간다.
- **쓰는 프로세스는 앱 하나:** CLI는 파일을 직접 **읽고**, 쓰는 일(backfill/
  distill/profile)은 분산 알림으로 실행 중인 앱에 부탁한다. 두 프로세스가 같은
  노트를 접으면 경쟁한다.
- **AppKit 분리:** `memory/` 는 `tab.py`만 AppKit을 쓴다 → `cli/configure.py`가
  stdlib-only 규약을 유지한 채 (`/usr/bin/python3`로도) 기억을 읽는다.
- 영역(region) 캡처는 스트림 전에 대조할 텍스트가 없다(픽셀뿐) → 리콜 없이
  **읽는 사람 프로필만** 주입하고, 답변은 끝난 뒤 정상적으로 기억에 들어간다.

**캐시 은퇴 (사용자 결정: 롤링 창).** 기억이 장기 기록을 맡은 뒤
`macsist memory retire-cache`가 `history_max_items`를
`memory_history_rolling`(20)로 낮추고 즉시 프루닝한다 — 기존
`HistoryStore._prune`이 JSONL을 원자적으로 재작성하면서 살아남은 레코드가
참조하지 않는 캡처 PNG까지 지우므로 `history_images/`의 용량도 함께 회수된다.
기억이 비어 있거나 큐에 미증류 항목이 남아 있으면 **거부한다** — 그 읽기들의
유일한 다른 사본이 바로 그 캐시이기 때문이다. 기록 탭·다시 질문·카드 삭제
(M7/M11)는 짧은 버퍼 위에서 그대로 동작한다.

**CLI / UI**
- `macsist memory [status|list|show <slug>|backfill|distill|profile|open|
  retire-cache]`
- 사이드바 **기억** 탭: 노트 카드(제목/요약/분야/횟수/최근) + 선택한 노트의
  마크다운 원문, 선택 없으면 관심사 프로필. 공유 검색 필드는 보이는 탭에 따라
  분기한다. "이 기억 삭제"는 파일을 지우고 인덱스를 다시 접는다.

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
- **M12 — .app 번들화** (§5.8). **DONE (2026-06-13).**
  *AC:* Cmd-Tab/Dock/TCC 목록에 Macsist 이름+아이콘; 재배포(`macsist update`)
  후 TCC 재허용 없이 핫키 동작; install.sh가 빈 상태에서 번들 설치까지 한
  세션 완주(M10 AC 유지); 기존 기능 회귀 없음.
  *AC verified (2026-06-13, live):* py2app 0.28.10 + brew python@3.13으로
  45MB Macsist.app 빌드(`Contents/MacOS/`에 Macsist/macsist_notify/python),
  "Macsist Signing" 서명 — `codesign -dr-`의 designated requirement가 두
  풀 리빌드에서 바이트 동일(`identifier "com.macsist.app" and certificate
  leaf = H"ca77…"`); launchd가 번들 직접 실행, `lsappinfo`가
  `LSDisplayName="Macsist"` 보고(Dock/Cmd-Tab 명칭). **TCC 영속**: 손쉬운
  사용/화면 기록 1회 허용 후 풀 리빌드+재서명+재배포 →
  `TCC: accessibility=True screen_recording=True` 유지 + 핫키 attach
  (재허용 0회 — M12 핵심 AC). AX grant 시 EXECUTABLEPATH exec-재실행이
  라이브로 관찰됨("Accessibility granted — relaunching" → True → listening).
  회귀(HE_DEBUG, 배포 번들 포그라운드): 텍스트 explain+follow-up 스트림,
  REGION_RECT 영역 explain, OPEN_HISTORY+UI_AUDIT 창 감사, SET_LANGUAGE
  ko→en 전환 모두 통과; `macsist status|doctor|logs|settings|history|
  restart|update` 전부 동작(doctor에 서명 검사 추가). **설치 완주**:
  move-aside 시뮬레이션(에이전트 bootout + Macsist 디렉토리/plist 백업) →
  스크립트 입력으로 install.sh가 서버 재배포·번들 빌드·CLI·TCC(손쉬운 사용
  "[건너뜀 — 이미 완료]" — 새로 빌드된 번들이 csreq로 grant 승계, 이행 AC)·
  서버 chat 프로브·앱 왕복 스모크까지 rc=0 완주; 라이브 상태 복원 후
  권한·핫키 정상.
- **M20 — 기억(Memory)** (§5.9). **DONE (2026-09-27).**
  읽은 것이 `memory/notes/*.md` 로 자라고, 관련된 것을 만나면 설명이 이전 것과
  이어지며, 그 다음 옛 `history.jsonl` 캐시는 짧은 롤링 버퍼로 은퇴한다. 전부
  로컬 Qwen3.8-27B (`memory_local_only`).
  *AC:* ① 기존 기록 전체가 한 번에 기억으로 형성된다(backfill, 중단 후 이어감).
  ② 관련된 새 용어를 설명할 때 이전 노트를 한 줄로 이어 언급하고, 무관한
  캡처에서는 언급하지 않는다. ③ 핫키 경로에 LLM 호출이 늘지 않는다.
  ④ 노트는 사용자가 직접 읽고 고칠 수 있으며 고친 내용이 다음 로드에 반영된다.
  ⑤ 은퇴 후에도 기록 탭·다시 질문·카드 삭제가 동작한다. ⑥ 6개 언어 키 완비.
  *AC verified (2026-09-27, live):* **백필** — `macsist memory backfill` 이
  실행 중인 앱에 위임되어 **173건 → 노트 69개**(큐 0, `backfill_done_ts` 기록).
  로컬 27B bf16 실측: prefill ~1.1k tok @600-920 tok/s + decode ~450 tok
  @9.7 tok/s ≒ 배치(4건)당 50초~2분, 전체 약 50분. 인사말·비서 답변 같은
  배치는 모델이 `[]`로 정직하게 비우고 "no concepts … skipped"로 소비된다.
  **중단 후 이어감** — 백필 중 재배포로 앱을 죽인 뒤 다시 실행 → 재시드는
  ts+mode+input dedupe로 no-op, `state.json` 커서에서 정확히 이어갔다
  (24 → 149 잔여 → 완주). **이어서 설명** — `Fowlkes-Mallows index…` 캡처에서
  리콜이 Adjusted Rand Index(0.555)/Batch Silhouette를 올리고 답변이
  "앞서 본 Adjusted Rand Index(ARI)와 Batch Silhouette와 마찬가지로 …
  ARI가 전체 쌍의 일치/불일치를 본다면 FMI는 …"로 **'쉽게 말하면' 항목 안에서**
  이어 설명(4단 형식 유지, 새 제목 0). **기억이 복리로 자란다** — 그 설명이
  만든 노트 `fowlkes-mallows-index` 의 terms에 `ARI, Adjusted Rand Index` 가
  들어가, 다음 회차에는 두 개념이 서로를 끌어온다. **무관 캡처** — 주택임대차
  갱신요구권 문장에서 리콜 0건 → 프로필 줄(123자)만 주입, 기억 언급 0회.
  **앱 안 전체 고리(라이브)** — `HE_DEBUG_KEEP_PANEL` + `EXPLAIN_AFTER` 로
  핫키 explain → `memory: recall Batch Silhouette(0.584), PBISC(0.582),
  Adjusted Rand Index(0.526)` 주입 → 스트림 완료 → `_remember` 적립 →
  poke로 즉시 증류 → `new note fowlkes-mallows-index`(173 → 174건).
  **손으로 고친 노트** — `aliases` 에 사람이 `조정랜드지수` 를 직접 써넣자
  다음 로드(mtime 변화 → 재파싱)에서 그 별칭 질의가 그 노트를 1위로 올렸다.
  **검색 정확도** — 13개 질의 중 12개 기대대로(ARI/OMOP/XAI/GAE를 한글·영문·
  약자로 물어도 적중, 점심/git/전세/영문 pangram 0건). 남은 1개는 단독 "표준"
  질의가 OMOP CDM을 올린 것 — 노트 5개 코퍼스에서는 사실상 맞는 답이고,
  블록이 조언이라 오탐이 단정으로 승격되지 않는다. **캐시 은퇴** —
  `macsist memory retire-cache`: 기록 174건 → 20건, 캡처 이미지 34장 →
  2장(5.7MB → 444KB), `history.jsonl` 248KB → 24KB, `history_max_items=20`
  기록. 은퇴 후 라이브 확인: 기록 탭 20/20 + 기억 탭 70/70 정상, 예외 0.
  빈 기억/미증류 큐에서는 거부(`은퇴 보류: 기억이 비어 있습니다 …`).
  **UI** — 기억 탭이 6개 언어 전부 빌드/refresh 통과,
  `HE_DEBUG_OPEN_MEMORY` 라이브 확인(`sidebar selected memory` →
  `main window shown tab=memory`), 기억 저장·로컬만 스위치 즉시 반영.
  `macsist memory status|list|show|backfill|distill|profile|open|retire-cache`
  + `macsist doctor` 의 `[기억 (M20)]` 섹션 동작, `macsist doctor` 전체 통과.

  *라이브에서 잡힌 결함 4건 (설계를 고친 것들):*
  1. **빈 추출을 실패로 처리 → 큐 영구 봉쇄.** 모델이 `[]`(뽑을 개념 없음 —
     정당한 답)을 반환하면 커서가 전진하지 않아 같은 4건이 큐를 영원히 막고,
     백필은 149건을 남긴 채 "finished"라고 보고했다. → 유효한 빈 배열은
     **성공(소비)**, JSON 자체가 없을 때만 재시도.
  2. **배치 1회 실패로 40분 작업 종료.** → `memory_backfill_retries` 만큼
     재시도하고, 큐가 남은 채 멈추면 "STOPPED — N건 남음"이라고 정직하게 말한다.
  3. **문서측 정규화가 리콜을 죽였다.** 최초 점수식이 노트 term 수로 나눠
     `GAE와 PPO의 차이` 가 GAE 노트를 못 찾았다 → 질의 커버리지로 교체.
  4. **프리앰블이 "무시하라"에 치우쳐 모델이 관련된 경우에도 침묵.**
     → 긍정형("이어지면 반드시 한 문장으로") + 배치 지정('쉽게 말하면' 안,
     새 항목 금지)으로 고쳐 통과. 부수적으로 모델이 같은 분야를
     "노화 생물학"/"노화생물학"으로 번갈아 써서 관심 분야가 갈리는 것도
     `domains()` 정규화(공백·대소문자 접기, 최빈 표기 표시)로 고쳤다.

  *알려진 거친 부분:* 증류가 드물게 쓸모없는 제목(모델 파일명 조각 등)을
  노트로 만든다 — 기억 탭의 "이 기억 삭제" 한 번으로 정리되며, 제목 필터를
  더 세게 걸면 `GPT-4o` 같은 진짜 이름을 잃는다. `links` 는 모델이 비워두는
  경우가 많지만 terms 공유로 관계는 유지된다(노트 간 명시적 링크는 후속 과제).

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
13. **py2app 번들 + 서명 (M12):** ① 빌드 python은 framework/shared 빌드여야
    한다 — miniforge base는 **정적**(`libpython3.13.a`)이라 불가, brew
    `python@3.13` 사용. ② 번들 안 `sys.executable`은 앱 스텁이 아니라 동봉
    CLI 인터프리터 — 자가 재실행은 반드시 `EXECUTABLEPATH` env로. ③ 에셋은
    `RESOURCEPATH` env 기반 `config.asset_dir()`로만 (`__file__`은
    site-packages.zip 내부). ④ **ad-hoc 서명 금지** — CDHash DR이 빌드마다
    바뀌어 TCC가 풀린다; 고정 "Macsist Signing" 인증서 + 불변
    `CFBundleIdentifier`가 csreq를 고정한다. ⑤ 인증서는 PEM으로 import
    (OpenSSL 3.x p12는 SecKeychainItemImport가 거부), 신뢰는 사용자 도메인
    `add-trusted-cert -p codeSign`으로 충분(sudo 불필요). ⑥ 번들 복사는
    `ditto`만 (cp -R은 서명 깨짐). ⑦ setup.py `packages`에 네임스페이스
    패키지(PyObjCTools)나 미설치 패키지(sniffio)를 넣으면 modulegraph가
    죽는다.
14. **기억(M20):** ① **핫패스에 LLM 금지** — 리콜은 인메모리 IDF 겹침이다.
    핫키→패널 지연이 제품의 심장이라, "관련 기억"을 찾으려 모델을 한 번 더
    부르는 순간 제품이 망가진다. ② 점수는 **질의측**으로 정규화한다(커버리지
    0~1). 절대 IDF 합은 코퍼스와 함께 자라서 고정 컷오프가 표류한다. ③ 질의측과
    색인측은 **같은 `terms_of()`** 를 써야 한다 — 비대칭 토크나이저는 어휘
    검색이 조용히 안 맞는 고전적 원인. ④ 주입 블록은 **조언**이다: 오탐이
    설명 속 단정으로 승격되면 안 되므로 "관련 없으면 무시하라"가 프롬프트에
    박혀 있어야 한다. ⑤ `memory_local_only` — 독서 이력은 프로바이더를 외부로
    바꿨다고 따라 나가면 안 된다. ⑥ 증류 실패 시 **커서를 전진시키지 않는다**
    (재시도 ≫ 유실) — 단, 모델의 **유효한 빈 배열은 성공**이다. 실패로 보면
    그 배치가 큐를 영구히 막는다(M20 백필에서 실제로 149건이 멈췄다). ⑦ 기억을 쓰는 프로세스는 **앱 하나** — CLI는 읽고, 쓰기는
    분산 알림으로 부탁한다. ⑧ `app/memory/__init__.py`는 **import를 두지 않는다**
    — `from memory.store import …`가 distiller→llm_client→httpx를 끌고 오면
    `cli/configure.py`의 stdlib-only 보장이 깨진다(실제로 한 번 깨졌다).
    ⑨ 노트 파일명은 **ASCII slug** — 한글 파일명은 NFC/NFD 정규화가 쓰는 쪽마다
    달라 같은 개념이 두 파일이 된다. ⑩ `retire-cache`는 기억이 비었거나 큐에
    미증류 항목이 남아 있으면 거부한다 — 그 읽기들의 다른 사본은 그 캐시뿐이다.

---

## 8. Repo layout

```
macsist/
  app/                  menu-bar app (PyObjC) — see §1 file map
  app/setup.py          (M12) py2app build config (bundle identity/plist)
  app/macsist_notify.py (M12) extra_scripts notification poster
  server/               FastAPI proxy + mlx backends, launchd deploy
  docs/SPEC.md          this file
  README.md             user-facing: install, server ops, troubleshooting
  CLAUDE.md             agent instructions (lean)
  install.sh            (M10) onboarding installer (Korean TUI, idempotent)
  cli/macsist           (M10) CLI dispatcher (symlinked onto PATH)
  cli/configure.py      (M10) config/Keychain helper (stdlib-only)
  server/requirements.txt  (M10) conda env package pins
```

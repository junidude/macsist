# AGENTS.md — "Hotkey Explain" (local-LLM macOS app)

> Handoff spec for a coding agent. Decisions below are **locked** — implement them, do not relitigate. Where a value is marked *(config)*, expose it in Settings instead of hardcoding.

---

## 0. One-paragraph brief

Build a native macOS **menu-bar app** that, on a global hotkey, captures either (a) the user's **selected text** in any app, or (b) a **screen region as an image**, sends it to a **locally-running OpenAI-compatible LLM server** (`http://127.0.0.1:8000`), and **streams a concise Korean explanation** into a small floating panel positioned near the mouse cursor. No cloud calls. No Electron.

---

## 1. Locked decisions (do not change)

- **Target OS:** macOS **26.2+**, Apple Silicon only. (Reason: MLX uses the M5 Neural Accelerators only on 26.2+. Dev machine is an M5 Max / 128 GB.)
- **App language/UI framework:** **Python 3.13 + PyObjC** (AppKit called directly; no rumps). Menu-bar app via `NSStatusBar`; LSUIElement-equivalent via `NSApp.setActivationPolicy_(Accessory)`. No app-level server. *(Revised 2026-06-11: originally Swift 6 + SwiftUI, but this machine has no Xcode.app — only Command Line Tools — and the user chose Python over installing Xcode.)*
- **Serving model:** the app is a **thin HTTP client**. The LLM runs in a **separate local server process** exposing OpenAI-compatible routes at `http://127.0.0.1:8000`. (This is the "API server + thin app" path — chosen for fast MVP.)
- **Modalities (v1):** text **and** vision (image). **No audio** in v1.
- **Output:** Korean, concise. Streamed token-by-token.
- **Global hotkey lib:** `pynput`. Do not hand-roll Carbon `RegisterEventHotKey`. *(Was SPM `KeyboardShortcuts` in the Swift plan.)*

### Models (config, with defaults)
- **Explain model (default):** `Qwen3.6-35B-A3B` MLX 4-bit (natively multimodal, strong Korean). ~22 GB.
- **Alt explain model (for A/B):** `Gemma-4-12B` (MLX, multimodal, lighter/snappier).
- **Agent backbone (future, not built in v1):** `Qwen3.6-27B` dense (best agentic/coding). Keep the server able to host it in the same pool.
- Pull quants from the `mlx-community` HF org. The exact model id is a Settings field; do not hardcode.

---

## 2. Non-goals (v1)

- No audio input. No in-process MLX. No fine-tuning. No cloud fallback. No multi-user/sync. No App Store / notarization (running from a dev shell is fine for v1; `.app` packaging is a later concern). No conversation history/memory across invocations (each hotkey press is a fresh single-turn request).

---

## 3. Architecture

```
[Global hotkey]
   |
   +-- explainText  --> TextCapture  (AX selected-text  |  fallback: synthetic ⌘C + pasteboard)
   |
   +-- explainRegion --> RegionCapture (interactive screen-region screenshot -> PNG -> base64)
                              |
                        Build chat request (system prompt + user content)
                              |
                        LLMClient --(SSE stream, /v1/chat/completions)--> localhost:8000
                              |
                        ResultPanel (non-activating floating NSPanel near cursor, streams tokens)
```

### Components (Python modules under `app/`)
- **`main.py` / `menubar.py`** — NSApplication entry (Accessory policy) + status item, opens Settings, shows server status (reachable / down).
- **`hotkeys.py`** — registers two global shortcuts via `pynput`: `explainText`, `explainRegion` (bindings are config values).
- **`text_capture.py`**
  - Primary: read focused element's `kAXSelectedTextAttribute` via the Accessibility API (PyObjC `ApplicationServices`).
  - Fallback: if AX returns empty/unsupported, save current `NSPasteboard` contents → post synthetic ⌘C (`CGEvent` via Quartz) → small delay (~80–120 ms) → read pasteboard → **restore** original pasteboard contents.
- **`region_capture.py`**
  - v1 implementation: shell out to `screencapture -i -x <tmp>.png` (interactive region select). Read PNG bytes, base64. Cancelling (Esc) returns non-zero → treat as no-op.
  - (Note for later: ScreenCaptureKit `SCScreenshotManager` is the modern API; `screencapture` is fine and reliable for v1.)
- **`llm_client.py`** — `httpx` streaming POST to `/v1/chat/completions` with `stream: true`; parse SSE `data:` lines, extract `choices[0].delta.content`, yield chunks (runs off the main thread; UI updates marshalled back to the main thread).
- **`result_panel.py`** — `NSPanel` with `NSWindowStyleMaskNonactivatingPanel` + `.floating` level so it never steals focus from the source app. Renders streamed text. Positions near current mouse location, clamped to screen bounds. Dismiss on Esc, click-away, or a new invocation.
- **`settings_window.py` + `config.py`** (config surface) — server base URL, explain model id, alt model id, per-mode system prompts, hotkey bindings, max_tokens, temperature. JSON store at `~/Library/Application Support/HotkeyExplain/config.json`.

---

## 4. Permissions (TCC) — must be handled, not assumed

- **Accessibility** (`AXIsProcessTrustedWithOptions`) — required for AX text read and for posting synthetic ⌘C.
- **Screen Recording** — required for screenshot capture.
- First-run onboarding: detect missing grants, show an explainer, deep-link to the relevant System Settings pane, and re-check on focus. The app must degrade gracefully (clear error in the panel) if a permission is missing rather than silently failing.

---

## 5. Local server setup (prerequisite — document in README, do NOT build into the app)

The app assumes a server is already running. Provide a `README` "Prerequisites" section with two options:

**Option A (default): macMLX**
- Install macMLX (native Swift, MLX-backed, ships text **and** vision models, OpenAI-compatible at `localhost:8000`, multi-model pool + cold-swap).
- Load `Qwen3.6-35B-A3B` (MLX 4-bit) and `Gemma-4-12B` into the pool.
- **Verify the vision path**: confirm the server accepts OpenAI `image_url` (base64 data URL) content and returns a description. If macMLX's VLM image route does not work for the chosen model, use Option B.

**Option B (fallback): Python + mlx-vlm**
- `python3 -m venv .venv && source .venv/bin/activate`
- `pip install mlx-vlm`
- Run mlx-vlm's OpenAI-compatible server (or a thin FastAPI wrapper) serving the VLM on `:8000`.
- Document exact run command + model id used.

Either way the app only ever talks to `http://127.0.0.1:8000/v1/chat/completions`.

---

## 6. API contract (what `LLMClient` sends)

`POST /v1/chat/completions`, header `Content-Type: application/json`, body `stream: true`.

**Text mode**
```json
{
  "model": "<explain-model-id>",
  "stream": true,
  "max_tokens": 512,
  "messages": [
    { "role": "system", "content": "<Korean explain system prompt for text>" },
    { "role": "user", "content": "<captured selected text>" }
  ]
}
```

**Vision mode** (OpenAI multimodal content array)
```json
{
  "model": "<explain-model-id>",
  "stream": true,
  "max_tokens": 512,
  "messages": [
    { "role": "system", "content": "<Korean explain system prompt for image>" },
    { "role": "user", "content": [
        { "type": "text", "text": "이 이미지를 한국어로 간결하게 설명해줘." },
        { "type": "image_url", "image_url": { "url": "data:image/png;base64,<...>" } }
    ]}
  ]
}
```

Parse SSE: for each `data: {json}` line, read `choices[0].delta.content` and append. Terminate on `data: [DONE]`.

Default system prompts (config, editable in Settings):
- Text: `"너는 한국어로 답하는 간결한 해설가다. 선택된 텍스트의 핵심을 3~5문장으로 설명하고, 전문용어는 짧게 풀어줘. 군더더기 금지."`
- Image: `"너는 한국어로 답하는 간결한 해설가다. 이미지의 핵심 내용을 설명하고, 표/코드/도식이면 의미를 풀어줘. 3~6문장."`

---

## 7. Milestones (each must pass its acceptance criteria before moving on)

- **M0 — Scaffold.** Python venv (`app/run.sh`), deps incl. `pynput`/`httpx`/PyObjC, `NSStatusBar` status item, config store.
  *AC:* app launches (no Dock icon), status item appears, Settings window opens and persists edits to config.json.
- **M1 — Server connectivity.** `LLMClient` streams a hardcoded text prompt.
  *AC:* tokens from `localhost:8000` print to console in real time; clean error if server is down.
- **M2 — Text explain (core).** `explainText` hotkey → AX/⌘C capture → stream → floating panel.
  *AC:* select text in TextEdit **and** in a browser, press hotkey; a Korean explanation streams into a panel near the cursor; original clipboard is restored; panel does not steal focus.
- **M3 — Vision explain.** `explainRegion` hotkey → interactive region capture → base64 → vision request → panel.
  *AC:* drag-select a screen region (e.g. a chart or a code screenshot); a Korean explanation of the image streams in.
- **M4 — Settings + model picker.** Configurable server URL, model id, system prompts, hotkeys; runtime model switch.
  *AC:* switch explain model between `Qwen3.6-35B-A3B` and `Gemma-4-12B` without restart; new requests use the new model.
- **M5 — Polish.** Permission onboarding, server-down state, loading/streaming indicator, Esc/click-away dismiss, region-capture cancel handled.
  *AC:* fresh machine with no permissions granted is walked through setup and reaches a working explain in one session.

---

## 8. Gotchas the implementation MUST handle

1. **Clipboard restore:** snapshot all `NSPasteboard.general` items before synthetic ⌘C and restore after reading; never leave the user's clipboard clobbered.
2. **Copy timing:** add a short delay after posting ⌘C before reading the pasteboard, or poll the `changeCount`.
3. **AX empty result:** Electron/web/Java apps often don't expose `kAXSelectedTextAttribute` → always fall back to ⌘C.
4. **Region capture cancel:** `screencapture -i` exits non-zero on Esc → no-op, no error panel.
5. **VLM support lag:** vision for very new models may be immature in the MLX stack. If the explain model's image path errors, surface a clear message and let the user switch to a known-good VLM in Settings.
6. **Non-activating panel:** the result window must use `.nonactivatingPanel` and must not call `makeKeyAndOrderFront` in a way that defocuses the source app.
7. **Streaming cancellation:** pressing the hotkey again cancels the in-flight request and starts a new one.

---

## 9. Suggested repo layout

```
macsist/
  app/
    main.py             entry point (NSApplication, Accessory policy)
    menubar.py          status item + menu
    hotkeys.py          pynput global shortcuts            (M2)
    text_capture.py     AX read + ⌘C fallback              (M2)
    region_capture.py   screencapture -i → base64          (M3)
    llm_client.py       httpx SSE streaming client         (M1)
    result_panel.py     non-activating floating NSPanel    (M2)
    settings_window.py  settings UI
    config.py           JSON config store
    permissions.py      TCC checks + onboarding            (M5)
    requirements.txt
    run.sh              venv bootstrap + run
  server/               local LLM server (proxy + backends, launchd)
  README.md             server setup, permissions, build/run
  docs/SPEC.md          this file
```

---

## 10. First actions for the agent

1. Confirm the Python toolchain (miniforge 3.13) and create `app/.venv` via `app/run.sh`.
2. Install deps from `app/requirements.txt` (PyObjC frameworks, `pynput`, `httpx`).
3. Implement M0 → M5 in order; after each milestone, run against a live `localhost:8000` server and verify the AC.
4. The server is already set up and always-on (launchd) — see `README.md`.
5. Keep all tunables (server URL, model ids, prompts, hotkeys, max_tokens) in the config store, not hardcoded.

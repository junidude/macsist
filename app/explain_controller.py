"""ExplainController — hotkey → capture → LLM stream → panel wiring.

Threading: the pynput callback runs on the listener thread (Quartz only, no
AppKit); each request gets a daemon worker thread iterating stream_chat; every
panel touch is marshalled to the main thread via AppHelper.callAfter. Staleness
is decided ON the main thread (the run loop is the serialization point) by
comparing the request's generation against the current one — worker-side checks
alone would race with the next hotkey press.
"""

import os
import threading

from ApplicationServices import AXIsProcessTrusted
from PyObjCTools import AppHelper
from Quartz import (
    CGEventCreate,
    CGEventGetLocation,
    CGPreflightScreenCaptureAccess,
    CGRequestScreenCaptureAccess,
)

from hotkeys import HotkeyManager
from llm_client import LLMClient, LLMError, StreamHandle
from region_capture import capture_region, to_data_url
from text_capture import capture_selected_text

MSG_NO_ACCESSIBILITY = (
    "손쉬운 사용 권한이 필요합니다 — 방금 연 시스템 설정 창에서 이 앱"
    "(개발 중엔 터미널)을 허용하세요."
)
MSG_NO_SELECTION = "선택된 텍스트가 없습니다."
MSG_NO_SCREEN_RECORDING = (
    "화면 기록 권한이 필요합니다 — 방금 연 시스템 설정 창에서 허용한 뒤 "
    "앱을 재실행하세요."
)

# System Settings deep links (M5 permission onboarding)
URL_PANE_ACCESSIBILITY = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_Accessibility"
)
URL_PANE_SCREEN_RECORDING = (
    "x-apple.systempreferences:com.apple.preference.security"
    "?Privacy_ScreenCapture"
)
MSG_VISION_HINT = (
    " (이미지 미지원 모델일 수 있습니다 — Settings에서 Vision model을 확인하세요.)"
)


def _last_user_image(messages):
    """PNG bytes of the last user message's image part, or None. Used to save
    the region capture alongside its history record (M7.1) — the base64 stays
    out of the JSONL; the store writes the bytes to history_images/."""
    import base64
    prefix = "data:image/png;base64,"
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return None
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if url.startswith(prefix):
                    return base64.b64decode(url[len(prefix):])
        return None
    return None


def _last_user_text(messages):
    """Text of the last user message, for the history record (M7). Multimodal
    content keeps only its text parts — region messages embed the screenshot
    as a base64 image_url, which must never reach history.jsonl."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        return " ".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


class ExplainController:
    def __init__(self, config, panel, health_monitor=None, history=None):
        self.config = config
        self.panel = panel
        self.health_monitor = health_monitor
        self.history = history  # HistoryStore (M7); appends on the main thread
        self.client = LLMClient(config)
        self._lock = threading.Lock()
        self._gen = 0
        self._handle = None
        self._capture_proc = None  # pending `screencapture -i` (region mode)
        # M6: retained conversation for the panel's follow-up input —
        # {gen, messages, model, max_tokens, error_suffix}; None when no
        # session can continue (cleared on preempt/dismiss; region sessions
        # hold the base64 PNG, so clearing also releases that memory).
        self._session = None
        panel.on_dismiss = self._onPanelDismissed
        panel.on_followup = self.submitFollowUp
        self.on_open_history = None  # set by main.py: MainWindow.toggleHistory
        self._opened_panes = set()  # System Settings panes opened this run
        self.hotkeys = HotkeyManager(self._bindings())

    def _bindings(self):
        return {
            str(self.config.get("hotkey_explain_text")): self.explainTextHotkey,
            str(self.config.get("hotkey_explain_region")): self.explainRegionHotkey,
            str(self.config.get("hotkey_open_history")): self._openHistoryHotkey,
        }

    def _openHistoryHotkey(self):
        # pynput listener thread → the window toggle is pure AppKit
        if self.on_open_history is not None:
            AppHelper.callAfter(self.on_open_history)

    def start(self):
        self.hotkeys.start()
        # Verification hooks: fire the hotkey paths programmatically —
        # computer-use cannot send key chords to this bundle-less process.
        # Comma-separated seconds; multiple firings exercise cancellation.
        for env, callback in (
            ("HE_DEBUG_EXPLAIN_AFTER", self.explainTextHotkey),
            ("HE_DEBUG_EXPLAIN_REGION_AFTER", self.explainRegionHotkey),
        ):
            delays = os.environ.get(env)
            if delays:
                for delay in delays.split(","):
                    timer = threading.Timer(float(delay), callback)
                    timer.daemon = True
                    timer.start()
                print(f"{env}: firing at {delays}s", flush=True)
        # M8 hook: dismiss the panel programmatically (fade-out verification)
        delays = os.environ.get("HE_DEBUG_DISMISS_AFTER")
        if delays:
            for delay in delays.split(","):
                timer = threading.Timer(
                    float(delay),
                    lambda: AppHelper.callAfter(self.panel.dismiss),
                )
                timer.daemon = True
                timer.start()
            print(f"HE_DEBUG_DISMISS_AFTER: firing at {delays}s", flush=True)
        # M6 hooks: submit a follow-up / exercise the key-window cycle
        # programmatically (submitFollowUp is main-thread-only → callAfter)
        delays = os.environ.get("HE_DEBUG_FOLLOWUP_AFTER")
        if delays:
            text = os.environ.get(
                "HE_DEBUG_FOLLOWUP_TEXT", "방금 답을 한 문장으로 요약해줘"
            )
            for delay in delays.split(","):
                timer = threading.Timer(
                    float(delay),
                    lambda: AppHelper.callAfter(self.submitFollowUp, text),
                )
                timer.daemon = True
                timer.start()
            print(f"HE_DEBUG_FOLLOWUP_AFTER: firing at {delays}s", flush=True)
        keycycle = os.environ.get("HE_DEBUG_FOLLOWUP_KEYCYCLE")
        if keycycle:
            def cycle():
                def step2():
                    self.panel._unfocusInput()
                    print(
                        "keycycle: key =",
                        bool(self.panel.panel.isKeyWindow()),
                        "visible =", bool(self.panel.panel.isVisible()),
                        flush=True,
                    )

                def step1():
                    self.panel.focusInput()
                    print(
                        "keycycle: key =",
                        bool(self.panel.panel.isKeyWindow()),
                        "fr =",
                        type(self.panel.panel.firstResponder()).__name__,
                        flush=True,
                    )
                    t2 = threading.Timer(
                        1.0, lambda: AppHelper.callAfter(step2)
                    )
                    t2.daemon = True
                    t2.start()

                AppHelper.callAfter(step1)

            timer = threading.Timer(float(keycycle), cycle)
            timer.daemon = True
            timer.start()
            print(f"HE_DEBUG_FOLLOWUP_KEYCYCLE: at {keycycle}s", flush=True)

    def reloadHotkeys(self):
        """Settings saved: re-register with the (possibly changed) bindings."""
        self.hotkeys.rebind(self._bindings())

    def pauseHotkeys_(self, paused):
        self.hotkeys.set_paused(paused)

    # -- hotkey callback (pynput listener thread / debug timer thread) -------

    def _preempt(self):
        """Any hotkey press preempts whatever is in flight — the LLM stream
        and a pending region-selection overlay alike ("last press wins")."""
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._session = None  # new hotkey press = new session (M6)
            if self._handle is not None:
                self._handle.cancel()
            handle = StreamHandle()
            self._handle = handle
            proc = self._capture_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()  # dismisses the selection overlay
        return gen, handle

    def explainTextHotkey(self):
        # Thread-safe cursor sample, top-left-origin global coords; the panel
        # flips to AppKit coords on the main thread.
        loc = CGEventGetLocation(CGEventCreate(None))
        cursor_tl = (loc.x, loc.y)
        gen, handle = self._preempt()
        print(
            f"hotkey explainText gen={gen} cursor=({loc.x:.0f},{loc.y:.0f})",
            flush=True,
        )
        threading.Thread(
            target=self._run, args=(gen, handle, cursor_tl), daemon=True
        ).start()

    def explainRegionHotkey(self):
        # No cursor sample here — the panel belongs next to where the region
        # selection ENDS, sampled in the worker after screencapture returns.
        gen, handle = self._preempt()
        print(f"hotkey explainRegion gen={gen}", flush=True)
        threading.Thread(
            target=self._runRegion, args=(gen, handle), daemon=True
        ).start()

    # -- worker thread ---------------------------------------------------------

    def _run(self, gen, handle, cursor_tl, preset_text=None):
        # preset_text: re-ask from the History window (M7) — skip capture.
        fake = preset_text or os.environ.get("HE_DEBUG_FAKE_TEXT")
        if fake:
            text = fake
        else:
            if not AXIsProcessTrusted():
                self._openSettingsPane(URL_PANE_ACCESSIBILITY)
                self._onMain(gen, self.panel.showMessageAt_text_, cursor_tl,
                             MSG_NO_ACCESSIBILITY)
                return
            text = capture_selected_text(self.config)
        if handle.cancelled:
            return
        if not text.strip():
            self._onMain(gen, self.panel.showMessageAt_text_, cursor_tl,
                         MSG_NO_SELECTION)
            return
        self._onMain(gen, self.panel.beginSessionAt_, cursor_tl)
        suffix, max_tokens, detail = self._detail()
        messages = [
            {"role": "system",
             "content": self.config.get("system_prompt_text") + suffix},
            {"role": "user", "content": text},
        ]
        self._stream(gen, handle, messages, max_tokens=max_tokens,
                     mode="text", detail=detail)

    def _runRegion(self, gen, handle):
        if not CGPreflightScreenCaptureAccess():
            # registers the app in System Settings; prompts at most once
            CGRequestScreenCaptureAccess()
            self._openSettingsPane(URL_PANE_SCREEN_RECORDING)
            loc = CGEventGetLocation(CGEventCreate(None))
            self._onMain(gen, self.panel.showMessageAt_text_, (loc.x, loc.y),
                         MSG_NO_SCREEN_RECORDING)
            return
        with self._lock:
            prev = self._capture_proc
        if prev is not None:
            try:
                prev.wait(timeout=1)  # two -i overlays can't coexist
            except Exception:
                pass
        png, center = capture_region(
            self.config,
            proc_holder=self._setCaptureProc,
            debug_rect=os.environ.get("HE_DEBUG_REGION_RECT"),
        )
        if png is None or handle.cancelled:
            return  # Esc / preempted / capture-to-clipboard — silent no-op
        if center is not None:
            # panel centered on the captured region (M8 polish) — not stuck
            # small under the drag's end point
            anchor, centered = center, True
        else:
            # window mode / click: selection rect unknown — fall back to the
            # mouse position where the capture ended
            loc = CGEventGetLocation(CGEventCreate(None))
            anchor, centered = (loc.x, loc.y), False
        self._runImage(
            gen, handle, anchor,
            str(self.config.get("user_prompt_image")), png, centered,
        )

    def _runImage(self, gen, handle, cursor_tl, user_text, png,
                  centered=False):
        """Vision request tail shared by region capture and history re-ask."""
        self._onMain(gen, self.panel.beginSessionAt_centered_, cursor_tl,
                     centered)
        suffix, max_tokens, detail = self._detail()
        messages = [
            {"role": "system",
             "content": self.config.get("system_prompt_image") + suffix},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": to_data_url(png)}},
            ]},
        ]
        self._stream(
            gen, handle, messages,
            model=str(self.config.get("vision_model")),
            max_tokens=max_tokens,
            error_suffix=MSG_VISION_HINT,
            mode="region",
            detail=detail,
        )

    def _openSettingsPane(self, url):
        """Open the System Settings privacy pane the user needs — once per
        run per pane, so repeated hotkey presses don't keep yanking System
        Settings to the front. Worker thread → marshal to main (AppKit);
        deliberately NOT generation-checked: a preempting press must not
        suppress the pane."""
        if url in self._opened_panes:
            return
        self._opened_panes.add(url)

        def open_pane():
            from AppKit import NSWorkspace
            from Foundation import NSURL
            print(f"opening System Settings pane: {url}", flush=True)
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

        AppHelper.callAfter(open_pane)

    def _setCaptureProc(self, proc):
        with self._lock:
            self._capture_proc = proc

    def _detail(self):
        """(prompt suffix, max_tokens, level key) for the configured detail."""
        levels = self.config.get("detail_levels")
        key = str(self.config.get("explain_detail"))
        level = levels.get(key)
        if not level:
            return "", None, key
        return str(level.get("prompt_suffix", "")), level.get("max_tokens"), key

    def _stream(self, gen, handle, messages, model=None, max_tokens=None,
                error_suffix="", mode="text", detail=None):
        reasoning_chars = [0]
        parts = []  # accumulated content → assistant message for follow-ups

        def on_reasoning(chunk):
            # thinking models stream CoT before content; show progress, not the CoT
            reasoning_chars[0] += len(chunk)
            self._onMain(gen, self.panel.showThinking_, reasoning_chars[0])

        def commit():
            # spec §5.1: the follow-up input appears after success AND after
            # LLM errors; capture-stage failures never reach _stream.
            self._onMain(
                gen, self._commitSession, gen, messages, "".join(parts),
                model, max_tokens, error_suffix, mode, detail,
            )

        got_content = False
        try:
            for chunk in self.client.stream_chat(
                messages, handle, on_reasoning=on_reasoning, model=model,
                max_tokens=max_tokens,
            ):
                got_content = True
                parts.append(chunk)
                self._onMain(gen, self.panel.appendChunk_, chunk)
        except LLMError as err:
            # str(err) is the whole user-facing story — no tracebacks in the UI
            self._onMain(gen, self.panel.showErrorText_, str(err) + error_suffix)
            commit()
            if self.health_monitor is not None:
                # update the menu bar now, not a poll interval later
                self.health_monitor.poke()
            return
        if handle.cancelled:
            return
        if got_content:
            self._onMain(gen, self.panel.finishStream)
        else:
            detail = (
                f" 사고(thinking)에 {reasoning_chars[0]}자를 쓰고 끝났습니다 — "
                "max_tokens를 늘려보세요."
                if reasoning_chars[0]
                else " 서버/모델 설정을 확인하세요."
            )
            self._onMain(
                gen, self.panel.showErrorText_,
                "모델이 응답 내용을 내지 않았습니다." + detail + error_suffix,
            )
        commit()

    # -- follow-up session (M6) ------------------------------------------------

    def _commitSession(self, gen, messages, content, model, max_tokens,
                       error_suffix, mode, detail):
        """Main thread (via _onMain). Retain the finished conversation so the
        panel's input can extend it. The synthetic assistant message on empty
        content keeps user/assistant alternation valid for chat templates."""
        assistant = (
            content if content.strip() else "(이전 요청이 응답 없이 끝났습니다.)"
        )
        with self._lock:
            if gen != self._gen:
                return
            self._session = {
                "gen": gen,
                "messages": list(messages)
                + [{"role": "assistant", "content": assistant}],
                "model": model,
                "max_tokens": max_tokens,
                "error_suffix": error_suffix,
                "detail": detail,  # follow-up commits inherit it (M7 history)
            }
        # M7: one history record per completed request. Content-less runs
        # (pure errors) are not history; the input snippet takes only the
        # text parts of the user message — the region base64 never leaves
        # the messages list.
        if self.history is not None and content.strip():
            self.history.append(
                mode,
                model or str(self.config.get("explain_model")),
                _last_user_text(messages),
                content,
                detail,
                image_png=(
                    _last_user_image(messages) if mode == "region" else None
                ),
            )
        self.panel.showFollowUpInput()

    def submitFollowUp(self, text):
        """Main thread (panel input action / debug hook). Same preemption
        semantics as a hotkey press — bumps the generation so chunks already
        queued by a still-streaming follow-up go stale — but keeps the panel
        transcript and the session. A mid-stream re-submit drops the
        uncommitted partial answer (and its question) from the LLM context;
        both stay visible in the transcript — same flavor as preemption."""
        with self._lock:
            session = self._session
            if session is None or session["gen"] != self._gen:
                return  # preempted/dismissed since the input appeared
            self._gen += 1
            gen = self._gen
            session["gen"] = gen
            if self._handle is not None:
                self._handle.cancel()
            handle = StreamHandle()
            self._handle = handle
            messages = self._capTurns(
                session["messages"] + [{"role": "user", "content": text}]
            )
            model = session["model"]
            max_tokens = session["max_tokens"]
            error_suffix = session["error_suffix"]
            detail = session.get("detail")
        print(f"follow-up gen={gen} msgs={len(messages)}", flush=True)
        self.panel.beginFollowUp_(text)  # we ARE the main thread
        threading.Thread(
            target=self._stream, args=(gen, handle, messages),
            kwargs={
                "model": model,
                "max_tokens": max_tokens,
                "error_suffix": error_suffix,
                "mode": "followup",
                "detail": detail,
            },
            daemon=True,
        ).start()

    def resubmit_text(self, text):
        """Main thread (History window re-ask, M7). Same semantics as the
        text hotkey — preempts anything in flight, panel near the cursor —
        but the input is the stored history snippet instead of a capture."""
        loc = CGEventGetLocation(CGEventCreate(None))
        cursor_tl = (loc.x, loc.y)
        gen, handle = self._preempt()
        print(f"re-ask gen={gen} chars={len(text)}", flush=True)
        threading.Thread(
            target=self._run, args=(gen, handle, cursor_tl),
            kwargs={"preset_text": text}, daemon=True,
        ).start()

    def resubmit_image(self, text, png):
        """Main thread (History window re-ask of a region record, M7.1):
        re-sends the saved capture PNG with the stored prompt."""
        loc = CGEventGetLocation(CGEventCreate(None))
        gen, handle = self._preempt()
        print(f"re-ask(image) gen={gen} png={len(png)}b", flush=True)
        threading.Thread(
            target=self._runImage,
            args=(gen, handle, (loc.x, loc.y), text, png),
            daemon=True,
        ).start()

    def _capTurns(self, msgs):
        """system + at most 2*(followup_max_turns+1) chat messages; drop the
        oldest user/assistant pair first. Region sessions eventually drop the
        image message — intended ("oldest dropped"), bounds payload size."""
        limit = 2 * (int(self.config.get("followup_max_turns")) + 1)
        head, tail = msgs[:1], msgs[1:]
        while len(tail) > limit:
            tail = tail[2:]
        return head + tail

    # -- main-thread marshalling ------------------------------------------------

    def _onMain(self, gen, fn, *args):
        def call():
            with self._lock:
                stale = gen != self._gen
            if not stale:
                fn(*args)

        AppHelper.callAfter(call)

    def _onPanelDismissed(self):
        # Main thread (event monitor). Invalidate queued chunks, stop the
        # stream feeding the now-hidden panel, and drop a pending selection.
        with self._lock:
            self._gen += 1
            self._session = None
            if self._handle is not None:
                self._handle.cancel()
                self._handle = None
            proc = self._capture_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

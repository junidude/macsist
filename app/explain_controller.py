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


class ExplainController:
    def __init__(self, config, panel, health_monitor=None):
        self.config = config
        self.panel = panel
        self.health_monitor = health_monitor
        self.client = LLMClient(config)
        self._lock = threading.Lock()
        self._gen = 0
        self._handle = None
        self._capture_proc = None  # pending `screencapture -i` (region mode)
        panel.on_dismiss = self._onPanelDismissed
        self._opened_panes = set()  # System Settings panes opened this run
        self.hotkeys = HotkeyManager(self._bindings())

    def _bindings(self):
        return {
            str(self.config.get("hotkey_explain_text")): self.explainTextHotkey,
            str(self.config.get("hotkey_explain_region")): self.explainRegionHotkey,
        }

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

    def _run(self, gen, handle, cursor_tl):
        fake = os.environ.get("HE_DEBUG_FAKE_TEXT")  # bypass capture in tests
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
        suffix, max_tokens = self._detail()
        messages = [
            {"role": "system",
             "content": self.config.get("system_prompt_text") + suffix},
            {"role": "user", "content": text},
        ]
        self._stream(gen, handle, messages, max_tokens=max_tokens)

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
        png = capture_region(
            self.config,
            proc_holder=self._setCaptureProc,
            debug_rect=os.environ.get("HE_DEBUG_REGION_RECT"),
        )
        if png is None or handle.cancelled:
            return  # Esc / preempted / capture-to-clipboard — silent no-op
        # selection just ended; the mouse sits at its end point
        loc = CGEventGetLocation(CGEventCreate(None))
        self._onMain(gen, self.panel.beginSessionAt_, (loc.x, loc.y))
        suffix, max_tokens = self._detail()
        messages = [
            {"role": "system",
             "content": self.config.get("system_prompt_image") + suffix},
            {"role": "user", "content": [
                {"type": "text", "text": self.config.get("user_prompt_image")},
                {"type": "image_url", "image_url": {"url": to_data_url(png)}},
            ]},
        ]
        self._stream(
            gen, handle, messages,
            model=str(self.config.get("vision_model")),
            max_tokens=max_tokens,
            error_suffix=MSG_VISION_HINT,
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
        """(prompt suffix, max_tokens) for the configured detail level."""
        levels = self.config.get("detail_levels")
        level = levels.get(str(self.config.get("explain_detail")))
        if not level:
            return "", None
        return str(level.get("prompt_suffix", "")), level.get("max_tokens")

    def _stream(self, gen, handle, messages, model=None, max_tokens=None,
                error_suffix=""):
        reasoning_chars = [0]

        def on_reasoning(chunk):
            # thinking models stream CoT before content; show progress, not the CoT
            reasoning_chars[0] += len(chunk)
            self._onMain(gen, self.panel.showThinking_, reasoning_chars[0])

        got_content = False
        try:
            for chunk in self.client.stream_chat(
                messages, handle, on_reasoning=on_reasoning, model=model,
                max_tokens=max_tokens,
            ):
                got_content = True
                self._onMain(gen, self.panel.appendChunk_, chunk)
        except LLMError as err:
            # str(err) is the whole user-facing story — no tracebacks in the UI
            self._onMain(gen, self.panel.showErrorText_, str(err) + error_suffix)
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
            if self._handle is not None:
                self._handle.cancel()
                self._handle = None
            proc = self._capture_proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

"""Deliverer — push assistant proposals to Telegram via Hermes (M15).

`hermes send -t telegram` reuses Hermes's bot credentials and needs NO running
gateway. Best-effort: the send runs on a worker thread with a timeout and never
blocks or crashes the assistant loop — the native glass panel is always shown
regardless. Telegram is the away / quiet-hours channel (and a manual test).

NOTE: actual delivery depends on the network reaching api.telegram.org's bot
API. Where that's blocked, sends time out silently (logged, never fatal).
"""

import os
import subprocess
import threading
from datetime import datetime

try:
    from Quartz import (
        CGEventSourceSecondsSinceLastEventType,
        kCGAnyInputEventType,
        kCGEventSourceStateHIDSystemState,
    )
except Exception:  # pragma: no cover — Quartz always present on macOS
    CGEventSourceSecondsSinceLastEventType = None


class Deliverer:
    def __init__(self, config):
        self.config = config

    def _hermes_bin(self):
        return os.path.expanduser(str(self.config.get("hermes_bin")))

    def telegram_enabled(self):
        return bool(self.config.get("assistant_telegram_enabled"))

    # -- presence ------------------------------------------------------------

    def idle_seconds(self):
        if CGEventSourceSecondsSinceLastEventType is None:
            return 0.0
        try:
            return float(CGEventSourceSecondsSinceLastEventType(
                kCGEventSourceStateHIDSystemState, kCGAnyInputEventType))
        except Exception:
            return 0.0

    def is_away(self):
        return self.idle_seconds() >= float(
            self.config.get("assistant_away_seconds"))

    def in_quiet_hours(self):
        window = self.config.get("assistant_quiet_hours") or []
        if len(window) != 2:
            return False
        start, end = int(window[0]), int(window[1])
        if start == end:
            return False
        hour = datetime.now().astimezone().hour
        return start <= hour < end if start < end else (hour >= start
                                                        or hour < end)

    def should_telegram(self):
        """Route to Telegram only when the user is away or in quiet hours —
        the panel covers the at-the-desk case."""
        return self.telegram_enabled() and (self.is_away()
                                            or self.in_quiet_hours())

    # -- send (fire-and-forget) ---------------------------------------------

    def send_telegram(self, text):
        threading.Thread(target=self._send, args=(text,), daemon=True,
                         name="assistant-telegram").start()

    def _send(self, text):
        bin_ = self._hermes_bin()
        target = str(self.config.get("assistant_telegram_target") or "telegram")
        try:
            r = subprocess.run(
                [bin_, "send", "-t", target, "-q", text],
                capture_output=True, text=True, timeout=25,
            )
        except Exception as exc:  # timeout / OSError — never fatal
            print(f"deliver: telegram error {exc!r}", flush=True)
            return
        if r.returncode != 0:
            print("deliver: telegram failed: "
                  f"{(r.stderr or r.stdout or '').strip()[:200]}", flush=True)
        else:
            print("deliver: telegram sent", flush=True)

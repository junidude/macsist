"""gmail_monitor.py — inbox poller (M17, §6.4). A health.py / monitor.py clone.

One daemon thread, a threading.Event sleep with poke(), gated on `gmail_enabled`
(OFF by default). Each tick asks GmailClient for messages newer than the stored
cursor (`history.list`, or `messages.list` on a resync), drops ones already seen
(a ~500-id ring), fetches their headers+snippet, advances the cursor, and
marshals the batch to the main thread via AppHelper.callAfter(on_gmail, metas).

Triage + proposal creation happen on the controller side — this thread only does
network I/O and cursor bookkeeping. The cursor file (`assistant_gmail_state.json`)
has a single writer: this thread. Never touches AppKit.
"""

import json
import os
import threading

from PyObjCTools import AppHelper

from config import CONFIG_DIR

from assistant.gmail_client import GmailClient

GMAIL_STATE_PATH = CONFIG_DIR / "assistant_gmail_state.json"
_RING_MAX = 500


class GmailState:
    """{history_id, last_poll_ts, seen_msg_ids_ring}. Single-writer (the
    monitor thread); atomic temp+replace like the history_store convention."""

    def __init__(self, path=None):
        self.path = path or GMAIL_STATE_PATH
        self._data = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {"history_id": None, "last_poll_ts": None, "seen": []}

    @property
    def history_id(self):
        return self._data.get("history_id")

    def seen(self, mid):
        return mid in self._data.get("seen", [])

    def remember(self, ids):
        ring = self._data.get("seen", [])
        ring.extend(m for m in ids if m not in ring)
        self._data["seen"] = ring[-_RING_MAX:]

    def commit(self, history_id, ts):
        self._data["history_id"] = history_id
        self._data["last_poll_ts"] = ts
        tmp = self.path.with_suffix(".json.tmp")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


def _now():
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


class GmailMonitor:
    def __init__(self, config, on_gmail=None, client=None, state=None):
        self.config = config
        self.client = client or GmailClient(config)
        self.state = state or GmailState()
        self.on_gmail = on_gmail        # MAIN thread: (metas: list[dict])
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if not bool(self.config.get("gmail_enabled")):
            print("gmail monitor: disabled (gmail_enabled=False)", flush=True)
            return
        self._thread = threading.Thread(
            target=self._loop, name="assistant-gmail", daemon=True)
        self._thread.start()
        print("gmail monitor started", flush=True)

    def poke(self):
        self._wake.set()

    def _loop(self):
        while True:
            try:
                self._poll()
            except Exception as exc:        # never let the daemon thread die
                print(f"gmail monitor: poll error {exc!r}", flush=True)
            self._wake.wait(
                timeout=float(self.config.get("gmail_poll_interval")))
            self._wake.clear()

    def _poll(self):
        if not bool(self.config.get("gmail_enabled")):
            return
        cursor = self.state.history_id
        if cursor:
            res = self.client.history_since(cursor)
            if res.get("resync"):
                print("gmail: cursor expired -> resync", flush=True)
                res = self.client.list_query(
                    self.config.get("gmail_query_filter"),
                    self.config.get("gmail_max_triage_per_poll"))
        else:
            # first run: seed from the filter; cursor anchored to current state
            res = self.client.list_query(
                self.config.get("gmail_query_filter"),
                self.config.get("gmail_max_triage_per_poll"))
        if res.get("error"):
            print(f"gmail: {res['error']}", flush=True)
            return
        new_ids = [m for m in (res.get("ids") or []) if not self.state.seen(m)]
        cap = int(self.config.get("gmail_max_triage_per_poll"))
        new_ids = new_ids[:cap]
        history_id = res.get("history_id") or cursor
        if not new_ids:
            self.state.remember([])           # no-op, keeps ring intact
            if history_id:
                self.state.commit(history_id, _now())
            return
        metas = []
        for mid in new_ids:
            meta = self.client.get_meta(mid)
            if not meta.get("error"):
                metas.append(meta)
        self.state.remember(new_ids)
        if history_id:
            self.state.commit(history_id, _now())
        print(f"gmail: {len(metas)} new message(s)", flush=True)
        if metas and self.on_gmail is not None:
            AppHelper.callAfter(self.on_gmail, metas)

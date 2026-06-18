"""calendar_monitor.py — read-only calendar poller + alert engine (M18, §6.5).

A monitor.py/gmail_monitor.py clone: one daemon thread, gated on
`calendar_enabled` (OFF by default), never touches AppKit. Two cadences in one
loop — a fast tick (`calendar_monitor_tick_sec`) evaluates the in-memory event
set for **imminent** ("N분 후") and **conflict** (double-booking) alerts, and a
slow refetch (`calendar_poll_interval_sec`, ETag-conditional) refreshes events
from the ICS. Alerts are DETERMINISTIC (no LLM) and fired at most once per event
(`alerted{event_key}` in calendar_state.json). Each new alert marshals to the
main thread via AppHelper.callAfter(on_alert, alert).

State/snapshot files are single-writer on this thread (atomic temp+replace).
calendar_snapshot.json is derived (for the CLI/doctor); the working event set is
held in memory and rebuilt by a refetch after a restart.
"""

import json
import os
import threading
from datetime import datetime, timedelta

from PyObjCTools import AppHelper

from config import CONFIG_DIR

from assistant import calendar_unify as unify
from assistant.calendar_ics import IcsClient

SNAPSHOT_PATH = CONFIG_DIR / "calendar_snapshot.json"
STATE_PATH = CONFIG_DIR / "calendar_state.json"
_ALERT_TTL = timedelta(days=1)   # prune alerted-keys older than this


def _now():
    return datetime.now().astimezone()


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


class CalendarState:
    """{etag, last_fetch_ts, alerted{key: iso_ts}} — single-writer (monitor)."""

    def __init__(self, path=None):
        self.path = path or STATE_PATH
        self._data = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault("alerted", {})
                return d
        except (OSError, ValueError):
            pass
        return {"etag": None, "last_fetch_ts": None, "alerted": {}}

    @property
    def etag(self):
        return self._data.get("etag")

    def last_fetch(self):
        ts = self._data.get("last_fetch_ts")
        try:
            return datetime.fromisoformat(ts) if ts else None
        except (ValueError, TypeError):
            return None

    def alerted(self, key):
        return key in self._data.get("alerted", {})

    def mark(self, key, now):
        self._data.setdefault("alerted", {})[key] = now.isoformat()

    def note_fetch(self, etag, now):
        self._data["etag"] = etag
        self._data["last_fetch_ts"] = now.isoformat()

    def prune(self, now):
        keep = {}
        for k, ts in self._data.get("alerted", {}).items():
            try:
                if now - datetime.fromisoformat(ts) < _ALERT_TTL:
                    keep[k] = ts
            except (ValueError, TypeError):
                pass
        self._data["alerted"] = keep

    def save(self):
        _atomic_write(self.path, self._data)


def _serialize(events):
    out = []
    for e in events:
        d = dict(e)
        d["start"] = e["start"].isoformat()
        d["end"] = e["end"].isoformat()
        out.append(d)
    return out


class CalendarMonitor:
    def __init__(self, config, on_alert=None, client=None, state=None):
        self.config = config
        self.client = client or IcsClient(config)
        self.state = state or CalendarState()
        self.on_alert = on_alert        # MAIN thread: (alert: dict)
        self._events = None             # working set (aware datetimes); None=stale
        self._wake = threading.Event()
        self._thread = None

    def start(self):
        if not bool(self.config.get("calendar_enabled")):
            print("calendar monitor: disabled (calendar_enabled=False)",
                  flush=True)
            return
        self._thread = threading.Thread(
            target=self._loop, name="assistant-calendar", daemon=True)
        self._thread.start()
        print("calendar monitor started", flush=True)

    def poke(self):
        self._events = None             # force a refetch on the next tick
        self._wake.set()

    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as exc:      # never let the daemon thread die
                print(f"calendar monitor: tick error {exc!r}", flush=True)
            self._wake.wait(
                timeout=float(self.config.get("calendar_monitor_tick_sec")))
            self._wake.clear()

    def _tick(self):
        if not bool(self.config.get("calendar_enabled")):
            return
        now = _now()
        if self._should_refetch(now):
            self._refetch(now)
        if self._events:
            self._evaluate(now)

    def _should_refetch(self, now):
        if self._events is None:
            return True
        last = self.state.last_fetch()
        if last is None:
            return True
        return (now - last).total_seconds() >= float(
            self.config.get("calendar_poll_interval_sec"))

    def _refetch(self, now):
        res = self.client.fetch(self.state.etag)
        if res.get("error"):
            print(f"calendar: {res['error']}", flush=True)
            if self._events is None:
                self._events = []          # avoid hammering on a hard error
            return
        if res.get("status") == "unchanged":
            self.state.note_fetch(self.state.etag, now)
            self.state.save()
            if self._events is None:       # restart with a valid cache: reload
                self._events = self._load_snapshot()
            return
        events = unify.in_window(
            unify.merge_dedup(res.get("events") or []), now,
            int(self.config.get("calendar_window_days")))
        self._events = events
        _atomic_write(SNAPSHOT_PATH,
                      {"generated_ts": now.isoformat(),
                       "events": _serialize(events)})
        self.state.note_fetch(res.get("etag"), now)
        self.state.save()
        print(f"calendar: {len(events)} event(s) in window", flush=True)

    def _load_snapshot(self):
        try:
            with open(SNAPSHOT_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        out = []
        for e in data.get("events", []):
            try:
                e = dict(e)
                e["start"] = datetime.fromisoformat(e["start"])
                e["end"] = datetime.fromisoformat(e["end"])
                out.append(e)
            except (ValueError, KeyError):
                pass
        return out

    def _evaluate(self, now):
        alerts, changed = [], False
        lead = int(self.config.get("calendar_alert_lead_min"))
        for e in unify.imminent(self._events, now, lead):
            key = unify.event_key("imminent", e)
            if self.state.alerted(key):
                continue
            self.state.mark(key, now)
            changed = True
            mins = max(int((e["start"] - now).total_seconds() // 60), 0)
            alerts.append({"kind": "imminent", "key": key,
                           "summary": e["summary"], "start": e["start"].isoformat(),
                           "location": e.get("location", ""), "mins": mins})
        if bool(self.config.get("calendar_conflict_enabled")):
            for a, b in unify.conflict_pairs(self._events):
                key = unify.event_key("conflict", a, b)
                if self.state.alerted(key):
                    continue
                self.state.mark(key, now)
                changed = True
                alerts.append({
                    "kind": "conflict", "key": key,
                    "summary": f"{a['summary']} ↔ {b['summary']}",
                    "a_summary": a["summary"], "a_time": _hm(a["start"]),
                    "b_summary": b["summary"], "b_time": _hm(b["start"]),
                    "start": a["start"].isoformat()})
        if changed:
            self.state.prune(now)
            self.state.save()
        for alert in alerts:
            if self.on_alert is not None:
                AppHelper.callAfter(self.on_alert, alert)


def _hm(dt):
    return dt.strftime("%H:%M")

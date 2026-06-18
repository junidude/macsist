"""calendar_ics.py — read-only iCalendar (RFC-5545) connector (M18, §6.5).

Fetches a single **Google private secret-iCal URL** (stored in the Keychain, not
config) over httpx with ETag / If-None-Match (304 → unchanged), and parses the
VEVENTs into normalized event dicts. A deliberately small parser — no new
dependency (stdlib `zoneinfo` for timezones, the existing `httpx` for fetch):
line-unfolding, DTSTART/DTEND with TZID / `Z` / floating / `VALUE=DATE`, and a
**bounded recurrence expansion** (FREQ=DAILY/WEEKLY/MONTHLY + INTERVAL/COUNT/
UNTIL/BYDAY) within the requested window only. Exotic rules / unparseable events
are skipped and logged — a calendar poll must never raise into the daemon.

Worker-thread only (network). Returns dicts; transport / non-2xx → {"error": …}
(gmail_client.py convention). Event dicts carry aware `datetime` objects; the
monitor serializes them for the snapshot, calendar_unify works on them directly.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

import keychain
from config import CALENDAR_ICS_ACCOUNT

_WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_MAX_OCCURRENCES = 1000   # safety cap on recurrence expansion per event


def ics_url():
    """The configured secret iCal URL from the Keychain, or None."""
    try:
        return keychain.get_key(CALENDAR_ICS_ACCOUNT)
    except keychain.KeychainError:
        return None


def is_connected():
    return bool(ics_url())


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _unfold(text):
    """RFC-5545 line unfolding: a CRLF followed by space/tab continues the
    previous line. Returns logical lines."""
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _unescape(value):
    return (value.replace("\\n", "\n").replace("\\N", "\n")
            .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\"))


def _split_line(line):
    """'NAME;PARAM=v:VALUE' -> (name, {param: value}, value)."""
    if ":" not in line:
        return None
    head, value = line.split(":", 1)
    parts = head.split(";")
    name = parts[0].upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return name, params, value


def _parse_dt(value, params, local_tz):
    """(aware datetime, all_day). Handles VALUE=DATE, TZID=…, trailing Z (UTC),
    and floating local time."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=local_tz), True
    if value.endswith("Z"):
        dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=timezone.utc), False
    dt = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            return dt.replace(tzinfo=ZoneInfo(tzid)), False
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return dt.replace(tzinfo=local_tz), False   # floating → local


def _parse_rrule(value):
    rule = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            rule[k.upper()] = v.upper()
    return rule


def _vevents(lines):
    """Group unfolded lines into VEVENT property dicts (EXDATE accumulates)."""
    events, cur = [], None
    for line in lines:
        u = line.strip().upper()
        if u == "BEGIN:VEVENT":
            cur = {"_exdate": []}
        elif u == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None:
            parsed = _split_line(line)
            if not parsed:
                continue
            name, params, value = parsed
            if name == "EXDATE":
                cur["_exdate"].append((params, value))
            else:
                cur[name] = (params, value)
    return events


def _expand(raw, win_start, win_end, local_tz):
    """One VEVENT → occurrence event dicts overlapping [win_start, win_end].
    Recurrence is expanded only within the window (bounded)."""
    if "DTSTART" not in raw:
        return []
    try:
        start, all_day = _parse_dt(raw["DTSTART"][1], raw["DTSTART"][0], local_tz)
    except (ValueError, KeyError):
        return []
    if "DTEND" in raw:
        try:
            end, _ = _parse_dt(raw["DTEND"][1], raw["DTEND"][0], local_tz)
        except ValueError:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
    else:
        end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
    duration = end - start
    summary = _unescape(raw.get("SUMMARY", ("", ""))[1]).strip()
    location = _unescape(raw.get("LOCATION", ("", ""))[1]).strip()
    uid = raw.get("UID", ("", ""))[1].strip() or f"{summary}:{start.isoformat()}"

    exdates = set()
    for params, value in raw.get("_exdate", []):
        for v in value.split(","):
            try:
                ex, _ = _parse_dt(v, params, local_tz)
                exdates.add(ex)
            except ValueError:
                pass

    def _emit(s):
        return {"uid": uid, "summary": summary or "(no title)",
                "start": s, "end": s + duration, "location": location,
                "all_day": all_day, "source": "google"}

    starts = ([start] if "RRULE" not in raw
              else _recur(start, _parse_rrule(raw["RRULE"][1]),
                          win_start, win_end))
    out = []
    for s in starts:
        if s in exdates:
            continue
        if s + duration >= win_start and s <= win_end:
            out.append(_emit(s))
    return out


def _recur(start, rule, win_start, win_end):
    """Occurrence start datetimes within the window for DAILY/WEEKLY/MONTHLY."""
    freq = rule.get("FREQ", "")
    interval = max(int(rule.get("INTERVAL", "1") or 1), 1)
    count = int(rule["COUNT"]) if "COUNT" in rule else None
    until = None
    if "UNTIL" in rule:
        u = rule["UNTIL"]
        try:
            until = (datetime.strptime(u[:15], "%Y%m%dT%H%M%S").replace(
                        tzinfo=timezone.utc) if "T" in u
                     else datetime.strptime(u[:8], "%Y%m%d").replace(
                        tzinfo=start.tzinfo))
        except ValueError:
            until = None
    bydays = [_WEEKDAY[d] for d in rule.get("BYDAY", "").split(",")
              if d in _WEEKDAY]
    out, emitted = [], 0

    def _keep(dt):
        nonlocal emitted
        if until is not None and dt > until:
            return False
        if count is not None and emitted >= count:
            return False
        if dt <= win_end:
            if dt >= win_start - timedelta(days=1):
                out.append(dt)
            emitted += 1
        return dt <= win_end

    if freq == "WEEKLY" and bydays:
        # Monday of start's week, at start's time-of-day
        week = (start - timedelta(days=start.weekday())).replace(
            hour=start.hour, minute=start.minute, second=start.second,
            microsecond=0)
        for _ in range(_MAX_OCCURRENCES):
            for wd in sorted(bydays):
                occ = week + timedelta(days=wd)
                if occ < start:
                    continue
                if not _keep(occ):
                    return out
            week += timedelta(weeks=interval)
            if week > win_end:
                break
        return out

    step = {"DAILY": timedelta(days=interval),
            "WEEKLY": timedelta(weeks=interval),
            "MONTHLY": None}.get(freq)
    cur = start
    for _ in range(_MAX_OCCURRENCES):
        if not _keep(cur):
            break
        if freq == "MONTHLY":
            cur = _add_months(cur, interval)
        elif step is not None:
            cur = cur + step
        else:
            break
        if cur > win_end:
            break
    return out


def _add_months(dt, months):
    m = dt.month - 1 + months
    year = dt.year + m // 12
    month = m % 12 + 1
    # clamp day to the month's length (skip-style: pin to last valid day)
    import calendar as _cal
    day = min(dt.day, _cal.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def parse_ics(text, win_start, win_end):
    """All occurrences in [win_start, win_end]. Never raises — bad events skip."""
    local_tz = _local_tz()
    events = []
    for raw in _vevents(_unfold(text)):
        try:
            events.extend(_expand(raw, win_start, win_end, local_tz))
        except Exception as exc:  # one bad event must not drop the whole poll
            print(f"calendar_ics: skip event ({exc!r})", flush=True)
    return events


class IcsClient:
    def __init__(self, config):
        self.config = config

    def fetch(self, etag=None):
        """Fetch + parse the configured ICS. Returns one of:
        {"status":"unchanged"} | {"status":"ok","events":[...],"etag":…} |
        {"error": …}. Events are bounded to [now-1h, now+window_days]."""
        url = ics_url()
        if not url:
            return {"error": "calendar.not_connected"}
        headers = {"If-None-Match": etag} if etag else {}
        try:
            r = httpx.get(url, headers=headers, timeout=30,
                          follow_redirects=True)
        except httpx.HTTPError as exc:
            return {"error": f"ics fetch error: {exc.__class__.__name__}"}
        if r.status_code == 304:
            return {"status": "unchanged"}
        if r.status_code >= 400:
            return {"error": f"ics HTTP {r.status_code}"}
        now = datetime.now().astimezone()
        win_start = now - timedelta(hours=1)
        win_end = now + timedelta(days=int(self.config.get("calendar_window_days")))
        events = parse_ics(r.text, win_start, win_end)
        return {"status": "ok", "events": events,
                "etag": r.headers.get("ETag")}


def _main():
    """Smoke test from app/: `python -m assistant.calendar_ics`."""
    import json

    from config import ConfigStore

    res = IcsClient(ConfigStore()).fetch()
    if res.get("error"):
        print("error:", res["error"])
        return
    print(res.get("status"), "events:", len(res.get("events", [])))
    for e in (res.get("events") or [])[:8]:
        print(f"  {e['start'].isoformat()}  {e['summary']}"
              f"{' (all-day)' if e['all_day'] else ''}")


if __name__ == "__main__":
    _main()

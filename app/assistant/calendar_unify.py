"""calendar_unify.py — pure event-set functions (M18, §6.5).

No I/O, no AppKit, no clock of its own (the caller passes `now`) — so every rule
here is trivially unit-testable. Events are the dicts produced by calendar_ics
(aware `datetime` start/end). The monitor composes these:
parse → merge_dedup → in_window → snapshot, then imminent()/conflict_pairs() per
tick.
"""


def normalize(events):
    """Drop events missing a start/end; sort by start. (calendar_ics already
    shapes events; this is the defensive single entry point.)"""
    good = [e for e in events
            if e.get("start") is not None and e.get("end") is not None]
    return sorted(good, key=lambda e: e["start"])


def merge_dedup(events):
    """Collapse duplicates across sources: by UID first, else (summary, start).
    Keeps the first occurrence (input order)."""
    seen, out = set(), []
    for e in normalize(events):
        key = e.get("uid") or f"{e.get('summary')}|{e['start'].isoformat()}"
        # disambiguate recurring instances: same UID, different start = distinct
        key = f"{key}|{e['start'].isoformat()}"
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def in_window(events, now, days):
    """Events that intersect [now, now + days]."""
    from datetime import timedelta
    end = now + timedelta(days=days)
    return [e for e in normalize(events)
            if e["end"] >= now and e["start"] <= end]


def imminent(events, now, lead_min):
    """Timed events starting within (now, now + lead_min] — the "N분 후" set.
    All-day events have no specific time and never trigger imminent."""
    from datetime import timedelta
    horizon = now + timedelta(minutes=lead_min)
    return [e for e in normalize(events)
            if not e.get("all_day") and now < e["start"] <= horizon]


def conflict_pairs(events):
    """Pairs of distinct TIMED events whose intervals overlap (double-booking),
    after dedup. Returns (a, b) with a.start <= b.start; each unordered pair once."""
    timed = [e for e in merge_dedup(events) if not e.get("all_day")]
    timed.sort(key=lambda e: e["start"])
    pairs = []
    for i, a in enumerate(timed):
        for b in timed[i + 1:]:
            if b["start"] >= a["end"]:
                break                       # sorted: no later event can overlap
            if a.get("uid") != b.get("uid"):
                pairs.append((a, b))
    return pairs


def event_key(kind, *events):
    """Stable dedup/idempotency key for an alert (once-per-event). Sorted by uid
    so a conflict pair yields the same key regardless of argument order."""
    parts = sorted(f"{e.get('uid')}@{e['start'].isoformat()}" for e in events)
    return f"{kind}:" + "|".join(parts)

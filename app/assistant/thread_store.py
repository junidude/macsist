"""ThreadStore — work-thread state, the "어디까지 했더라" layer (M14, §4.1).

A thread is the assistant's mental model of one parallel work item: a title,
status, a carried `where_was_i` / `next_action` summary, links, and an activity
log. Threads reference kanban tasks by id (never copy them). Persisted as an
OpLogStore folded by id; touch() appends only the changed fields.

Main-thread-only (history_store convention).
"""

import uuid
from datetime import datetime, timezone

from assistant.oplog import OpLogStore
from config import CONFIG_DIR

THREADS_PATH = CONFIG_DIR / "threads.jsonl"
SCHEMA = "macsist.thread/v1"

ACTIVE = "active"
PAUSED = "paused"
BLOCKED = "blocked"
DONE = "done"


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ThreadStore:
    def __init__(self, config, path=None):
        self.config = config
        self.log = OpLogStore(
            path or THREADS_PATH,
            max_lines=int(config.get("assistant_thread_log_max")),
        )

    @property
    def on_changed(self):
        return self.log.on_changed

    @on_changed.setter
    def on_changed(self, cb):
        self.log.on_changed = cb

    # -- create / mutate -----------------------------------------------------

    def create(self, title, *, source="manual", status=ACTIVE, priority=0,
               where_was_i="", next_action="", links=None, tags=None,
               due_ts=None, kanban_task_ids=None):
        tid = "thr_" + uuid.uuid4().hex[:12]
        now = _now_iso()
        record = {
            "id": tid,
            "schema": SCHEMA,
            "ts": now,
            "title": title,
            "status": status,
            "priority": int(priority),
            "created_ts": now,
            "last_touched_ts": now,
            "due_ts": due_ts,
            "snoozed_until": None,
            "where_was_i": where_was_i,
            "next_action": next_action,
            "links": list(links or []),
            "tags": list(tags or []),
            "source": source,
            "kanban_task_ids": list(kanban_task_ids or []),
            "activity": [],
        }
        self.log.set(record)
        print(f"thread created {tid} title={title!r} source={source}",
              flush=True)
        return record

    def touch(self, tid, *, bump=True, **fields):
        """Merge `fields` into the thread; bump last_touched_ts unless bump=False
        (so a staleness-driven summary refresh doesn't reset the idle clock)."""
        if not self.log.get(tid):
            return None
        patch = {"id": tid, **fields}
        if bump:
            patch["last_touched_ts"] = _now_iso()
        self.log.set(patch)
        return self.log.get(tid)

    def add_activity(self, tid, kind, note):
        thread = self.log.get(tid)
        if not thread:
            return None
        activity = list(thread.get("activity") or [])
        activity.append({"ts": _now_iso(), "kind": kind, "note": note})
        return self.touch(tid, activity=activity)

    def remove(self, tid):
        self.log.tombstone(tid)

    # -- reads ---------------------------------------------------------------

    def get(self, tid):
        return self.log.get(tid)

    def all(self):
        rows = self.log.records()
        rows.sort(key=lambda r: r.get("last_touched_ts") or r.get("ts") or "",
                  reverse=True)
        return rows

    def active(self):
        return [t for t in self.all() if t.get("status") == ACTIVE]

    def for_display(self, done_limit=8):
        """Active threads + the most-recent done ones, so completed actions
        (e.g. a sent mail reply, M17) stay visible in the 비서 window without
        being stale-nudge targets (the engine only scans active()). all() is
        already sorted by recency."""
        active, done = [], []
        for t in self.all():
            status = t.get("status")
            if status == ACTIVE:
                active.append(t)
            elif status == DONE and len(done) < done_limit:
                done.append(t)
        return active + done

    @staticmethod
    def idle_hours(thread):
        """Hours since last_touched_ts (used by the staleness signal)."""
        stamp = thread.get("last_touched_ts") or thread.get("ts")
        if not stamp:
            return 0.0
        try:
            then = datetime.fromisoformat(stamp)
        except ValueError:
            return 0.0
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - then).total_seconds() / 3600.0

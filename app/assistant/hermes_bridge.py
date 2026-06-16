"""HermesBridge — the ONLY contact surface with Hermes (M13).

Reads the kanban board (tasks + task_events) read-only, with a `hermes kanban
list --json` fallback when the WAL-mode SQLite open fails (Hermes mid-write).
NEVER writes the DB directly — the board's atomic claim/lock invariants belong
to Hermes; writes (M16+) go through the `hermes kanban` CLI.

The kanban DB is WAL-mode (verified: kanban.db-wal/-shm present). A `mode=ro`
URI open reads committed rows while the -shm exists; on any sqlite error we
fall back to the CLI, then to an empty list, so the cockpit degrades
gracefully when Hermes isn't installed at all.

Threading: plain sqlite + subprocess, no AppKit — safe from a worker thread.
Callers marshal results to the main thread.
"""

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from shutil import which

# tasks columns we surface in the cockpit (subset of the full schema)
_TASK_COLUMNS = (
    "id", "title", "body", "assignee", "status", "priority", "tenant",
    "created_at", "started_at", "completed_at", "result",
    "idempotency_key", "workspace_kind", "branch_name",
)
_TERMINAL_STATUS = {"done", "completed", "complete", "archived",
                    "cancelled", "canceled", "closed"}
# hidden from the cockpit board view entirely (done/completed still show as
# recent results; archived/cancelled are off the board)
_HIDDEN_STATUS = {"archived", "cancelled", "canceled"}


class HermesBridge:
    def __init__(self, config):
        self.config = config

    # -- paths ---------------------------------------------------------------

    def _db_path(self):
        return Path(os.path.expanduser(
            str(self.config.get("assistant_kanban_db_path"))))

    def _hermes_bin(self):
        return os.path.expanduser(str(self.config.get("hermes_bin")))

    def available(self):
        """True if Hermes is readable (db file or hermes CLI present)."""
        return self._db_path().exists() or _resolvable(self._hermes_bin())

    def backend(self):
        """The resolved agent backend: 'hermes' or 'local'. 'auto' picks Hermes
        only when it's actually present, so a machine without Hermes is a clean
        local-only assistant (no kanban section, no Hermes references)."""
        choice = str(self.config.get("assistant_backend") or "auto").lower()
        if choice == "auto":
            return "hermes" if self.available() else "local"
        return choice if choice in ("local", "hermes") else "local"

    def is_active(self):
        """An external board is connected (currently only Hermes)."""
        return self.backend() == "hermes"

    # -- reads ---------------------------------------------------------------

    def list_tasks(self, tenant=None, limit=200):
        """All kanban tasks, newest first. RO sqlite → CLI fallback → []. Empty
        when the backend is local (no external agent)."""
        if self.backend() != "hermes":
            return []
        if tenant is None:
            tenant = str(self.config.get("assistant_kanban_tenant")) or None
        try:
            return self._list_tasks_sqlite(tenant, limit)
        except sqlite3.Error as exc:
            print(f"hermes_bridge: sqlite read failed ({exc}); CLI fallback",
                  flush=True)
        tasks = self._list_tasks_cli()
        if tenant:
            tasks = [t for t in tasks if t.get("tenant") == tenant]
        return tasks[:limit]

    def status(self):
        """Connection status for the 비서 tab header: which backend, connected?,
        gateway (Hermes only — Telegram/cron, M15+), task count."""
        backend = self.backend()
        if backend != "hermes":
            return {"backend": "local", "connected": False,
                    "gateway": "n/a", "board_count": 0}
        gateway = "unknown"
        gs = Path(os.path.expanduser("~/.hermes/gateway_state.json"))
        try:
            if gs.exists():
                gateway = str(json.loads(gs.read_text(encoding="utf-8"))
                              .get("gateway_state", "unknown"))
        except (OSError, ValueError):
            pass
        return {
            "backend": "hermes",
            "connected": True,
            "gateway": gateway,
            "board_count": len(self.board_tasks()),
        }

    def board_tasks(self, tenant=None, limit=200):
        """Tasks for the cockpit view — everything except archived/cancelled."""
        return [
            t for t in self.list_tasks(tenant, limit)
            if str(t.get("status", "")).lower() not in _HIDDEN_STATUS
        ]

    def open_task_count(self, tenant=None):
        """Tasks not in a terminal status — the menu-bar badge count (M13)."""
        return sum(
            1 for t in self.list_tasks(tenant)
            if str(t.get("status", "")).lower() not in _TERMINAL_STATUS
        )

    def events_since(self, last_id):
        """task_events with id > last_id (oldest first). Returns (events, max_id);
        max_id == last_id on empty/failure so the cursor never moves backward."""
        db = self._db_path()
        if not db.exists():
            return [], last_id
        try:
            rows = self._query(
                db,
                "SELECT id, task_id, kind, created_at FROM task_events "
                "WHERE id > ? ORDER BY id",
                (int(last_id),),
            )
        except sqlite3.Error as exc:
            print(f"hermes_bridge: events_since failed ({exc})", flush=True)
            return [], last_id
        events = [dict(r) for r in rows]
        return events, (events[-1]["id"] if events else last_id)

    def max_event_id(self):
        """Current max task_events.id — the cursor seed at startup. 0 if n/a."""
        db = self._db_path()
        if not db.exists():
            return 0
        try:
            rows = self._query(db, "SELECT COALESCE(MAX(id), 0) AS m FROM task_events")
            return int(rows[0]["m"]) if rows else 0
        except sqlite3.Error:
            return 0

    # -- internals -----------------------------------------------------------

    def _list_tasks_sqlite(self, tenant, limit):
        db = self._db_path()
        if not db.exists():
            return []
        cols = ", ".join(_TASK_COLUMNS)
        sql = f"SELECT {cols} FROM tasks"
        params = ()
        if tenant:
            sql += " WHERE tenant = ?"
            params = (tenant,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = self._query(db, sql, params + (int(limit),))
        return [dict(r) for r in rows]

    def _list_tasks_cli(self):
        bin_ = self._hermes_bin()
        if not _resolvable(bin_):
            return []
        try:
            out = subprocess.run(
                [bin_, "kanban", "list", "--json"],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            print(f"hermes_bridge: CLI fallback failed ({exc})", flush=True)
            return []
        if out.returncode != 0:
            print(f"hermes_bridge: hermes kanban list rc={out.returncode}",
                  flush=True)
            return []
        try:
            data = json.loads(out.stdout or "[]")
        except ValueError:
            return []
        if isinstance(data, dict):  # tolerate {"tasks": [...]}
            data = data.get("tasks", [])
        return [t for t in data if isinstance(t, dict)]

    @staticmethod
    def _query(db, sql, params=()):
        """Run a read-only query and return all rows (sqlite3.Row). WAL-aware:
        mode=ro never creates files and the -shm exists while Hermes is up.
        The connection is always closed (a `with` block would leak it)."""
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2.0)
        try:
            conn.row_factory = sqlite3.Row
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()


def _resolvable(path):
    if not path:
        return False
    if os.sep in path:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    return which(path) is not None

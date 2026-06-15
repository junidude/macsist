"""OpLogStore — append-only JSONL folded to latest-state-per-id (M14).

The shared persistence pattern for ThreadStore and ProposalStore. Each line is
an op on a record `id`: op="set" merges its fields into the record (partial
touches are fine), op="tombstone" deletes it. load() folds the log to the
current state; the file is compacted (atomic temp + os.replace, HistoryStore
convention) once it grows past max_lines.

Threading: guarded by an RLock so the proactive worker (scan) and the main
thread (approve/skip from the panel/IPC) can both mutate safely. UI-touching
callbacks (on_changed) must still be marshalled to the main thread by the owner.
"""

import json
import os
import threading


class OpLogStore:
    def __init__(self, path, max_lines=5000):
        self.path = path
        self.max_lines = int(max_lines)
        self.on_changed = None  # UI refresh hook (called after every mutation)
        self._lock = threading.RLock()
        self._lines = self._count_lines()

    # -- writes --------------------------------------------------------------

    def set(self, record):
        """Append a 'set' op. `record` must carry an 'id'; only the given
        fields are merged on load (so partial updates work)."""
        if not record.get("id"):
            raise ValueError("OpLogStore.set requires an 'id'")
        self._append({**record, "op": "set"})

    def tombstone(self, rid):
        self._append({"id": rid, "op": "tombstone"})

    def _append(self, rec):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._lines += 1
            if self._lines > self.max_lines:
                self._compact()
        if self.on_changed is not None:
            self.on_changed()

    # -- reads ---------------------------------------------------------------

    def folded(self):
        """{id: record} with ops applied in order; tombstones removed. The
        synthetic 'op' key is stripped from the returned records."""
        state = {}
        with self._lock:
            raw = list(self._raw())
        for rec in raw:
            rid = rec.get("id")
            if not rid:
                continue
            if rec.get("op") == "tombstone":
                state.pop(rid, None)
            else:
                merged = state.setdefault(rid, {})
                merged.update(rec)
                merged.pop("op", None)
        return state

    def records(self):
        """Folded records as a list (insertion order of first appearance)."""
        return list(self.folded().values())

    def get(self, rid):
        return self.folded().get(rid)

    # -- internals -----------------------------------------------------------

    def _raw(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict):
                        yield rec
        except OSError:
            return

    def _count_lines(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except OSError:
            return 0

    def _compact(self):
        """Rewrite the log to one 'set' per surviving record (atomic)."""
        survivors = self.folded()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for rec in survivors.values():
                f.write(json.dumps({**rec, "op": "set"},
                                   ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)
        self._lines = len(survivors)
        print(f"oplog compacted {self.path.name} -> {self._lines}", flush=True)

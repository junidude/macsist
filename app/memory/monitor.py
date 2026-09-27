"""MemoryMonitor — the daemon that turns the queue into notes (M20).

Another clone of `health.ServerHealthMonitor`: one daemon thread, a
`threading.Event` sleep with `poke()`, and never an AppKit call (the owner
wraps `on_changed` in `AppHelper.callAfter`). It wakes every
`memory_tick_interval`, drains `memory/pending.jsonl` in batches through
MemoryDistiller, and rewrites `profile.md` every `memory_profile_every`
readings.

`backfill()` is the same drain seeded from the existing `history.jsonl` — the
173 readings already on disk become the first memory, which is the whole point
of keeping that cache until now. It runs on its own thread (the CLI/app asks
for it), reports progress through `on_progress`, and is resumable: the cursor
in `memory/state.json` advances per batch, so a crash or a quit mid-backfill
picks up where it stopped instead of starting over.

The queue cursor only advances when a batch actually produced notes, so a
server that is down or loading costs nothing but a retry on the next tick.
"""

import threading
import time

from memory.distiller import MemoryDistiller


class MemoryMonitor:
    def __init__(self, config, store, on_changed=None):
        self.config = config
        self.store = store
        self.distiller = MemoryDistiller(config, store)
        self.on_changed = on_changed   # worker thread — owner marshals to main
        self.on_progress = None        # (done, total) during a backfill
        self._wake = threading.Event()
        self._thread = None
        self._busy = threading.Lock()  # one distiller at a time (tick/backfill)
        self._backfilling = False

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        if not bool(self.config.get("memory_enabled")):
            print("memory monitor: disabled (memory_enabled=False)", flush=True)
            return
        self._thread = threading.Thread(
            target=self._loop, name="memory-distill", daemon=True
        )
        self._thread.start()
        print(f"memory monitor started ({self.store.pending_count()} queued)",
              flush=True)

    def poke(self):
        """Drain now (`macsist memory distill`, or right after an explain)."""
        self._wake.set()

    def _loop(self):
        while True:
            self._wake.wait(
                timeout=float(self.config.get("memory_tick_interval"))
            )
            self._wake.clear()
            if not bool(self.config.get("memory_enabled")):
                continue
            try:
                self.drain()
            except Exception as exc:   # never let the daemon thread die
                print(f"memory monitor: drain error {exc!r}", flush=True)

    # -- draining ------------------------------------------------------------

    def drain(self, max_batches=None):
        """Distill queued readings until the queue is empty, the batch budget is
        spent, or a batch fails (then leave the rest for the next tick).
        Returns the number of readings consumed."""
        if self._backfilling and max_batches is None:
            return 0   # a backfill is already working the same queue
        batch = int(self.config.get("memory_batch_size"))
        budget = (int(self.config.get("memory_max_batches_per_tick"))
                  if max_batches is None else int(max_batches))
        done = 0
        with self._busy:
            for _ in range(max(budget, 0)):
                items = self.store.pending(limit=batch)
                if not items:
                    break
                consumed = self.distiller.distill(items)
                if consumed <= 0:
                    break
                self.store.mark_drained(consumed)
                done += consumed
                self._maybe_profile()
                self._notify()
        return done

    def _maybe_profile(self):
        every = int(self.config.get("memory_profile_every"))
        if every <= 0:
            return
        state = self.store.state()
        distilled = int(state.get("distilled") or 0)
        last = int(state.get("profile_at") or 0)
        if distilled - last < every:
            return
        if self.distiller.profile():
            state = self.store.state()
            state["profile_at"] = distilled
            self.store.save_state(state)

    # -- backfill from the history cache -------------------------------------

    def backfill_async(self, records):
        """Seed the queue from history records and drain it on a worker thread
        (the caller is the main thread / a notification handler)."""
        if self._backfilling:
            print("memory: backfill already running", flush=True)
            return False
        thread = threading.Thread(
            target=self._backfill, args=(records,),
            name="memory-backfill", daemon=True,
        )
        thread.start()
        return True

    def seed(self, records):
        """Append history records to the queue, skipping ones already seeded
        (same ts+mode+input) so a second backfill is a no-op rather than a
        duplicate pass. Returns how many were added."""
        existing = {
            (str(r.get("ts")), str(r.get("mode")), str(r.get("input"))[:80])
            for r in self._all_queued()
        }
        added = 0
        for record in records:
            key = (str(record.get("ts")), str(record.get("mode")),
                   str(record.get("input"))[:80])
            if key in existing:
                continue
            existing.add(key)
            self.store.enqueue(
                record.get("mode"), record.get("input"),
                record.get("response"), ts=record.get("ts"),
            )
            added += 1
        print(f"memory: seeded {added}/{len(records)} history record(s)",
              flush=True)
        return added

    def _all_queued(self):
        """Every queue line ever written, drained or not — the dedupe key set
        for seed(). Reads the raw file (store.pending() hides drained lines)."""
        import json
        rows = []
        try:
            with open(self.store.pending_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict):
                        rows.append(record)
        except OSError:
            return []
        return rows

    def _backfill(self, records):
        from memory.store import _now_iso
        self._backfilling = True
        try:
            self.seed(records)
            total = self.store.pending_count()
            done, failures = 0, 0
            retries = int(self.config.get("memory_backfill_retries"))
            print(f"memory: backfill start — {total} reading(s) queued",
                  flush=True)
            while self.store.pending_count():
                consumed = self.drain(max_batches=1)
                if consumed > 0:
                    done += consumed
                    failures = 0
                    if self.on_progress is not None:
                        self.on_progress(done, total)
                    print(f"memory: backfill {done}/{total}", flush=True)
                    continue
                # A batch can fail transiently (server loading, a truncated
                # reply). One failure must not end a 40-minute job — retry a
                # few times, then stop and SAY the queue is not empty.
                failures += 1
                if failures > retries:
                    break
                print(f"memory: backfill batch failed "
                      f"({failures}/{retries}) — retrying", flush=True)
                time.sleep(float(self.config.get("memory_backfill_retry_sleep")))
            self.distiller.profile()
            state = self.store.state()
            left = self.store.pending_count()
            if not left:
                state["backfill_done_ts"] = _now_iso()
            state["profile_at"] = int(state.get("distilled") or 0)
            self.store.save_state(state)
            if left:
                print(f"memory: backfill STOPPED — {done} distilled, {left} "
                      f"left (다시 `macsist memory backfill` 하면 이어서 갑니다), "
                      f"{len(self.store.notes())} note(s)", flush=True)
            else:
                print(f"memory: backfill finished — {done} distilled, "
                      f"{len(self.store.notes())} note(s)", flush=True)
        except Exception as exc:
            print(f"memory: backfill error {exc!r}", flush=True)
        finally:
            self._backfilling = False
            self._notify()

    def _notify(self):
        if self.on_changed is not None:
            self.on_changed()

"""HistoryStore — append-only JSONL history of completed explains (M7).

One record per completed request (text/region/followup), written from
ExplainController._commitSession. Region records save the capture PNG to
`history_images/<uuid>.png` next to the JSONL (when `history_save_images` is
on) so 다시 질문 can re-send it; the JSONL itself never holds base64. Pruning
rewrites the file atomically (temp + os.replace) keeping the newest
`history_max_items`, and deletes image files no surviving record references.

Saving is gated per mode: `history_enabled` is the master switch,
`history_save_text` covers text/followup records, `history_save_images`
covers region records (record + PNG together).

Threading: main-thread-only by design. Appends come from _commitSession
(marshalled via AppHelper.callAfter), reads from the History window — both on
the main thread, so no lock is needed. Do not call from worker threads.
"""

import json
import os
import uuid
from datetime import datetime

from config import CONFIG_DIR

HISTORY_PATH = CONFIG_DIR / "history.jsonl"


class HistoryStore:
    def __init__(self, config, path=None):
        self.config = config
        self.path = path or HISTORY_PATH
        self.images_dir = self.path.parent / "history_images"
        self.on_appended = None  # History window: refresh while visible
        self._count = self._countLines()

    def _countLines(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except OSError:
            return 0

    def append(self, mode, model, input_text, response, detail,
               image_png=None):
        if not self.config.get("history_enabled"):
            return
        if mode == "region":
            if not self.config.get("history_save_images"):
                return
        elif not self.config.get("history_save_text"):
            return
        snippet_chars = int(self.config.get("history_snippet_chars"))
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "mode": mode,
            "model": model,
            "input": str(input_text)[:snippet_chars],
            "response": response,
            "detail": detail,
        }
        if image_png and mode == "region":
            name = uuid.uuid4().hex + ".png"
            self.images_dir.mkdir(parents=True, exist_ok=True)
            (self.images_dir / name).write_bytes(image_png)
            record["image"] = name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._count += 1
        max_items = int(self.config.get("history_max_items"))
        if self._count > max_items:
            self._prune(max_items)
        if self.on_appended is not None:
            self.on_appended()

    def _prune(self, max_items):
        records = self.load()  # newest first, bad lines already dropped
        keep = list(reversed(records[:max_items]))  # back to oldest-first
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for record in keep:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)
        self._count = len(keep)
        referenced = {r["image"] for r in keep if r.get("image")}
        try:
            for file in self.images_dir.glob("*.png"):
                if file.name not in referenced:
                    file.unlink()
        except OSError:
            pass
        print(f"history pruned to {self._count} records", flush=True)

    def image_path(self, record):
        """Path of the record's saved capture, or None (no image / deleted)."""
        name = record.get("image")
        if not name:
            return None
        path = self.images_dir / name
        return path if path.exists() else None

    def load(self):
        """All records, newest first. Corrupt lines are skipped, never fatal."""
        records = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict):
                        records.append(record)
        except OSError:
            return []
        records.reverse()
        return records

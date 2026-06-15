"""AuditStore — append-only audit trail + the structural approval gate (M14).

Every proposal status transition is logged here and NEVER pruned. The gate:
`assert_approved(proposal_id)` raises NotApproved unless a row exists with
to_status in {approved, edited} AND by in {user, auto_policy}. Every side-effect
executor MUST call it before acting — this is the single structural bottleneck
that makes "nothing irreversible runs without an explicit approval record"
true by construction, independent of UI state or model output.

Threading: guarded by an RLock (the proactive worker and the main thread both
record/read here). Append-only + line-at-a-time JSON keeps reads consistent.
"""

import json
import threading
from datetime import datetime

from config import CONFIG_DIR

AUDIT_PATH = CONFIG_DIR / "assistant_audit.jsonl"

_APPROVED_STATUSES = {"approved", "edited"}
_APPROVING_ACTORS = {"user", "auto_policy"}


class NotApproved(Exception):
    """Raised by assert_approved when no valid approval row exists."""


class AuditStore:
    def __init__(self, config, path=None):
        self.config = config
        self.path = path or AUDIT_PATH
        self._lock = threading.RLock()

    def record(self, proposal_id, from_status, to_status, by, gesture,
               note=None):
        """Append one transition. Never pruned."""
        row = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "proposal_id": proposal_id,
            "from_status": from_status,
            "to_status": to_status,
            "by": by,
            "gesture": gesture,
            "note": note,
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"audit: {proposal_id} {from_status}->{to_status} "
              f"by={by} gesture={gesture}", flush=True)
        return row

    def assert_approved(self, proposal_id):
        """Raise NotApproved unless a user/auto_policy approval row exists for
        this proposal. The ONLY sanctioned precondition for any side effect."""
        for row in self._rows():
            if (row.get("proposal_id") == proposal_id
                    and row.get("to_status") in _APPROVED_STATUSES
                    and row.get("by") in _APPROVING_ACTORS):
                return
        raise NotApproved(
            f"{proposal_id}: no user/auto_policy approval row — refusing to act")

    def is_approved(self, proposal_id):
        try:
            self.assert_approved(proposal_id)
            return True
        except NotApproved:
            return False

    def rows_for(self, proposal_id):
        return [r for r in self._rows() if r.get("proposal_id") == proposal_id]

    def _rows(self):
        with self._lock:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                return []
        out = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

"""ProposalStore — the propose/approve envelope log (M14, ASSISTANT.md §4.2).

An OpLogStore of proposals folded by id. A proposal is the unit the user
confirms: {kind, risk, title, rationale, payload, status, ...}. `risk` is set
by the engine from risk.py (never the model). Dedup is by idempotency_key among
non-terminal proposals, so the same nudge isn't re-surfaced every cycle.

Status: pending -> approved|edited -> executed | failed ; or skipped | snoozed.
Approval rows live in the AuditStore (the gate); this store holds the proposal
body + its current status for the inbox/panel.
"""

import uuid
from datetime import datetime

from assistant.oplog import OpLogStore
from config import CONFIG_DIR

PROPOSALS_PATH = CONFIG_DIR / "assistant_proposals.jsonl"

SCHEMA = "macsist.proposal/v1"
TERMINAL = {"executed", "skipped", "failed"}
ACTIVE = {"pending", "approved", "edited"}  # snoozed re-surfaces, handled apart


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def payload_args(prop):
    """The proposal's payload.args dict (always a dict). Single source for the
    `(prop.get("payload") or {}).get("args") or {}` idiom used across the engine
    and controller."""
    return ((prop or {}).get("payload") or {}).get("args") or {}


class ProposalStore:
    def __init__(self, config, path=None):
        self.config = config
        self.log = OpLogStore(
            path or PROPOSALS_PATH,
            max_lines=int(config.get("assistant_proposal_max")) * 8,
        )

    @property
    def on_changed(self):
        return self.log.on_changed

    @on_changed.setter
    def on_changed(self, cb):
        self.log.on_changed = cb

    # -- create --------------------------------------------------------------

    def create(self, kind, risk, title, rationale, *, source="manual",
               source_ref=None, thread_id=None, payload=None,
               idempotency_key=None):
        pid = "prop_" + uuid.uuid4().hex[:12]
        record = {
            "id": pid,
            "schema": SCHEMA,
            "ts": _now(),
            "source": source,
            "source_ref": source_ref,
            "thread_id": thread_id,
            "kind": kind,
            "risk": risk,                 # set by the engine from risk.py
            "title": title,
            "rationale": rationale,
            "payload": payload or {},
            "idempotency_key": idempotency_key,
            "status": "pending",
            "approval": None,             # filled from a user gesture only
            "snoozed_until": None,
            "decided_ts": None,
            "result_ref": None,
            "error": None,
        }
        self.log.set(record)
        print(f"proposal created {pid} kind={kind} risk={risk} "
              f"status=pending", flush=True)
        return record

    # -- reads ---------------------------------------------------------------

    def get(self, pid):
        return self.log.get(pid)

    def all(self):
        rows = self.log.records()
        rows.sort(key=lambda r: r.get("ts") or "", reverse=True)
        return rows

    def pending(self):
        return [r for r in self.all() if r.get("status") == "pending"]

    def inbox(self):
        """What the user should see: pending + already-approved-not-yet-run."""
        return [r for r in self.all() if r.get("status") in ACTIVE]

    def find_active_by_idempotency(self, key):
        if not key:
            return None
        for r in self.all():
            if (r.get("idempotency_key") == key
                    and r.get("status") not in TERMINAL):
                return r
        return None

    # -- transitions ---------------------------------------------------------

    def update(self, pid, **fields):
        if not self.log.get(pid):
            return None
        self.log.set({"id": pid, **fields})
        return self.log.get(pid)

    def mark_decided(self, pid, status, **fields):
        return self.update(pid, status=status, decided_ts=_now(), **fields)

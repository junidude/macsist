"""risk.py — the action-safety spine (M14, docs/ASSISTANT.md §4.8).

The risk class of a proposal is decided HERE, deterministically, from its
`kind` — NEVER from anything the model emits. An unknown kind is `never_auto`
(fail safe), so a hallucinated kind can never widen its own privileges.

Classes:
  auto       reversible / internal — may auto-run when the trust dial allows it
             AND the kind is whitelisted (assistant_auto_safe_kinds).
  confirm    consumes resources or touches the outside world but is recoverable
             (a draft, a remote dispatch, a calendar event) — always a panel.
  never_auto irreversible — sending mail, deleting events, moving money. NO
             config value and NO model output can make these auto-run; only an
             explicit user gesture (recorded in the audit log) executes them.
"""

AUTO = "auto"
CONFIRM = "confirm"
NEVER_AUTO = "never_auto"

# kind -> risk. Hardcoded on purpose; extend deliberately as executors land.
RISK = {
    # auto (reversible / internal)
    "thread_resume_nudge": AUTO,
    "thread_summary_refresh": AUTO,
    "todo_add": AUTO,
    "label_suggestion": AUTO,
    "calendar_alert": AUTO,
    # confirm (recoverable external/resource)
    "reply_draft": CONFIRM,
    "remote_dispatch": CONFIRM,
    "calendar_write": CONFIRM,
    # never_auto (irreversible)
    "send_reply": NEVER_AUTO,
    "calendar_delete": NEVER_AUTO,
    "send_money": NEVER_AUTO,
}


def risk_of(kind):
    """The risk class for a proposal kind. Unknown -> never_auto (fail safe)."""
    return RISK.get(str(kind), NEVER_AUTO)


def known_kind(kind):
    return str(kind) in RISK

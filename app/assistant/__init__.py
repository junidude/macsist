"""Macsist Assistant subsystem (M13+).

The proactive "secretary" layer: a read-only cockpit over the Hermes kanban
board (M13), and — from M14 — work-thread state ("어디까지 했더라"), a
propose-then-confirm engine, and a structural action-safety gate. Full design:
docs/ASSISTANT.md.

Hard boundaries (see CLAUDE.md / SPEC §7):
- Brain = Macsist M9 LLMClient. Hermes is contacted ONLY through hermes_bridge
  (read-only kanban.db + `hermes` CLI); the DB is never written directly.
- All AppKit work on the main thread; pollers clone the health.py daemon and
  marshal via AppHelper.callAfter.
"""

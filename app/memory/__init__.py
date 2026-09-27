"""Macsist memory subsystem (M20) — what the user reads, remembered.

    store.py      MemoryStore — notes/*.md + derived index + ingestion queue,
                  and the LLM-free retrieval that runs in the hotkey path
    recall.py     recall_block() — the system-prompt suffix for one capture
    distiller.py  MemoryDistiller — readings → concepts (local Qwen, JSON)
    monitor.py    MemoryMonitor — the daemon that drains the queue + backfill
    tab.py        MemoryTabController — the 기억 tab in the main window

Design: everything except tab.py is AppKit-free, so `cli/configure.py` can
import the store from any python3 the way it already imports config.py.

This file stays import-free ON PURPOSE: `from memory.store import MemoryStore`
must not drag in distiller.py -> llm_client -> httpx, or the stdlib-only CLI
helper loses the ability to read memory under a bare /usr/bin/python3.
"""

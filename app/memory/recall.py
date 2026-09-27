"""Hot-path prompt assembly for memory (M20).

Called from ExplainController right before streaming: turn the notes that the
selected text is about into a short system-prompt block. No LLM, no network —
`MemoryStore.recall` is IDF term overlap over an in-memory index, so this costs
microseconds and the panel opens exactly as fast as it did before M20.

The block is advisory on purpose: the preamble tells the model to weave in ONE
line when a note is genuinely related and to ignore the block otherwise. A
false positive from lexical retrieval must never become a wrong claim in the
explanation, so nothing here asserts that the notes ARE relevant.
"""

from memory.store import MemoryStore  # noqa: F401  (re-export convenience)


def _line(config, note):
    template = str(config.get("memory_recall_line"))
    seen = int(note.get("seen") or 1)
    when = str(note.get("last_ts") or "")[:10]
    summary = " ".join(str(note.get("summary") or "").split())
    limit = int(config.get("memory_recall_summary_chars"))
    return (template
            .replace("<<TITLE>>", str(note.get("title") or ""))
            .replace("<<SEEN>>", str(seen))
            .replace("<<WHEN>>", when)
            .replace("<<SUMMARY>>", summary[:limit]))


def recall_block(store, config, text, notes=None):
    """The system-prompt suffix for this capture ('' when memory is off, empty,
    or nothing scored above the threshold). Pass `notes` to reuse a recall the
    caller already ran (the panel shows the same set)."""
    if store is None or not bool(config.get("memory_enabled")):
        return ""
    if not bool(config.get("memory_recall_enabled")):
        return ""
    parts = []
    if bool(config.get("memory_inject_profile")):
        domains = store.domains(int(config.get("memory_profile_domains")))
        if domains:
            parts.append(str(config.get("memory_recall_profile"))
                         .replace("<<DOMAINS>>", ", ".join(domains)))
    if notes is None:
        notes = store.recall(text) if str(text or "").strip() else []
    if notes:
        block = [str(config.get("memory_recall_preamble"))]
        block += [_line(config, note) for note in notes]
        parts.append("\n".join(block))
        # greppable in app.log: which notes were offered to the model, and how
        # strongly they scored (the verification hook for "does it tie back?")
        print("memory: recall " + ", ".join(
            f"{note.get('title')}({note.get('score')})" for note in notes),
            flush=True)
    if not parts:
        return ""
    suffix = "\n\n" + "\n\n".join(parts)
    budget = int(config.get("memory_recall_max_chars"))
    return suffix[:budget]

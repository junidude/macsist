"""llm_util — shared LLM helpers for the assistant (single source).

Both the ProactiveEngine and the Gmail triager need to (a) run one chat
completion and collect the text, and (b) pull a JSON value out of the reply.
Keeping one copy here avoids the near-duplicate stream loops / extractors that
used to live in proactive.py and gmail_triage.py.
"""

import json

from llm_client import LLMError, StreamHandle


def extract_json(text):
    """Pull the first JSON value (array OR object) out of an LLM reply, tolerating
    code fences / prose around it. Returns the parsed value, or None."""
    if not text:
        return None
    text = text.strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except ValueError:
                continue
    return None


def complete_text(client, config, system, user):
    """One completion → trimmed text ('' if the LLM is unavailable). The model is
    config.assistant_model ('' = the active explain provider). Worker-thread use
    only (the caller marshals UI back to main)."""
    model = str(config.get("assistant_model")) or None
    buf = []
    try:
        for chunk in client.stream_chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                StreamHandle(), model=model):
            buf.append(chunk)
    except LLMError as exc:
        print(f"llm_util: LLM unavailable ({exc})", flush=True)
        return ""
    return "".join(buf).strip()

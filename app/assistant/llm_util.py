"""llm_util — shared LLM helpers for the assistant (single source).

Both the ProactiveEngine and the Gmail triager need to (a) run one chat
completion and collect the text, and (b) pull a JSON value out of the reply.
Keeping one copy here avoids the near-duplicate stream loops / extractors that
used to live in proactive.py and gmail_triage.py.

`ForceLocalConfig` joined them in M20: Gmail triage and the memory distiller
both need to pin one subsystem to the local MLX server without mutating the
shared ConfigStore that every other request reads.
"""

import json

from llm_client import LLMError, StreamHandle


class ForceLocalConfig:
    """A config view that pins active_provider() to the first is_local provider,
    delegating everything else. Used to keep Gmail triage (M17) and the memory
    distiller (M20) on the local server — what the user reads and what they get
    mailed then never leaves the machine, whatever provider is active."""

    def __init__(self, config):
        self._config = config

    def active_provider(self):
        providers = [p for p in (self._config.get("providers") or [])
                     if isinstance(p, dict)]
        local = next((p for p in providers if p.get("is_local")), None)
        return dict(local) if local else self._config.active_provider()

    def __getattr__(self, name):
        return getattr(self._config, name)


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


def complete_text(client, config, system, user, model=None, max_tokens=None):
    """One completion → trimmed text ('' if the LLM is unavailable). The model
    defaults to config.assistant_model ('' = the active explain provider);
    callers with their own model/budget key (M20 memory) pass them in.
    Worker-thread use only (the caller marshals UI back to main)."""
    model = str(model or config.get("assistant_model")) or None
    buf = []
    try:
        for chunk in client.stream_chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                StreamHandle(), model=model, max_tokens=max_tokens):
            buf.append(chunk)
    except LLMError as exc:
        print(f"llm_util: LLM unavailable ({exc})", flush=True)
        return ""
    return "".join(buf).strip()

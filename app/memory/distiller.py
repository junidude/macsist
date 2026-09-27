"""MemoryDistiller — turn finished readings into notes, on the local LLM (M20).

The cold half of memory. For a batch of queued readings (each an explain the
user actually got: mode + selected text + the explanation that streamed back)
it asks the model for the CONCEPTS behind them as strict JSON, then folds each
one into `memory/notes/*.md` through MemoryStore.upsert — new note, or a merge
that bumps `seen` and appends the context line.

Three decisions worth knowing:

- **Local by default.** `memory_local_only` pins this to the first is_local
  provider (llm_util.ForceLocalConfig). The reading history is the most
  personal thing the app holds; it must not reach a remote provider because
  the user switched providers for explaining.
- **Fail quiet, never lose the item.** A missing server, a truncated reply or
  unparseable JSON returns 0 and the queue cursor does NOT advance, so the
  reading is retried on the next tick instead of vanishing.
- **Known slugs are handed to the model** so `links` point at notes that
  actually exist — that is what makes the memory a graph rather than a pile.
"""

from llm_client import LLMClient

from assistant.llm_util import ForceLocalConfig, complete_text, extract_json


def _clean_list(value, limit=12):
    if isinstance(value, str):
        value = [part for part in value.replace(";", ",").split(",")]
    out = []
    for item in (value or []):
        item = " ".join(str(item).split()).strip()
        if item and item.lower() not in {o.lower() for o in out}:
            out.append(item[:60])
    return out[:limit]


class MemoryDistiller:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self._llm = LLMClient(config)
        self._local_llm = LLMClient(ForceLocalConfig(config))

    # -- provider selection --------------------------------------------------

    def _client(self):
        """The LLM to distill with, or None when memory must stay local and no
        local provider is configured (then the queue simply waits)."""
        if not bool(self.config.get("memory_local_only")):
            return self._llm
        providers = [p for p in (self.config.get("providers") or [])
                     if isinstance(p, dict) and p.get("is_local")]
        if not providers:
            print("memory: no local provider — distillation held "
                  "(memory_local_only)", flush=True)
            return None
        return self._local_llm

    def _model(self):
        return str(self.config.get("memory_model")) or None

    # -- one batch -----------------------------------------------------------

    def distill(self, items):
        """items: queued readings (oldest first). Returns the number of items
        consumed — 0 means "retry later", never "drop these"."""
        items = [i for i in items if str(i.get("input") or "").strip()]
        if not items:
            return 0
        client = self._client()
        if client is None:
            return 0
        max_concepts = str(self.config.get("memory_max_concepts"))
        system = (str(self.config.get("memory_distill_system"))
                  .replace("<<MAX>>", max_concepts))
        user = (str(self.config.get("memory_distill_user"))
                .replace("<<ITEMS>>", self._digest(items))
                .replace("<<KNOWN>>", self._known())
                .replace("<<MAX>>", max_concepts))
        reply = complete_text(
            client, self.config, system, user,
            model=self._model(),
            max_tokens=int(self.config.get("memory_distill_max_tokens")),
        )
        if not reply:
            return 0
        concepts = self._parse(reply, len(items))
        if concepts is None:
            print(f"memory: distill reply unparseable ({reply[:120]!r})",
                  flush=True)
            return 0
        if not concepts:
            # A VALID empty array is a real answer: these readings held no
            # concept worth a note (follow-ups, one-off sentence translations).
            # Treating it as failure is how a batch becomes poison — the cursor
            # never advances and the same four readings block the queue forever
            # (observed live during the M20 backfill).
            print(f"memory: no concepts in {len(items)} reading(s) — skipped",
                  flush=True)
            return len(items)
        upserted = 0
        for index, concept in concepts:
            context = items[index] if 0 <= index < len(items) else items[-1]
            slug, _created = self.store.upsert(concept, {
                "ts": context.get("ts"),
                "mode": context.get("mode"),
                "snippet": context.get("input"),
            })
            if slug:
                upserted += 1
        print(f"memory: distilled {len(items)} reading(s) -> {upserted} note(s)",
              flush=True)
        return len(items)

    def _digest(self, items):
        """The batch as a numbered digest. The explanation is truncated hard:
        its opening (번역/약자 풀이/쉽게 말하면) already names the concept, and a
        long tail only costs prompt budget."""
        in_chars = int(self.config.get("memory_distill_input_chars"))
        out_chars = int(self.config.get("memory_distill_response_chars"))
        lines = []
        for index, item in enumerate(items):
            selected = " ".join(str(item.get("input") or "").split())
            explained = " ".join(str(item.get("response") or "").split())
            lines.append(
                f"[{index}] ({item.get('mode')}, {str(item.get('ts'))[:10]})\n"
                f"읽은 것: {selected[:in_chars]}\n"
                f"설명: {explained[:out_chars]}"
            )
        return "\n\n".join(lines)

    def _known(self):
        """Existing note slugs (+titles) the model may link to, newest first and
        capped so the prompt stays bounded as memory grows."""
        limit = int(self.config.get("memory_known_notes"))
        rows = self.store.notes()[:limit]
        if not rows:
            return "(none)"
        return "; ".join(f"{row['slug']}={row['title']}" for row in rows)

    def _parse(self, reply, item_count):
        """[(item_index, concept)], possibly EMPTY when the model correctly
        found nothing to file — or None when the reply carried no JSON at all.
        The two must stay distinguishable: empty means "consume", None means
        "retry". Tolerates both the documented array and a bare single object."""
        data = extract_json(reply)
        if isinstance(data, dict):
            data = data.get("concepts") if "concepts" in data else [data]
        if not isinstance(data, list):
            return None
        max_per_item = int(self.config.get("memory_max_concepts"))
        per_item, out = {}, []
        for raw in data:
            if not isinstance(raw, dict):
                continue
            title = " ".join(str(raw.get("title") or "").split()).strip()
            if not title or len(title) > 120:
                continue
            try:
                index = int(raw.get("item", 0))
            except (TypeError, ValueError):
                index = 0
            index = max(0, min(index, item_count - 1))
            if per_item.get(index, 0) >= max_per_item:
                continue
            per_item[index] = per_item.get(index, 0) + 1
            out.append((index, {
                "title": title[:120],
                "kind": str(raw.get("kind") or "concept")[:20],
                "aliases": _clean_list(raw.get("aliases"), 6),
                "domains": _clean_list(raw.get("domains"), 3),
                "terms": _clean_list(raw.get("terms"), 14),
                "links": _clean_list(raw.get("links"), 5),
                "summary": " ".join(str(raw.get("summary") or "").split())[
                    :int(self.config.get("memory_summary_chars"))],
            }))
        return out

    # -- 관심사 프로필 --------------------------------------------------------

    def profile(self):
        """Rewrite memory/profile.md from the current notes. Cheap enough to run
        after a backfill and every `memory_profile_every` distilled readings."""
        rows = self.store.notes()
        if not rows:
            return False
        client = self._client()
        if client is None:
            return False
        limit = int(self.config.get("memory_profile_notes"))
        digest = "\n".join(
            f"- {row['title']} ({', '.join(row.get('domains') or []) or '?'}) "
            f"×{row.get('seen', 1)}: {row.get('summary', '')[:100]}"
            for row in rows[:limit]
        )
        text = complete_text(
            client, self.config,
            str(self.config.get("memory_profile_system")),
            str(self.config.get("memory_profile_user"))
            .replace("<<NOTES>>", digest)
            .replace("<<COUNT>>", str(len(rows))),
            model=self._model(),
            max_tokens=int(self.config.get("memory_profile_max_tokens")),
        )
        if not text:
            return False
        self.store.save_profile(text)
        print(f"memory: profile rewritten from {len(rows)} note(s)", flush=True)
        return True

"""MemoryStore — the filesystem memory of what the user reads (M20).

One markdown note per concept under `…/Application Support/Macsist/memory/`:

    memory/
      notes/<slug>.md    one concept: frontmatter (title/aliases/terms/seen/
                         first_ts/last_ts/links) + summary + the contexts it
                         was seen in. Hand-editable — the notes are the source
                         of truth, `index.json` is a derived cache.
      index.json         {slug: {title, terms, seen, …, mtime}} for retrieval;
                         rebuilt per-note whenever a file's mtime moved, so an
                         edit in any text editor is picked up on next load.
      pending.jsonl      ingestion queue (append-only + cursor in state.json):
                         every finished explain lands here and the distiller
                         drains it. Survives restarts, so nothing read is lost
                         when the LLM is busy/offline or the provider is remote.
      state.json         {pending_cursor, distilled, backfill_done_ts, …}
      profile.md         the distilled 관심사 프로필 (what this reader reads).

Retrieval is pure Python and runs in the hotkey path — no LLM, no embeddings
(the local stack is vlm-only; `/v1/embeddings` does not exist). Scoring is
IDF-weighted term overlap over `terms`, with Korean handled by prefix
indexing: "강화학습을" contributes 강화/강화학/강화학습, so a particle-suffixed
query still hits the note. All the LLM work (what a note IS) happens off the
hot path in memory/distiller.py.

Threading: every public method is guarded by an RLock — the distiller thread
writes while the main thread recalls (hotkey) and the 기억 tab reads. No AppKit
here; UI refresh goes through `on_changed`, which the owner marshals to main.
"""

import json
import math
import os
import re
import threading
from datetime import datetime

from config import CONFIG_DIR

MEMORY_DIR = CONFIG_DIR / "memory"
SCHEMA = "macsist.memory/v1"

_ASCII_RE = re.compile(r"[a-z][a-z0-9+#.]*|[0-9]+[a-z]+")
_HANGUL_RE = re.compile(r"[가-힣]+")
_CJK_RE = re.compile(r"[぀-ヿ一-鿿]+")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")

# Terms this common carry no signal; IDF alone would still rank them near zero
# but dropping them keeps the index small and the debug output readable.
_STOP = {
    "the", "and", "for", "with", "that", "this", "are", "was", "from", "have",
    "has", "not", "but", "can", "will", "which", "their", "them", "then",
    "than", "these", "those", "its", "our", "you", "your", "all", "any", "one",
    "two", "may", "more", "most", "such", "into", "over", "each", "also",
    "been", "when", "what", "how", "why", "who", "use", "used", "using",
    "based", "via", "per", "non", "etc", "eg", "ie",
    "그리고", "하지만", "그러나", "그런", "이런", "저런", "있는", "없는",
    "하는", "되는", "이것", "그것", "때문", "위해", "통해", "대한", "대해",
    "수가", "것이", "것을", "합니다", "입니다",
}

_MAX_PREFIX_LEN = 8       # Korean prefix indexing cap (조사 handling)
_MAX_CONTEXTS = 8         # context lines kept per note (newest wins)
_PENDING_COMPACT_AT = 200  # drained lines tolerated before rewriting the queue


def _now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def terms_of(text):
    """Retrieval terms for a blob of text (query side and index side share this
    one function — asymmetric tokenizers are how lexical search silently stops
    matching). ASCII words are lowercased; Korean/CJK runs also contribute
    their prefixes so "강화학습을"/"강화학습의" both reach the term 강화학습."""
    out = set()
    lowered = str(text or "").lower()
    for word in _ASCII_RE.findall(lowered):
        word = word.strip(".")
        if len(word) >= 2 and word not in _STOP:
            out.add(word)
    for run in _HANGUL_RE.findall(lowered) + _CJK_RE.findall(lowered):
        if len(run) < 2 or run in _STOP:
            continue
        out.add(run)
        for end in range(2, min(len(run), _MAX_PREFIX_LEN)):
            prefix = run[:end]
            if prefix not in _STOP:
                out.add(prefix)
    return out


def slugify(title, fallback_seed=""):
    """ASCII-only slug — the note's filename. Hangul filenames round-trip
    through HFS/APFS normalization differently depending on who wrote them
    (NFD vs NFC), which turns "same note" into two files; the Korean stays in
    the `title` field instead."""
    base = _SLUG_STRIP_RE.sub("-", str(title or "").lower()).strip("-")
    base = base[:60].strip("-")
    if base:
        return base
    seed = str(fallback_seed or title or "note")
    digest = 0
    for ch in seed:
        digest = (digest * 131 + ord(ch)) & 0xFFFFFFFF
    return f"note-{digest:08x}"


def _fm_value(value):
    if isinstance(value, (list, tuple, set)):
        items = [str(v).replace(",", " ").replace("\n", " ").strip()
                 for v in value]
        return "[" + ", ".join(i for i in items if i) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("\n", " ").strip()


def _parse_fm_value(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [part.strip() for part in inner.split(",") if part.strip()]
    if raw.isdigit():
        return int(raw)
    return raw


def parse_note(text):
    """(meta, body) from a note's markdown. Tolerant on purpose: the user may
    hand-edit these files, and a broken note must degrade to "no metadata",
    never raise into the retrieval path."""
    meta, body = {}, str(text or "")
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end > 0:
            block = body[3:end]
            body = body[end + 4:].lstrip("\n")
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, _, raw = line.partition(":")
                meta[key.strip()] = _parse_fm_value(raw)
    return meta, body


def render_note(meta, body):
    keys = ("name", "title", "kind", "domains", "aliases", "terms", "seen",
            "first_ts", "last_ts", "links")
    lines = ["---"]
    for key in keys:
        if key in meta:
            lines.append(f"{key}: {_fm_value(meta[key])}")
    for key in sorted(k for k in meta if k not in keys):
        lines.append(f"{key}: {_fm_value(meta[key])}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


class MemoryStore:
    def __init__(self, config, root=None):
        self.config = config
        self.root = root or MEMORY_DIR
        self.notes_dir = self.root / "notes"
        self.index_path = self.root / "index.json"
        self.pending_path = self.root / "pending.jsonl"
        self.state_path = self.root / "state.json"
        self.profile_path = self.root / "profile.md"
        self.on_changed = None       # owner marshals to main (UI refresh)
        self._lock = threading.RLock()
        self._index = {}             # slug -> entry (terms as a set)
        self._df = {}                # term -> document frequency
        self._loaded = False

    # -- index ---------------------------------------------------------------

    def _ensure_loaded(self):
        if not self._loaded:
            self._reload()

    def _reload(self):
        """Fold notes/ into the in-memory index, reusing index.json for notes
        whose mtime hasn't moved (so startup stays cheap) and reparsing the
        rest — that is what makes a hand-edited note take effect."""
        cached = {}
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cached = data.get("notes") or {}
        except (OSError, ValueError):
            cached = {}
        index, dirty = {}, False
        for path in sorted(self.notes_dir.glob("*.md")):
            slug = path.stem
            try:
                mtime = int(path.stat().st_mtime)
            except OSError:
                continue
            entry = cached.get(slug)
            if not entry or int(entry.get("mtime") or 0) != mtime:
                entry = self._parse_entry(path, mtime)
                dirty = True
                if entry is None:
                    continue
            index[slug] = {**entry, "terms": set(entry.get("terms") or [])}
        if len(index) != len(cached):
            dirty = True
        self._index = index
        self._df = {}
        for entry in index.values():
            for term in entry["terms"]:
                self._df[term] = self._df.get(term, 0) + 1
        self._loaded = True
        if dirty:
            self._save_index()
        print(f"memory: index {len(index)} note(s), {len(self._df)} term(s)",
              flush=True)

    def _parse_entry(self, path, mtime):
        try:
            meta, body = parse_note(path.read_text(encoding="utf-8"))
        except OSError:
            return None
        title = str(meta.get("title") or path.stem)
        aliases = [str(a) for a in (meta.get("aliases") or [])]
        domains = [str(d) for d in (meta.get("domains") or [])]
        keyed = list(meta.get("terms") or []) + [title] + aliases + domains
        terms = set()
        for chunk in keyed:
            terms |= terms_of(chunk)
        summary = ""
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-", "*")):
                summary = line
                break
        try:
            seen = int(meta.get("seen") or 1)
        except (TypeError, ValueError):
            seen = 1
        return {
            "slug": path.stem,
            "title": title,
            "kind": str(meta.get("kind") or "concept"),
            "domains": domains,
            "aliases": aliases,
            "links": [str(link) for link in (meta.get("links") or [])],
            "seen": seen,
            "first_ts": str(meta.get("first_ts") or ""),
            "last_ts": str(meta.get("last_ts") or ""),
            "summary": summary,
            "terms": sorted(terms),
            "mtime": mtime,
        }

    def _save_index(self):
        notes = {slug: {**entry, "terms": sorted(entry["terms"])}
                 for slug, entry in self._index.items()}
        self._write_json(self.index_path, {
            "schema": SCHEMA, "built_ts": _now_iso(), "notes": notes,
        })

    def _write_json(self, path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        os.replace(tmp, path)

    # -- retrieval (hot path: hotkey -> panel, no LLM) -----------------------

    def _idf(self, term):
        return math.log(1.0 + len(self._index) / (1.0 + self._df.get(term, 0)))

    def recall(self, text, top_k=None, min_score=None):
        """The notes this text is actually about, best first. Pure Python and
        O(terms); safe to call on the worker thread right before streaming.

        The score is QUERY COVERAGE: of the IDF mass of the query terms this
        memory knows anything about, how much does this note cover. Query-side
        normalization (not document-side) is what makes the threshold mean the
        same thing with 5 notes and with 500 — an absolute IDF sum grows with
        the corpus, so a fixed cutoff would drift from "too loose" to "nothing
        ever matches". Terms the memory has never seen are excluded from the
        denominator: an unrelated word in the capture must not dilute a note
        that genuinely covers the rest.

        `min_mass` is the second gate. Coverage alone can be 1.0 on a single
        weak hit (a 2-char Korean prefix), which is exactly the false positive
        that would make the model reference an unrelated note."""
        with self._lock:
            self._ensure_loaded()
            if not self._index:
                return []
            top_k = int(self.config.get("memory_recall_top_k")
                        if top_k is None else top_k)
            min_score = float(self.config.get("memory_recall_min_score")
                              if min_score is None else min_score)
            min_mass = float(self.config.get("memory_recall_min_mass"))
            known = {term: self._idf(term) for term in terms_of(text)
                     if self._df.get(term)}
            if not known:
                return []
            denominator = sum(known.values())
            if denominator <= 0:
                return []
            scored = []
            for entry in self._index.values():
                hits = known.keys() & entry["terms"]
                if not hits:
                    continue
                mass = sum(known[term] for term in hits)
                coverage = mass / denominator
                if coverage < min_score or mass < min_mass:
                    continue
                score = coverage + 0.08 * math.log1p(max(entry["seen"], 1))
                scored.append((score, mass, entry))
            scored.sort(key=lambda row: (-row[0], -row[1], row[2]["slug"]))
            out = []
            for score, mass, entry in scored[:max(top_k, 0)]:
                item = {k: v for k, v in entry.items() if k != "terms"}
                item["score"] = round(score, 3)
                out.append(item)
            return out

    # -- notes ---------------------------------------------------------------

    def notes(self):
        """Every note, most recently seen first (the 기억 tab's list)."""
        with self._lock:
            self._ensure_loaded()
            rows = [{k: v for k, v in e.items() if k != "terms"}
                    for e in self._index.values()]
        rows.sort(key=lambda r: (r.get("last_ts") or "", r.get("seen") or 0),
                  reverse=True)
        return rows

    def note_body(self, slug):
        try:
            text = (self.notes_dir / f"{slug}.md").read_text(encoding="utf-8")
        except OSError:
            return ""
        _meta, body = parse_note(text)
        return body

    def note_path(self, slug):
        path = self.notes_dir / f"{slug}.md"
        return path if path.exists() else None

    def delete(self, slug):
        with self._lock:
            path = self.notes_dir / f"{slug}.md"
            try:
                path.unlink()
            except OSError:
                return False
            self._index.pop(slug, None)
            self._loaded = False     # df needs a rebuild; next read reloads
            self._reload()
        print(f"memory: deleted note {slug}", flush=True)
        self._notify()
        return True

    def find_slug(self, title, aliases=()):
        """An existing note for this concept, matched by slug or by any alias
        (case-insensitive) — so "GAE" and "Generalized Advantage Estimation"
        don't become two notes."""
        with self._lock:
            self._ensure_loaded()
            wanted = {str(a).strip().lower() for a in (list(aliases) + [title])
                      if str(a).strip()}
            slug = slugify(title)
            if slug in self._index:
                return slug
            for entry in self._index.values():
                names = {entry["title"].lower()}
                names |= {a.lower() for a in entry["aliases"]}
                if wanted & names:
                    return entry["slug"]
        return None

    def upsert(self, concept, context=None):
        """Create or merge one distilled concept. `context` is the reading that
        produced it: {ts, mode, snippet}. Returns (slug, created)."""
        title = str(concept.get("title") or "").strip()
        if not title:
            return None, False
        aliases = [str(a).strip() for a in (concept.get("aliases") or [])
                   if str(a).strip()]
        with self._lock:
            slug = (self.find_slug(title, aliases)
                    or slugify(title, fallback_seed=title))
            path = self.notes_dir / f"{slug}.md"
            now = (context or {}).get("ts") or _now_iso()
            if path.exists():
                meta, body = parse_note(path.read_text(encoding="utf-8"))
                created = False
            else:
                meta, body, created = {}, "", True
            merged = dict(meta)
            merged["name"] = slug
            merged["title"] = str(meta.get("title") or title)
            merged["kind"] = str(concept.get("kind")
                                 or meta.get("kind") or "concept")
            links = [link for link in (concept.get("links") or [])
                     if str(link).strip() != slug]   # a note linking itself
            for key, incoming in (("domains", concept.get("domains")),
                                  ("aliases", aliases),
                                  ("terms", concept.get("terms")),
                                  ("links", links)):
                have = [str(v) for v in (meta.get(key) or [])]
                seen_lower = {v.lower() for v in have}
                for value in (incoming or []):
                    value = str(value).strip()
                    if value and value.lower() not in seen_lower:
                        have.append(value)
                        seen_lower.add(value.lower())
                merged[key] = have[:24]
            try:
                merged["seen"] = int(meta.get("seen") or 0) + 1
            except (TypeError, ValueError):
                merged["seen"] = 1
            merged["first_ts"] = str(meta.get("first_ts") or now)
            merged["last_ts"] = now
            body = self._merge_body(body, concept, context)
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(render_note(merged, body), encoding="utf-8")
            entry = self._parse_entry(path, int(path.stat().st_mtime))
            if entry is not None:
                previous = self._index.get(slug)
                if previous:
                    for term in previous["terms"]:
                        self._df[term] = max(self._df.get(term, 1) - 1, 0)
                self._index[slug] = {**entry, "terms": set(entry["terms"])}
                for term in self._index[slug]["terms"]:
                    self._df[term] = self._df.get(term, 0) + 1
                self._save_index()
        print(f"memory: {'new' if created else 'merged'} note {slug} "
              f"seen={merged['seen']}", flush=True)
        return slug, created

    def _merge_body(self, body, concept, context):
        """Keep the first summary (stable identity) and append the reading that
        just happened, newest last, capped — a note is a concept plus the trail
        of where the user met it."""
        summary = str(concept.get("summary") or "").replace("\n", " ").strip()
        head, contexts = [], []
        in_contexts = False
        for line in body.splitlines():
            if line.strip().startswith("## "):
                in_contexts = True
                continue
            (contexts if in_contexts else head).append(line)
        head_text = "\n".join(head).strip()
        if not head_text and summary:
            head_text = summary
        elif summary and summary not in head_text:
            head_text = f"{head_text}\n{summary}".strip()
        lines = [line.strip() for line in contexts
                 if line.strip().startswith("- ")]
        if context:
            snippet = " ".join(str(context.get("snippet") or "").split())[:110]
            stamp = str(context.get("ts") or "")[:16].replace("T", " ")
            mode = str(context.get("mode") or "")
            entry = f"- {stamp} · {mode} · {snippet}".rstrip(" ·")
            if entry not in lines:
                lines.append(entry)
        lines = lines[-_MAX_CONTEXTS:]
        section = ("\n## seen in\n" + "\n".join(lines)) if lines else ""
        return (head_text + "\n" + section).strip()

    # -- ingestion queue -----------------------------------------------------

    def enqueue(self, mode, input_text, response, ts=None):
        """Called from the main thread right after a session commits. Appending
        a line is all the hot path pays; the distiller drains it later."""
        snippet_chars = int(self.config.get("memory_snippet_chars"))
        record = {
            "ts": ts or _now_iso(),
            "mode": str(mode),
            "input": str(input_text)[:snippet_chars],
            "response": str(response)[:snippet_chars],
        }
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with open(self.pending_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def pending(self, limit=None):
        """The undrained queue head (oldest first)."""
        with self._lock:
            cursor = int(self.state().get("pending_cursor") or 0)
            rows = []
            try:
                with open(self.pending_path, "r", encoding="utf-8") as f:
                    for n, line in enumerate(f):
                        if n < cursor or not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(record, dict):
                            rows.append(record)
                            if limit and len(rows) >= int(limit):
                                break
            except OSError:
                return []
            return rows

    def pending_count(self):
        return len(self.pending())

    def mark_drained(self, count):
        with self._lock:
            state = self.state()
            cursor = int(state.get("pending_cursor") or 0) + int(count)
            state["pending_cursor"] = cursor
            state["distilled"] = int(state.get("distilled") or 0) + int(count)
            self.save_state(state)
            if cursor >= _PENDING_COMPACT_AT:
                self._compact_pending(cursor)

    def compact_pending(self):
        """Drop every already-distilled line from the queue. Called by
        `retire-cache` (M20): once the notes hold the long-term record, the raw
        readings should not survive in the queue either — otherwise "the old
        cache is gone" would be only half true (history.jsonl and the capture
        PNGs pruned, the same text still sitting here). Returns bytes freed.

        Called from the CLI, i.e. a second process, which is the one place the
        single-writer rule bends. `retire-cache` only runs with an empty queue,
        so the window is "an explain finishes during the rewrite" — that one
        reading would miss distillation. Accepted over asking the app (which
        need not be running) for a file rewrite that is already atomic."""
        with self._lock:
            try:
                before = self.pending_path.stat().st_size
            except OSError:
                return 0
            cursor = int(self.state().get("pending_cursor") or 0)
            if not cursor:
                return 0
            self._compact_pending(cursor)
            try:
                return before - self.pending_path.stat().st_size
            except OSError:
                return before

    def _compact_pending(self, cursor):
        keep = self.pending()
        tmp = self.pending_path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for record in keep:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        os.replace(tmp, self.pending_path)
        state = self.state()
        state["pending_cursor"] = 0
        self.save_state(state)
        print(f"memory: pending compacted (dropped {cursor} drained)",
              flush=True)

    # -- state / profile -----------------------------------------------------

    def state(self):
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_state(self, state):
        self._write_json(self.state_path, state)

    def profile(self):
        try:
            return self.profile_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def save_profile(self, text):
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(str(text).strip() + "\n",
                                         encoding="utf-8")
        self._notify()

    def domains(self, limit=8):
        """Domains ranked by how much of the reading falls in them — the cheap,
        LLM-free half of the 관심사 프로필 (used in the prompt preamble).

        Counted on a normalized key (spaces/case folded) because the model
        spells the same field both ways across batches ("노화 생물학" and
        "노화생물학"), which would otherwise show up as two interests. The most
        frequent spelling is what gets displayed."""
        counts, spellings = {}, {}
        for note in self.notes():
            weight = max(int(note.get("seen") or 1), 1)
            for domain in note.get("domains") or []:
                key = "".join(str(domain).split()).lower()
                if not key:
                    continue
                counts[key] = counts.get(key, 0) + weight
                variants = spellings.setdefault(key, {})
                variants[domain] = variants.get(domain, 0) + weight
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        out = []
        for key, _count in ranked[:limit]:
            variants = spellings[key]
            out.append(max(variants, key=lambda name: (variants[name], -len(name))))
        return out

    def stats(self):
        notes = self.notes()
        state = self.state()
        return {
            "notes": len(notes),
            "seen_total": sum(int(n.get("seen") or 0) for n in notes),
            "domains": self.domains(),
            "pending": self.pending_count(),
            "distilled": int(state.get("distilled") or 0),
            "backfill_done_ts": state.get("backfill_done_ts") or "",
            "root": str(self.root),
        }

    def _notify(self):
        if self.on_changed is not None:
            self.on_changed()

"""Config/Keychain helper for install.sh and the `macsist` CLI (M10).

Stdlib-only on purpose: it reuses app/config.py and app/keychain.py (both
stdlib-only), so any python3 — the miniforge base interpreter, the deployed
venv, even /usr/bin/python3 — can run it from a user shell. It always loads
the repo's app/ modules (a user shell CAN read ~/Documents; only launchd
can't), so it works before the first app deploy.

Subcommands (JSON on stdout, exit 0 = ok / 1 = error):
  status               config summary — provider, models, key presence, hotkeys
  memory-*             M20 기억: read the notes / retire the history cache. Reads
                       are files only (memory/store.py is stdlib-only); anything
                       that needs the LLM is asked of the running app instead
  set-local-provider   point the local provider at the chosen models
  set-api-provider     add/update an external provider (key via stdin only)
  probe                health-check the active provider (auth header stays in
                       python — never on a shell command line)

Secrets: keys are read from stdin, stored via keychain.set_key, and only the
Keychain ACCOUNT NAME ever appears in config.json or on stdout.
"""

import argparse
import contextlib
import json
import re
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import i18n  # noqa: E402
import keychain  # noqa: E402
from config import ConfigStore  # noqa: E402


def _unique_account(providers, name):
    """Same slug logic as settings_window._unique_account (settings_window.py
    — not importable here: it pulls in AppKit). Keep the two in sync."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    base = f"provider-{slug}" if slug else "provider"
    taken = {
        str(p.get("api_key_env_or_value", "")).strip() for p in providers
    }
    account, n = base, 2
    while account in taken:
        account, n = f"{base}-{n}", n + 1
    return account


def _emit(payload, ok=True):
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def cmd_status(args):
    try:
        store = ConfigStore()
    except Exception as exc:
        if getattr(args, "shell", False):
            print("CFG_OK=0")
            return 1
        return _emit({"config_ok": False, "error": repr(exc)}, ok=False)
    provider = store.active_provider()
    ref = str(provider.get("api_key_env_or_value", "")).strip()
    key_present = keychain.resolve_key(ref) is not None if ref else None
    if getattr(args, "shell", False):
        # eval-able KEY=VALUE lines for cli/macsist (avoids a jq dependency).
        q = shlex.quote
        flag = lambda v: "1" if v else "0"  # noqa: E731
        print("\n".join([
            "CFG_OK=1",
            f"P_NAME={q(str(provider.get('name', '')))}",
            f"P_BASE_URL={q(str(provider.get('base_url', '')))}",
            f"P_IS_LOCAL={flag(provider.get('is_local'))}",
            f"P_EXPLAIN={q(str(provider.get('explain_model', '')))}",
            f"P_VISION={q(str(provider.get('vision_model', '')))}",
            f"P_KEY_ACCOUNT={q(ref)}",
            f"P_KEY_PRESENT={'' if key_present is None else flag(key_present)}",
            f"HK_TEXT={q(str(store.get('hotkey_explain_text') or ''))}",
            f"HK_REGION={q(str(store.get('hotkey_explain_region') or ''))}",
            f"HK_HISTORY={q(str(store.get('hotkey_open_history') or ''))}",
        ]))
        return 0
    return _emit({
        "config_ok": True,
        "active_provider": {
            "name": provider.get("name"),
            "base_url": provider.get("base_url"),
            "is_local": bool(provider.get("is_local")),
            "explain_model": provider.get("explain_model"),
            "vision_model": provider.get("vision_model"),
            "key_account": ref,
            "key_present": key_present,
        },
        "providers": [p.get("name") for p in store.get("providers") or []],
        "language": store.get("language"),
        "hotkeys": {
            "explain_text": store.get("hotkey_explain_text"),
            "explain_region": store.get("hotkey_explain_region"),
            "open_history": store.get("hotkey_open_history"),
        },
    })


def cmd_set_local_provider(args):
    store = ConfigStore()
    providers = store.get("providers") or []
    # Match on is_local, not name — the user may have renamed the entry.
    local = next((p for p in providers if p.get("is_local")), None)
    if local is None:
        local = {
            "name": "로컬 서버",
            "base_url": "http://127.0.0.1:8000",
            "api_key_env_or_value": "",
            "is_local": True,
        }
        providers.insert(0, local)
    if args.mode == "full":
        if not args.lm_model:
            print("--mode full에는 --lm-model이 필요합니다", file=sys.stderr)
            return 1
        local["explain_model"] = args.lm_model
        local["vision_model"] = args.vlm_model
    else:  # vlm-only: one multimodal model serves both
        local["explain_model"] = args.vlm_model
        local["vision_model"] = args.vlm_model
    store.set("providers", providers)
    store.set("active_provider", local["name"])
    store.set("onboarded", True)  # installer configured a backend (M13)
    store.save()
    return _emit({"saved": True, "provider": local["name"],
                  "explain_model": local["explain_model"],
                  "vision_model": local["vision_model"]})


def cmd_set_api_provider(args):
    store = ConfigStore()
    providers = store.get("providers") or []
    entry = next((p for p in providers if p.get("name") == args.name), None)
    if entry is None:
        entry = {"name": args.name, "api_key_env_or_value": "",
                 "is_local": False}
        providers.append(entry)
    entry["base_url"] = args.base_url.rstrip("/")
    entry["explain_model"] = args.explain_model
    entry["vision_model"] = args.vision_model or args.explain_model
    if args.key_stdin:
        secret = sys.stdin.readline().rstrip("\n")
        if not secret:
            print("stdin에서 키를 읽지 못했습니다", file=sys.stderr)
            return 1
        ref = str(entry.get("api_key_env_or_value", "")).strip()
        if not ref or ref.startswith("env:"):
            ref = _unique_account(providers, args.name)
        keychain.set_key(ref, secret)
        entry["api_key_env_or_value"] = ref
    store.set("providers", providers)
    store.set("active_provider", args.name)
    store.set("onboarded", True)  # installer configured a backend (M13)
    store.save()
    return _emit({"saved": True, "provider": args.name,
                  "key_account": entry.get("api_key_env_or_value", "")})


def cmd_set_language(args):
    store = ConfigStore()
    store.set("language", args.code)
    store.save()
    return _emit({"saved": True, "language": args.code})


def cmd_probe(args):
    store = ConfigStore()
    provider = store.active_provider()
    base = str(provider.get("base_url", "")).rstrip("/")
    name = provider.get("name")
    try:
        if provider.get("is_local"):
            with urllib.request.urlopen(f"{base}/health", timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            ok = body.get("status") == "ok"
            return _emit({"ok": ok, "provider": name, "detail": body}, ok=ok)
        # External: authed /v1/models, same contract as health.py (M9).
        req = urllib.request.Request(f"{base}/v1/models")
        key = keychain.resolve_key(provider.get("api_key_env_or_value", ""))
        if key:
            req.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        ids = [m.get("id") for m in body.get("data", [])]
        return _emit({"ok": True, "provider": name, "models": len(ids)})
    except urllib.error.HTTPError as exc:
        hint = " — API 키를 확인하세요" if exc.code in (401, 403) else ""
        return _emit({"ok": False, "provider": name,
                      "detail": f"HTTP {exc.code}{hint}"}, ok=False)
    except Exception as exc:
        return _emit({"ok": False, "provider": name,
                      "detail": f"접속 불가: {exc}"}, ok=False)


def cmd_tasks(args):
    """M13: print the Hermes kanban board (read-only). Works without the app
    running — reads kanban.db directly (CLI fallback inside HermesBridge)."""
    from assistant.hermes_bridge import HermesBridge
    store = ConfigStore()
    bridge = HermesBridge(store)
    tasks = bridge.board_tasks()
    if getattr(args, "json", False):
        return _emit(tasks)
    if not tasks:
        print("표시할 작업이 없습니다 (kanban 보드 비어 있음 또는 Hermes 미설치)")
        return 0
    for task in tasks:
        status = str(task.get("status", "") or "?")
        title = str(task.get("title", "") or "—")
        tenant = str(task.get("tenant", "") or "")
        suffix = f"  ({tenant})" if tenant else ""
        print(f"· [{status}] {title}{suffix}")
    return 0


def cmd_inbox(args):
    """M14: print the assistant inbox (pending + approved-not-run proposals)."""
    from assistant.proposal_store import ProposalStore
    store = ProposalStore(ConfigStore())
    items = store.inbox()
    if getattr(args, "json", False):
        return _emit(items)
    if not items:
        print("받은 작업함이 비어 있습니다")
        return 0
    for p in items:
        print(f"· [{p.get('status')}/{p.get('risk')}] {p.get('id')}  "
              f"{p.get('title')}")
    return 0


def cmd_gmail_status(args):
    """M17: Gmail connection summary (Keychain refresh-token presence + config).
    Stdlib + keychain only — never imports gmail_oauth (which needs httpx)."""
    try:
        store = ConfigStore()
    except Exception as exc:
        return _emit({"error": str(exc)}, ok=False)
    try:
        from config import GMAIL_OAUTH_REFRESH_ACCOUNT
        connected = bool(keychain.get_key(GMAIL_OAUTH_REFRESH_ACCOUNT))
    except keychain.KeychainError:
        connected = False
    return _emit({
        "enabled": bool(store.get("gmail_enabled")),
        "connected": connected,
        "account": store.get("gmail_account") or "",
        "poll_interval": store.get("gmail_poll_interval"),
        "filter": store.get("gmail_query_filter"),
    })


def cmd_calendar_status(args):
    """M18: Calendar connection summary (Keychain ICS-URL presence + config)."""
    try:
        store = ConfigStore()
    except Exception as exc:
        return _emit({"error": str(exc)}, ok=False)
    try:
        from config import CALENDAR_ICS_ACCOUNT
        connected = bool(keychain.get_key(CALENDAR_ICS_ACCOUNT))
    except keychain.KeychainError:
        connected = False
    return _emit({
        "enabled": bool(store.get("calendar_enabled")),
        "connected": connected,
        "lead_min": store.get("calendar_alert_lead_min"),
        "window_days": store.get("calendar_window_days"),
        "conflict": bool(store.get("calendar_conflict_enabled")),
    })


# ── M20 기억(memory) ────────────────────────────────────────────────────────
# Reading memory is file work, so it belongs here (stdlib-only, runs under any
# python3). WRITING notes needs httpx + the provider config, so the CLI asks the
# running app for that (`macsist memory backfill|distill|profile` post
# distributed notifications) — one writer, no two processes folding the same
# notes.


@contextlib.contextmanager
def _quiet():
    """The app modules log to stdout (app.log convention). Here stdout is the
    JSON contract, so their chatter goes to stderr instead."""
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _memory_store():
    from memory.store import MemoryStore
    return MemoryStore(ConfigStore())


def cmd_memory_status(args):
    try:
        with _quiet():
            store = _memory_store()
    except Exception as exc:
        return _emit({"error": str(exc)}, ok=False)
    with _quiet():
        stats = store.stats()
        stats["profile"] = store.profile()
        stats["recent"] = [
            {k: note[k] for k in ("slug", "title", "seen", "last_ts", "domains")}
            for note in store.notes()[:int(args.limit)]
        ]
    if getattr(args, "doctor", False):
        # `macsist doctor` lines. The marker is the first token and the shell
        # swaps it for the colored glyph — building these lines in python keeps
        # the CLI free of nested-quoted python (which broke twice).
        mark = "OK" if stats["notes"] else "WARN"
        print(f"{mark} 기억 노트 {stats['notes']}개 · "
              f"정리 대기 {stats['pending']}건")
        print(f"DOT 관심 분야: {', '.join(stats['domains']) or '-'}")
        print(f"DOT 백필: {stats['backfill_done_ts'] or '아직 '
                            '(macsist memory backfill)'}")
        return 0
    if not getattr(args, "text", False):
        return _emit(stats)
    print(f"기억 노트   : {stats['notes']}개 "
          f"(누적 {stats['seen_total']}회 마주침)")
    print(f"관심 분야   : {', '.join(stats['domains']) or '-'}")
    print(f"정리 대기   : {stats['pending']}건 "
          f"(누적 정리 {stats['distilled']}건)")
    print(f"백필 완료   : {stats['backfill_done_ts'] or '아직'}")
    print(f"폴더        : {stats['root']}")
    if stats["recent"]:
        print("\n최근 기억:")
        for note in stats["recent"]:
            domains = ", ".join(note.get("domains") or [])
            print(f"  · {note['title'][:44]:46s} x{note['seen']:<3d} "
                  f"{str(note['last_ts'])[:10]}  {domains}")
    if stats["profile"]:
        print("\n[관심사 프로필]")
        print(stats["profile"])
    return 0


def cmd_memory_list(args):
    try:
        with _quiet():
            store = _memory_store()
    except Exception as exc:
        return _emit({"error": str(exc)}, ok=False)
    with _quiet():
        notes = store.notes()[:int(args.limit)]
    if getattr(args, "json", False):
        return _emit({"count": len(notes), "notes": notes})
    for note in notes:
        domains = ", ".join(note.get("domains") or [])
        print(f"{note['slug']:40s} {str(note.get('last_ts'))[:10]} "
              f"x{note.get('seen', 1):<3d} {note['title'][:44]:46s} {domains}")
    if not notes:
        print("(기억이 없습니다 — `macsist memory backfill`)")
    return 0


def cmd_memory_show(args):
    try:
        with _quiet():
            store = _memory_store()
    except Exception as exc:
        return _emit({"error": str(exc)}, ok=False)
    with _quiet():
        path = store.note_path(args.slug)
    if path is None:
        print(f"그런 기억이 없습니다: {args.slug}", file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_memory_retire_cache(args):
    """Shrink the explain history to a short rolling buffer now that memory holds
    the long-term record (M20). HistoryStore._prune rewrites the JSONL atomically
    AND deletes the capture PNGs no surviving record references, so this reclaims
    the history_images/ space too.

    Refuses while memory is empty or the queue still has undistilled readings —
    the cache is the only other copy of those, so it must not be dropped before
    they have been turned into notes."""
    try:
        with _quiet():
            config = ConfigStore()
            store = _memory_store()
            from history_store import HistoryStore
            history = HistoryStore(config)
    except Exception as exc:
        return _emit({"error": str(exc)}, ok=False)
    with _quiet():
        stats = store.stats()
    keep = int(args.keep if args.keep is not None
               else config.get("memory_history_rolling"))
    before = len(history.load())
    if not args.force:
        refusal = None
        if stats["notes"] == 0:
            refusal = {"error": "기억이 비어 있습니다 — 먼저 "
                                "`macsist memory backfill`", "notes": 0}
        elif stats["pending"] > 0:
            refusal = {"error": "아직 정리되지 않은 읽기 기록이 "
                                f"{stats['pending']}건 남았습니다 — "
                                "`macsist memory distill` 후 다시 시도",
                       "pending": stats["pending"]}
        if refusal is not None:
            if getattr(args, "text", False):
                print("은퇴 보류: " + refusal["error"])
                return 1
            return _emit(refusal, ok=False)
    config.set("history_max_items", keep)
    config.save()
    with _quiet():
        history._prune(keep)
        queue_freed = store.compact_pending()
    result = {
        "queue_bytes_freed": queue_freed,
        "kept": keep,
        "records_before": before,
        "records_after": len(history.load()),
        "history_max_items": keep,
        "notes": stats["notes"],
        "images_dir": str(history.images_dir),
        "images_left": (len(list(history.images_dir.glob("*.png")))
                        if history.images_dir.exists() else 0),
    }
    if not getattr(args, "text", False):
        return _emit(result)
    print(f"설명 기록 {result['records_before']}건 → "
          f"{result['records_after']}건 (history_max_items={keep})")
    print(f"남은 캡처 이미지: {result['images_left']}장")
    if result["queue_bytes_freed"]:
        print(f"정리 완료된 읽기 큐 {result['queue_bytes_freed'] // 1024}KB 회수")
    print(f"기억 노트 {result['notes']}개가 장기 기록을 맡습니다.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status")
    p.add_argument("--shell", action="store_true",
                   help="eval-able KEY=VALUE lines instead of JSON")

    p = sub.add_parser("set-local-provider")
    p.add_argument("--mode", choices=["full", "vlm-only"], required=True)
    p.add_argument("--vlm-model", required=True)
    p.add_argument("--lm-model")

    p = sub.add_parser("set-api-provider")
    p.add_argument("--name", required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--explain-model", required=True)
    p.add_argument("--vision-model")
    p.add_argument("--key-stdin", action="store_true")

    p = sub.add_parser("set-language")
    p.add_argument("code", choices=list(i18n.LANGUAGES))

    sub.add_parser("probe")

    p = sub.add_parser("tasks")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("inbox")
    p.add_argument("--json", action="store_true")

    sub.add_parser("gmail-status")
    sub.add_parser("calendar-status")

    p = sub.add_parser("memory-status")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--text", action="store_true",
                   help="human-readable summary instead of JSON")
    p.add_argument("--doctor", action="store_true",
                   help="`macsist doctor` lines (OK/WARN/DOT markers)")

    p = sub.add_parser("memory-list")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("memory-show")
    p.add_argument("slug")

    p = sub.add_parser("memory-retire-cache")
    p.add_argument("--keep", type=int,
                   help="history records to keep (default memory_history_rolling)")
    p.add_argument("--force", action="store_true",
                   help="retire even with an empty memory / a non-empty queue")
    p.add_argument("--text", action="store_true",
                   help="human-readable summary instead of JSON")

    args = parser.parse_args()
    handler = {
        "status": cmd_status,
        "set-local-provider": cmd_set_local_provider,
        "set-api-provider": cmd_set_api_provider,
        "set-language": cmd_set_language,
        "probe": cmd_probe,
        "tasks": cmd_tasks,
        "inbox": cmd_inbox,
        "gmail-status": cmd_gmail_status,
        "calendar-status": cmd_calendar_status,
        "memory-status": cmd_memory_status,
        "memory-list": cmd_memory_list,
        "memory-show": cmd_memory_show,
        "memory-retire-cache": cmd_memory_retire_cache,
    }[args.cmd]
    sys.exit(handler(args))


if __name__ == "__main__":
    main()

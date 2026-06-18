"""Config/Keychain helper for install.sh and the `macsist` CLI (M10).

Stdlib-only on purpose: it reuses app/config.py and app/keychain.py (both
stdlib-only), so any python3 — the miniforge base interpreter, the deployed
venv, even /usr/bin/python3 — can run it from a user shell. It always loads
the repo's app/ modules (a user shell CAN read ~/Documents; only launchd
can't), so it works before the first app deploy.

Subcommands (JSON on stdout, exit 0 = ok / 1 = error):
  status               config summary — provider, models, key presence, hotkeys
  set-local-provider   point the local provider at the chosen models
  set-api-provider     add/update an external provider (key via stdin only)
  probe                health-check the active provider (auth header stays in
                       python — never on a shell command line)

Secrets: keys are read from stdin, stored via keychain.set_key, and only the
Keychain ACCOUNT NAME ever appears in config.json or on stdout.
"""

import argparse
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
    }[args.cmd]
    sys.exit(handler(args))


if __name__ == "__main__":
    main()

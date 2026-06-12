"""Keychain — API key storage via the `security` CLI (M9).

config.json never holds a key, only a reference (`api_key_env_or_value`):
"" (no auth) · "env:NAME" (environment variable) · anything else = the
account name of a generic-password item under SERVICE in the login keychain.

Why the CLI and not Security.framework: items created by
`/usr/bin/security` get an ACL trusting that same Apple-signed binary, so
reads through it never pop a keychain prompt — including under launchd,
which runs in the user's GUI session where the login keychain is unlocked.
(The partition-list caveat only affects apps calling the framework
directly; we never do.)

Tradeoff, accepted for a single-user app: the secret transits argv of a
short-lived process (visible in `ps` for milliseconds). `security -i`
stdin mode exists if this ever matters.

Never log key values — errors carry only the return code and stderr of
set/delete (find's stdout is the secret and must not leak into messages).
"""

import os
import subprocess

SERVICE = "com.macsist"  # one service; one account per provider

_RC_NOT_FOUND = 44  # errSecItemNotFound


class KeychainError(Exception):
    """User-facing error with a clean one-line message (like LLMError)."""


def _run(args):
    return subprocess.run(
        ["security", *args], capture_output=True, text=True
    )


def set_key(account, secret):
    """Create or update (-U) the generic password for `account`."""
    proc = _run([
        "add-generic-password", "-U", "-s", SERVICE, "-a", account,
        "-w", secret, "-j", "Macsist provider API key",
    ])
    if proc.returncode != 0:
        raise KeychainError(
            f"Keychain 저장 실패 (security rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )


def get_key(account):
    """Return the stored key, or None if no item exists."""
    proc = _run([
        "find-generic-password", "-s", SERVICE, "-a", account, "-w",
    ])
    if proc.returncode == _RC_NOT_FOUND:
        return None
    if proc.returncode != 0:
        # never include stdout here — it would be the secret on success paths
        raise KeychainError(
            f"Keychain 조회 실패 (security rc={proc.returncode})"
        )
    return proc.stdout.rstrip("\n")


def delete_key(account):
    """Delete the item; a missing item is a no-op."""
    proc = _run([
        "delete-generic-password", "-s", SERVICE, "-a", account,
    ])
    if proc.returncode not in (0, _RC_NOT_FOUND):
        raise KeychainError(
            f"Keychain 삭제 실패 (security rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )


def resolve_key(ref):
    """api_key_env_or_value → actual key or None (no auth header)."""
    ref = str(ref or "").strip()
    if not ref:
        return None
    if ref.startswith("env:"):
        return os.environ.get(ref[len("env:"):]) or None
    return get_key(ref)


def _main():
    import argparse
    import getpass
    import sys

    parser = argparse.ArgumentParser(description="M9 keychain smoke test")
    parser.add_argument("action", choices=["set", "get", "delete"])
    parser.add_argument("account")
    args = parser.parse_args()

    try:
        if args.action == "set":
            secret = getpass.getpass(f"{args.account} 키 입력: ")
            if not secret:
                print("빈 키 — 취소", file=sys.stderr)
                sys.exit(1)
            set_key(args.account, secret)
            print(f"저장됨: {SERVICE}/{args.account}")
        elif args.action == "get":
            key = get_key(args.account)
            print("(키 없음)" if key is None else f"(키 있음, {len(key)}자)")
        else:
            delete_key(args.account)
            print(f"삭제됨(또는 없음): {SERVICE}/{args.account}")
    except KeychainError as err:
        print(f"오류: {err}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()

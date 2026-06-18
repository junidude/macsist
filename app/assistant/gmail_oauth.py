"""gmail_oauth.py — Gmail OAuth via loopback PKCE (M17, docs/ASSISTANT.md §6.4).

The user creates a Google Cloud **Desktop** OAuth client once and drops the
downloaded JSON at `gmail_client_json_path` (git-ignored). `connect()` reads
that file, opens the consent page in the browser, captures the auth code on a
throwaway `127.0.0.1:<port>` server, exchanges it (with the PKCE verifier) for a
**refresh token**, and stores everything in the Keychain:

  gmail.oauth.client   {"client_id":…, "client_secret":…}  (loaded once)
  gmail.oauth.refresh  the long-lived refresh token

Access tokens are NEVER persisted — `access_token()` mints a short-lived one in
memory on demand. config.json holds no secret (hard rule).

Desktop-client note: the "client_secret" of an installed app is not actually
secret (it ships in the app), so PKCE — not the secret — is what protects the
exchange. Google still wants the secret echoed on the token call, so we keep it.

Threading: `connect()` runs the local HTTP server inline and blocks until the
redirect arrives (or times out); call it from a worker thread (the Settings
button does). Stdlib + httpx only — no google-api-python-client.
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import urllib.parse
import webbrowser

import httpx

import keychain
from config import (
    GMAIL_OAUTH_CLIENT_ACCOUNT as CLIENT_ACCOUNT,
    GMAIL_OAUTH_REFRESH_ACCOUNT as REFRESH_ACCOUNT,
)
from i18n import t

_AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"
# compose covers drafts.create; send covers drafts.send (the 2nd-gesture path);
# readonly covers history.list / messages.get. The two-step send keeps send
# behind an explicit user gesture regardless of the granted scope.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailAuthError(Exception):
    """User-facing one-line error (like LLMError / KeychainError)."""


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier).digest()).rstrip(b"=")
    return verifier.decode(), challenge.decode()


def load_client(config):
    """Return {client_id, client_secret} — from the Keychain if already
    imported, else read once from the GCP JSON file and cache it there."""
    cached = keychain.get_key(CLIENT_ACCOUNT)
    if cached:
        try:
            data = json.loads(cached)
            if data.get("client_id"):
                return data
        except ValueError:
            pass
    path = os.path.expanduser(str(config.get("gmail_client_json_path")))
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise GmailAuthError(t("gmail.oauth.client_empty").format(path=path))
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        raise GmailAuthError(
            t("gmail.oauth.client_unreadable").format(err=exc)) from None
    node = raw.get("installed") or raw.get("web") or raw
    cid, csecret = node.get("client_id"), node.get("client_secret")
    if not cid:
        raise GmailAuthError(t("gmail.oauth.no_client_id"))
    client = {"client_id": cid, "client_secret": csecret or ""}
    keychain.set_key(CLIENT_ACCOUNT, json.dumps(client))
    return client


def is_connected():
    """True once a refresh token is stored (the Settings status line / doctor)."""
    try:
        return bool(keychain.get_key(REFRESH_ACCOUNT))
    except keychain.KeychainError:
        return False


def disconnect():
    keychain.delete_key(REFRESH_ACCOUNT)


class _CodeHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (stdlib selector name)
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.server.auth_code = (params.get("code") or [None])[0]
        self.server.auth_error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = (t("gmail.oauth.page_ok") if self.server.auth_code
               else t("gmail.oauth.page_fail"))
        self.wfile.write(
            f"<html><body style='font-family:sans-serif;padding:3em'>"
            f"<h2>Macsist · Gmail</h2><p>{msg}</p></body></html>"
            .encode("utf-8"))

    def log_message(self, *_args):  # silence stdlib request logging
        pass


def connect(config, timeout=180):
    """Run the full loopback-PKCE consent flow. Blocks until the browser
    redirect arrives (or `timeout` seconds). On success the refresh token is in
    the Keychain and the address is returned; raises GmailAuthError otherwise.
    Call from a worker thread."""
    client = load_client(config)
    verifier, challenge = _pkce_pair()
    # loopback server on an OS-chosen free port (Google allows any 127.0.0.1 port)
    server = http.server.HTTPServer(("127.0.0.1", 0), _CodeHandler)
    server.auth_code = server.auth_error = None
    server.timeout = timeout
    redirect_uri = f"http://127.0.0.1:{server.server_address[1]}/"

    state = secrets.token_urlsafe(16)
    auth_url = _AUTH_URI + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",          # force a refresh_token every time
        "state": state,
    })
    print("gmail oauth: opening consent page", flush=True)
    webbrowser.open(auth_url)
    try:
        server.handle_request()        # blocks until one redirect (or timeout)
    except socket.timeout:
        raise GmailAuthError(t("gmail.oauth.timeout")) from None
    finally:
        server.server_close()

    if server.auth_error or not server.auth_code:
        raise GmailAuthError(t("gmail.oauth.consent_failed").format(
            err=server.auth_error or "no code"))

    try:
        resp = httpx.post(_TOKEN_URI, data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code": server.auth_code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }, timeout=30)
    except httpx.HTTPError as exc:
        raise GmailAuthError(t("gmail.oauth.token_comm").format(
            err=exc.__class__.__name__)) from None
    if resp.status_code != 200:
        raise GmailAuthError(t("gmail.oauth.token_failed").format(
            status=resp.status_code))
    tok = resp.json()
    refresh = tok.get("refresh_token")
    if not refresh:
        raise GmailAuthError(t("gmail.oauth.no_refresh"))
    keychain.set_key(REFRESH_ACCOUNT, refresh)
    addr = _whoami(tok.get("access_token"))
    if addr:
        config.set("gmail_account", addr)
        config.save()
    print(f"gmail oauth: connected ({addr or 'unknown'})", flush=True)
    return addr or ""


def access_token():
    """Mint a short-lived access token from the stored refresh token. Returns
    the token string. Never persisted. Raises GmailAuthError if not connected."""
    refresh = keychain.get_key(REFRESH_ACCOUNT)
    if not refresh:
        raise GmailAuthError(t("gmail.oauth.not_connected"))
    client = keychain.get_key(CLIENT_ACCOUNT)
    if not client:
        raise GmailAuthError(t("gmail.oauth.no_client"))
    client = json.loads(client)
    try:
        resp = httpx.post(_TOKEN_URI, data={
            "client_id": client["client_id"],
            "client_secret": client.get("client_secret", ""),
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }, timeout=30)
    except httpx.HTTPError as exc:
        raise GmailAuthError(t("gmail.oauth.refresh_comm").format(
            err=exc.__class__.__name__)) from None
    if resp.status_code != 200:
        # a revoked / expired grant comes back 400 invalid_grant — surface it so
        # the user re-connects instead of silently failing every poll.
        raise GmailAuthError(t("gmail.oauth.refresh_failed").format(
            status=resp.status_code))
    token = resp.json().get("access_token")
    if not token:
        raise GmailAuthError(t("gmail.oauth.no_access"))
    return token


def _whoami(access):
    """Best-effort: the connected address via the userinfo/profile endpoint."""
    if not access:
        return ""
    try:
        r = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access}"}, timeout=15)
        if r.status_code == 200:
            return r.json().get("emailAddress", "") or ""
    except httpx.HTTPError:
        pass
    return ""


def _main():
    """Smoke test: `python -m assistant.gmail_oauth connect|status` from app/."""
    import sys

    from config import ConfigStore

    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    config = ConfigStore()
    try:
        if action == "connect":
            print("연결됨:", connect(config))
        elif action == "status":
            print("connected" if is_connected() else "not connected",
                  "·", config.get("gmail_account") or "(no account)")
        elif action == "token":
            print("access token len:", len(access_token()))
        elif action == "disconnect":
            disconnect()
            print("disconnected")
        else:
            print("usage: connect|status|token|disconnect")
    except (GmailAuthError, keychain.KeychainError) as exc:
        print("오류:", exc)
        raise SystemExit(1)


if __name__ == "__main__":
    _main()

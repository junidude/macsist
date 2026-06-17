"""gmail_client.py — thin Gmail REST client over httpx (M17, §6.4).

Just the surface M17 needs: incremental change detection (`history.list` from a
stored historyId, falling back to `messages.list` on a 404 expired-cursor),
message fetch (metadata-only headers+snippet vs. full body — full only for the
1–2 messages we actually triage, for privacy + tokens), and the two-step send
(`drafts.create` then, behind a separate user gesture, `drafts.send`).

Every method returns a dict; transport / non-2xx errors become `{"error": …}`
(remote_exec.py convention) so a poll never raises into the daemon thread.
Access tokens come from gmail_oauth.access_token() — minted per call, never
stored. Worker-thread only (network); the monitor marshals results to main.
"""

import base64
import email.utils
import json

import httpx

from assistant import gmail_oauth

_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailClient:
    def __init__(self, config):
        self.config = config

    # -- transport -----------------------------------------------------------

    def _request(self, method, path, *, params=None, body=None, timeout=30):
        try:
            token = gmail_oauth.access_token()
        except gmail_oauth.GmailAuthError as exc:
            return {"error": str(exc)}
        headers = {"Authorization": f"Bearer {token}"}
        try:
            r = httpx.request(method, _API + path, params=params, json=body,
                              headers=headers, timeout=timeout)
        except httpx.HTTPError as exc:
            return {"error": f"Gmail 통신 오류: {exc.__class__.__name__}"}
        if r.status_code == 404:
            return {"error": "404", "status": 404}
        if r.status_code >= 400:
            detail = ""
            try:
                detail = r.json().get("error", {}).get("message", "")
            except ValueError:
                pass
            return {"error": f"Gmail HTTP {r.status_code}: {detail}"[:200],
                    "status": r.status_code}
        try:
            return r.json()
        except ValueError:
            return {}

    # -- change detection ----------------------------------------------------

    def profile(self):
        """{emailAddress, historyId, …} — also the way to seed the cursor."""
        return self._request("GET", "/profile")

    def history_since(self, start_history_id):
        """Message ids changed since the cursor. Returns
        {"ids": [...], "history_id": "<latest>"} or {"error"/"resync": …}.
        A 404 (cursor too old / expired) signals the caller to resync."""
        ids, page, latest = [], None, str(start_history_id)
        while True:
            params = {"startHistoryId": start_history_id,
                      "historyTypes": "messageAdded"}
            if page:
                params["pageToken"] = page
            data = self._request("GET", "/history", params=params)
            if data.get("status") == 404:
                return {"resync": True}
            if "error" in data:
                return data
            latest = data.get("historyId", latest)
            for h in data.get("history", []):
                for m in h.get("messagesAdded", []):
                    mid = (m.get("message") or {}).get("id")
                    if mid:
                        ids.append(mid)
            page = data.get("nextPageToken")
            if not page:
                break
        # de-dup while preserving order
        seen, uniq = set(), []
        for mid in ids:
            if mid not in seen:
                seen.add(mid)
                uniq.append(mid)
        return {"ids": uniq, "history_id": latest}

    def list_query(self, query, max_results=15):
        """messages.list — the resync / first-run path. Returns
        {"ids": [...], "history_id": "<from profile>"}."""
        data = self._request("GET", "/messages",
                             params={"q": query, "maxResults": int(max_results)})
        if "error" in data:
            return data
        ids = [m.get("id") for m in data.get("messages", []) if m.get("id")]
        prof = self.profile()
        return {"ids": ids, "history_id": prof.get("historyId")}

    # -- message fetch -------------------------------------------------------

    def get_meta(self, msg_id):
        """Headers + snippet only (no body download). Returns a flat dict:
        {id, thread_id, from, subject, date, snippet, message_id_header}."""
        data = self._request(
            "GET", f"/messages/{msg_id}",
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date", "Message-ID"]})
        if "error" in data:
            return data
        headers = {h["name"].lower(): h["value"]
                   for h in (data.get("payload", {}).get("headers") or [])}
        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "from": headers.get("from", ""),
            "subject": headers.get("subject", "(제목 없음)"),
            "date": headers.get("date", ""),
            "message_id_header": headers.get("message-id", ""),
            "snippet": data.get("snippet", ""),
        }

    def get_body(self, msg_id, limit=4000):
        """Plain-text body of a single message (for the triage picks). Walks
        the MIME tree for the first text/plain part; truncated to `limit`."""
        data = self._request("GET", f"/messages/{msg_id}",
                             params={"format": "full"})
        if "error" in data:
            return data
        text = _extract_plain(data.get("payload", {}))
        return {"id": msg_id, "thread_id": data.get("threadId"),
                "body": (text or data.get("snippet", ""))[:limit]}

    # -- two-step send -------------------------------------------------------

    def create_draft(self, *, to, subject, body, thread_id=None,
                     in_reply_to=None):
        """Create a real Gmail DRAFT (reversible). Returns {"draft_id":…} or
        {"error":…}. The user can edit it in Gmail before the 2nd-gesture send."""
        raw = _build_mime(to=to, subject=subject, body=body,
                          in_reply_to=in_reply_to)
        message = {"raw": raw}
        if thread_id:
            message["threadId"] = thread_id
        data = self._request("POST", "/drafts", body={"message": message})
        if "error" in data:
            return data
        return {"draft_id": data.get("id"),
                "message_id": (data.get("message") or {}).get("id")}

    def send_draft(self, draft_id):
        """Send an existing DRAFT (the 2nd, explicit gesture). Returns
        {"sent_id":…} or {"error":…}."""
        data = self._request("POST", "/drafts/send", body={"id": draft_id})
        if "error" in data:
            return data
        return {"sent_id": data.get("id"),
                "thread_id": data.get("threadId")}


# -- helpers -----------------------------------------------------------------

def _extract_plain(payload):
    """Depth-first search for the first text/plain part; decode base64url."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if mime == "text/plain" and body.get("data"):
        return _b64(body["data"])
    for part in payload.get("parts", []) or []:
        found = _extract_plain(part)
        if found:
            return found
    # single-part message with the body at the top level
    if body.get("data") and mime.startswith("text/"):
        return _b64(body["data"])
    return ""


def _b64(data):
    try:
        return base64.urlsafe_b64decode(data + "===").decode(
            "utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _addr(from_header):
    """The bare address out of a `Name <a@b.com>` From header."""
    return email.utils.parseaddr(from_header or "")[1] or from_header or ""


def _build_mime(*, to, subject, body, in_reply_to=None):
    """A minimal RFC-822 message, base64url-encoded for the Gmail `raw` field.
    Subject is RFC-2047 encoded so non-ASCII (Korean) headers survive."""
    from email.header import Header
    from email.mime.text import MIMEText

    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = _addr(to)
    msg["Subject"] = str(Header(subject, "utf-8"))
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _main():
    """Smoke test: `python -m assistant.gmail_client profile|list` from app/."""
    import sys

    from config import ConfigStore

    action = sys.argv[1] if len(sys.argv) > 1 else "profile"
    client = GmailClient(ConfigStore())
    if action == "profile":
        print(json.dumps(client.profile(), ensure_ascii=False, indent=2))
    elif action == "list":
        res = client.list_query(client.config.get("gmail_query_filter"), 5)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        for mid in (res.get("ids") or [])[:3]:
            print(json.dumps(client.get_meta(mid), ensure_ascii=False))


if __name__ == "__main__":
    _main()

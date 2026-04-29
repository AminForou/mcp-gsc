"""Vercel function: GET /api/oauth/callback.

Validates the CSRF state, exchanges the code for credentials, resolves the
Google account email, and stores the token in the shared pool in Vercel KV.
"""

import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib import oauth_web, token_store  # noqa: E402


_SUCCESS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>mcp-gsc — account linked</title>
<style>body{{font-family:system-ui,sans-serif;max-width:540px;margin:64px auto;padding:0 16px;color:#222}}
code{{background:#f3f3f3;padding:2px 6px;border-radius:4px}}</style></head>
<body><h1>Linked: {email}</h1>
<p>This Google account is now part of the shared pool. Anyone in your Claude
organization can query its Search Console data through the MCP connector.</p>
<p>Pass <code>account="{email}"</code> to any tool to scope the call to this
account, or call <code>list_linked_accounts</code> to see the full pool.</p>
</body></html>
"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        params = parse_qs(urlparse(self.path).query)
        code = (params.get("code") or [None])[0]
        state = (params.get("state") or [None])[0]
        error = (params.get("error") or [None])[0]

        if error:
            return self._send(400, f"Google returned an error: {error}")
        if not code or not state:
            return self._send(400, "Missing 'code' or 'state' query parameter.")

        if token_store.pop_oauth_state(state) is None:
            return self._send(
                400,
                "Invalid or expired OAuth state. Restart the flow at /api/oauth/start.",
            )

        try:
            creds = oauth_web.exchange_code(code)
            email = oauth_web.userinfo_email(creds)
        except Exception as exc:
            return self._send(500, f"Token exchange failed: {exc}")

        if not email:
            return self._send(500, "Could not resolve Google account email after consent.")

        try:
            token_store.set_token(email, creds.to_json())
        except Exception as exc:
            return self._send(500, f"Failed to persist token: {exc}")

        body = _SUCCESS_HTML.format(email=email).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

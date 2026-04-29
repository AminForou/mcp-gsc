"""Vercel function: GET /api/oauth/start.

Generates a CSRF state, stashes it in Vercel KV with a 10-minute TTL, then
302-redirects the visitor to Google's consent screen. Anyone in the Claude org
who knows the URL can use it to add a new Google account to the shared pool.
"""

import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib import oauth_web, token_store  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - signature required by BaseHTTPRequestHandler
        try:
            state = secrets.token_urlsafe(32)
            token_store.put_oauth_state(state)
            url = oauth_web.build_authorize_url(state)
        except Exception as exc:  # surface configuration errors clearly
            body = f"OAuth start failed: {exc}".encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

"""Vercel function: GET /api/accounts.

Bearer-protected JSON list of currently linked Google accounts. Useful for
debugging and for the operator to confirm a new link succeeded.
"""

import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from lib import token_store  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        expected = os.environ.get("MCP_BEARER_TOKEN")
        if not expected:
            return self._send(503, "MCP_BEARER_TOKEN is not configured on the server.")

        provided = self.headers.get("Authorization", "")
        if not provided.lower().startswith("bearer "):
            return self._send(401, "Missing bearer token.")
        if not hmac.compare_digest(provided[7:].strip(), expected):
            return self._send(401, "Invalid bearer token.")

        try:
            payload = {
                "accounts": token_store.list_accounts(),
                "default": token_store.get_default(),
            }
        except Exception as exc:
            return self._send(500, f"Failed to list accounts: {exc}")

        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
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

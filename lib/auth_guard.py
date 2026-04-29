"""Bearer-token ASGI middleware for the Streamable HTTP MCP endpoint.

Claude org connectors send a static ``Authorization: Bearer <token>`` header on
every request. This middleware compares it against ``MCP_BEARER_TOKEN`` from
the environment and 401s anything that doesn't match, so the endpoint isn't
publicly callable.
"""

from __future__ import annotations

import hmac
import os
from typing import Awaitable, Callable


def bearer_required(app: Callable) -> Callable:
    expected = os.environ.get("MCP_BEARER_TOKEN")

    async def asgi(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return

        if not expected:
            await _send_text(send, 503, "MCP_BEARER_TOKEN is not configured on the server.")
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if not auth.lower().startswith("bearer "):
            await _send_text(send, 401, "Missing bearer token.")
            return
        token = auth[7:].strip()
        if not hmac.compare_digest(token, expected):
            await _send_text(send, 401, "Invalid bearer token.")
            return

        await app(scope, receive, send)

    return asgi


async def _send_text(send, status: int, body: str) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"text/plain; charset=utf-8")],
        }
    )
    await send({"type": "http.response.body", "body": body.encode("utf-8")})

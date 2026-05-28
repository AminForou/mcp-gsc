"""Per-request bearer-token capture for multi-tenant ``GSC_AUTH_MODE=bearer``.

When the env var ``GSC_AUTH_MODE=bearer`` is set, the SSE/streamable-http
transport installs :class:`BearerCaptureMiddleware`, which extracts the
``Authorization: Bearer <token>`` header from each incoming request into a
:class:`contextvars.ContextVar`. ``get_gsc_service()`` then builds Google API
credentials from that per-request token, so the server calls Search Console
as the *user who made the MCP request* rather than as a single shared
identity.

This matches the pattern used by Google's hosted MCPs (drivemcp.googleapis.com
etc.) and lets MCP clients such as LibreChat run the OAuth flow per user and
simply forward the user's access token to the MCP server — no service-account
or on-disk refresh token required on the server side.

Single-tenant modes (OAuth-on-disk, service account) are unchanged and remain
the default when ``GSC_AUTH_MODE`` is unset.

NOTE: This is implemented as a **pure ASGI middleware** rather than subclassing
Starlette's :class:`BaseHTTPMiddleware`. ``BaseHTTPMiddleware`` buffers the
response body, which breaks **streaming SSE responses** with an
``AssertionError: Unexpected message`` from ``body_stream`` — exactly what
FastMCP's SSE endpoint serves. The pure ASGI form does not touch the response
stream at all.
"""

from contextvars import ContextVar
from typing import Optional

current_bearer: ContextVar[Optional[str]] = ContextVar(
    "current_bearer", default=None
)


def _extract_bearer(header_value: str) -> Optional[str]:
    """Return the token from a ``Bearer <token>`` header, or None."""
    if not header_value or not header_value.lower().startswith("bearer "):
        return None
    token = header_value[7:].strip()
    return token or None


class BearerCaptureMiddleware:
    """Pure ASGI middleware that captures ``Authorization: Bearer <token>``
    into :data:`current_bearer` for the duration of each HTTP request.

    Implemented as a pure ASGI middleware (not ``BaseHTTPMiddleware``) so it
    is safe in front of streaming responses such as the FastMCP SSE endpoint.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            # WebSocket / lifespan: pass through unchanged.
            await self.app(scope, receive, send)
            return

        # ASGI headers are list[(bytes, bytes)]; convert lowercase keys to dict.
        headers = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        auth_header = headers.get("authorization", b"").decode("latin-1")
        token = _extract_bearer(auth_header)

        reset_token = current_bearer.set(token)
        try:
            await self.app(scope, receive, send)
        finally:
            current_bearer.reset(reset_token)

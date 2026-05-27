"""Per-request bearer-token capture for multi-tenant `GSC_AUTH_MODE=bearer`.

When the env var ``GSC_AUTH_MODE=bearer`` is set, the SSE/streamable-http
transport installs :class:`BearerCaptureMiddleware`, which extracts the
``Authorization: Bearer <token>`` header from each incoming request into a
:class:`contextvars.ContextVar`.  ``get_gsc_service()`` then builds Google API
credentials from that per-request token, so the server calls Search Console
as the *user who made the MCP request* rather than as a single shared
identity.

This matches the pattern used by Google's hosted MCPs (drivemcp.googleapis.com
etc.) and lets MCP clients such as LibreChat run the OAuth flow per user and
simply forward the user's access token to the MCP server — no service-account
or on-disk refresh token required on the server side.

Single-tenant modes (OAuth-on-disk, service account) are unchanged and remain
the default when ``GSC_AUTH_MODE`` is unset.
"""

from contextvars import ContextVar
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

current_bearer: ContextVar[Optional[str]] = ContextVar(
    "current_bearer", default=None
)


def _extract_bearer(header_value: str) -> Optional[str]:
    """Return the token from a ``Bearer <token>`` header, or None."""
    if not header_value or not header_value.lower().startswith("bearer "):
        return None
    token = header_value[7:].strip()
    return token or None


class BearerCaptureMiddleware(BaseHTTPMiddleware):
    """Captures ``Authorization: Bearer <token>`` into :data:`current_bearer`.

    The token is scoped to the request via :mod:`contextvars`, so per-request
    isolation is preserved across concurrent async handlers.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        token = _extract_bearer(request.headers.get("authorization", ""))
        reset_token = current_bearer.set(token)
        try:
            return await call_next(request)
        finally:
            current_bearer.reset(reset_token)

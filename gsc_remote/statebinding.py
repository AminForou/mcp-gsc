"""Bind the Google federation leg to the browser that started it.

Without this, ``state`` is just a server-side lookup key that anyone can mint.
An attacker registers a client (registration is open, as MCP requires), calls
``/authorize`` to get a state of their choosing, and lures a victim into
completing Google consent with that state. Google returns the victim's code to
our callback; we exchange it, see the *victim's* identity, and hand the
resulting authorization code to the *attacker's* registered redirect_uri. The
attacker then completes the token exchange with the PKCE verifier they chose,
and holds an access token backed by the victim's Google credentials.

The fix is the standard one: at ``/authorize`` we set an opaque, HttpOnly
cookie and store only its hash next to the state row. At the callback we
require a cookie whose hash matches. The victim's browser never visited the
attacker's ``/authorize``, so it carries no such cookie and the flow is
refused.

``SameSite=Lax`` is deliberate: Google's redirect back to us is a cross-site
top-level GET navigation, which Lax permits and Strict would drop.
"""

import contextvars
import hashlib
import secrets

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE_NAME = "gsc_fed_binding"
COOKIE_TTL = 600

# Set by provider.authorize() while handling /authorize; read by the middleware
# below when the response starts. A ContextVar keeps concurrent authorizations
# from seeing each other's binding.
pending_binding: contextvars.ContextVar = contextvars.ContextVar(
    "gsc_pending_binding", default=None
)


def new_binding() -> str:
    return secrets.token_urlsafe(32)


def hash_binding(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def binding_matches(cookie_value, expected_hash) -> bool:
    """Constant-time comparison that treats absent values as a mismatch."""
    if not cookie_value or not expected_hash:
        return False
    return secrets.compare_digest(hash_binding(cookie_value), expected_hash)


class StateBindingMiddleware:
    """Attaches the binding cookie to the /authorize response."""

    def __init__(self, app: ASGIApp, *, secure: bool):
        self.app = app
        self.secure = secure

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http" or scope.get("path") != "/authorize":
            await self.app(scope, receive, send)
            return

        reset_token = pending_binding.set(None)

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                value = pending_binding.get()
                if value:
                    cookie = (
                        f"{COOKIE_NAME}={value}; Path=/oauth/callback; "
                        f"Max-Age={COOKIE_TTL}; HttpOnly; SameSite=Lax"
                    )
                    if self.secure:
                        cookie += "; Secure"
                    MutableHeaders(scope=message).append("set-cookie", cookie)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            pending_binding.reset(reset_token)

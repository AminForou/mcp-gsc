"""Request-scoped Google credentials, injected into the upstream server.

Upstream ``gsc_server`` resolves credentials through one module-level function,
``get_gsc_service()``, which every tool calls. We rebind that name so the
unchanged tool code builds a Search Console service from the per-request user's
credentials when present, and falls back to upstream's own file/ADC resolution
otherwise. ``contextvars`` makes this safe under concurrency: each request or
task sees only its own credentials.
"""

import contextlib
import contextvars
from typing import Optional

from googleapiclient.discovery import build

import gsc_server as _gsc

current_credentials: contextvars.ContextVar[Optional[object]] = (
    contextvars.ContextVar("gsc_user_credentials", default=None)
)

# Captured once at import so the patch is idempotent and can defer to the
# original even after apply_patch() has run.
_original_get_gsc_service = _gsc.get_gsc_service


def _patched_get_gsc_service():
    creds = current_credentials.get()
    if creds is not None:
        return build(
            "searchconsole", "v1", credentials=creds, cache_discovery=False
        )
    return _original_get_gsc_service()


def apply_patch() -> None:
    """Install the credential override on the upstream module."""
    _gsc.get_gsc_service = _patched_get_gsc_service


@contextlib.contextmanager
def use_credentials(creds):
    """Bind ``creds`` as the current request's Google credentials."""
    token = current_credentials.set(creds)
    try:
        yield
    finally:
        current_credentials.reset(token)

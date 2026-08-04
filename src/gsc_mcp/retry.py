"""Retry helper for transient Google API errors (spec section 13).

- 400/401/403/404: no retry.
- 429 and 500/502/503/504: up to 3 retries with exponential backoff + jitter.
- Timeout: at most 1 retry.

No retry logic exposes credential paths or token text to callers.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, TypeVar
from random import Random

from .errors import ErrorCode, GscError, map_http_error

logger = logging.getLogger("gsc_mcp.retry")

T = TypeVar("T")

_MAX_RETRIES = 3
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_BASE_DELAY = 0.5  # seconds
_MAX_DELAY = 30.0

# Deterministic jitter source — the workflow runtime forbids Math.random at the
# script level, but this is library code imported normally; a per-call Random
# seeded by a caller-provided value keeps tests reproducible.
_rng = Random()


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter (Decorrelated Jitter variant)."""
    cap = min(_BASE_DELAY * (2 ** attempt), _MAX_DELAY)
    return _rng.uniform(0, cap)


def _http_status_of(exc: Exception) -> int | None:
    """Extract an HTTP status code from a googleapiclient HttpError, if present."""
    # googleapiclient.errors.HttpError carries `.resp.status`.
    resp = getattr(exc, "resp", None)
    if resp is not None:
        status = getattr(resp, "status", None)
        if isinstance(status, int):
            return status
    # Some exceptions wrap the status in a `.status_code` attr.
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def _reason_of(exc: Exception) -> str:
    """Best-effort extraction of the Google API error reason string."""
    content = getattr(exc, "content", None)
    if not content:
        return ""
    try:
        import json
        decoded = content.decode("utf-8") if isinstance(content, (bytes, bytearray)) else content
        payload = json.loads(decoded)
        errors = payload.get("error", {}).get("errors", [])
        if errors:
            return str(errors[0].get("reason", ""))
    except Exception:
        return ""
    return ""


def map_exception(exc: Exception) -> GscError:
    """Map any exception to a GscError (no retry info lost)."""
    if isinstance(exc, GscError):
        return exc
    status = _http_status_of(exc)
    if status is not None:
        return map_http_error(status, str(exc), reason=_reason_of(exc))
    # Timeout or connection error → retryable once.
    name = type(exc).__name__.lower()
    if "timeout" in name or "timed out" in str(exc).lower():
        return GscError(
            ErrorCode.GOOGLE_API_ERROR,
            "Request to Google timed out.",
            retryable=True,
        )
    return GscError(ErrorCode.INTERNAL_ERROR, str(exc), retryable=False)


def call_with_retry(fn: Callable[[], T]) -> T:
    """Call a synchronous Google API method with retry (spec 13).

    `fn` is expected to perform the API call and return its result. Raises a
    GscError on terminal failure.
    """
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — mapped below
            gsc_err = map_exception(exc)
            last_exc = exc
            if not gsc_err.retryable or attempt >= _MAX_RETRIES:
                raise gsc_err from exc
            # Timeout gets a single retry only.
            if "timeout" in gsc_err.message.lower() and attempt >= 1:
                raise gsc_err from exc
            delay = _backoff_seconds(attempt)
            logger.warning(
                "retryable error (attempt %d/%d, code=%s): backing off %.2fs",
                attempt + 1, _MAX_RETRIES + 1, gsc_err.code.value, delay,
            )
            time.sleep(delay)
    # Unreachable, but keeps mypy happy.
    raise GscError(ErrorCode.INTERNAL_ERROR, "Retry loop exhausted.") from last_exc  # type: ignore[arg-type]


async def call_with_retry_async(fn: Callable[[], Awaitable[T]]) -> T:
    """Async variant for use in tool bodies."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            gsc_err = map_exception(exc)
            last_exc = exc
            if not gsc_err.retryable or attempt >= _MAX_RETRIES:
                raise gsc_err from exc
            if "timeout" in gsc_err.message.lower() and attempt >= 1:
                raise gsc_err from exc
            delay = _backoff_seconds(attempt)
            logger.warning(
                "retryable error (attempt %d/%d, code=%s): backing off %.2fs",
                attempt + 1, _MAX_RETRIES + 1, gsc_err.code.value, delay,
            )
            time.sleep(delay)
    raise GscError(ErrorCode.INTERNAL_ERROR, "Retry loop exhausted.") from last_exc  # type: ignore[arg-type]


__all__ = ["call_with_retry", "call_with_retry_async", "map_exception"]

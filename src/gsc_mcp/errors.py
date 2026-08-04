"""Error model and HTTP→code mapping (spec 7.3, section 13).

All tool errors surface as a structured envelope with a stable `code` string
and a `retryable` flag. Raw exceptions containing credential paths or tokens
are never forwarded to tool output.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    PROPERTY_NOT_FOUND = "PROPERTY_NOT_FOUND"
    PROPERTY_NOT_ALLOWED = "PROPERTY_NOT_ALLOWED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
    GOOGLE_RATE_LIMITED = "GOOGLE_RATE_LIMITED"
    GOOGLE_API_ERROR = "GOOGLE_API_ERROR"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    NO_DATA = "NO_DATA"
    PARTIAL_DATA = "PARTIAL_DATA"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class GscError(Exception):
    """Domain error carrying a stable ErrorCode and retryability hint."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        self.http_status = http_status


def _is_sensitive(text: str) -> bool:
    """Heuristic: avoid forwarding exception text that may carry a credential path."""
    if not text:
        return False
    lowered = text.lower()
    markers = ("client_secret", "service_account", "token.json", "credentials.json", ".json")
    return any(m in lowered for m in markers) and ("path" in lowered or "file" in lowered or "not found" in lowered)


def map_http_error(status: int, message: str = "", *, reason: str = "") -> GscError:
    """Map a Google API HTTP status to a GscError (spec section 13).

    400 → INVALID_ARGUMENT (no retry)
    401 → AUTH_EXPIRED (no retry)
    403 → QUOTA_EXCEEDED if quota reason, else PROPERTY_NOT_ALLOWED/permission
    404 → PROPERTY_NOT_FOUND
    429 → GOOGLE_RATE_LIMITED (retryable)
    5xx → GOOGLE_API_ERROR (retryable)
    timeout → GOOGLE_API_ERROR (retryable, single retry max)
    """
    if status == 400:
        return GscError(ErrorCode.INVALID_ARGUMENT, message or "Invalid argument.", retryable=False, http_status=400)
    if status == 401:
        return GscError(ErrorCode.AUTH_EXPIRED, message or "Authentication expired.", retryable=False, http_status=401)
    if status == 403:
        if reason and "quota" in reason.lower():
            return GscError(ErrorCode.QUOTA_EXCEEDED, message or "API quota exceeded.", retryable=True, http_status=403)
        return GscError(
            ErrorCode.PROPERTY_NOT_ALLOWED,
            message or "Permission denied for this property.",
            retryable=False, http_status=403,
        )
    if status == 404:
        return GscError(
            ErrorCode.PROPERTY_NOT_FOUND,
            message or "Property not found. Verify the site_url exactly matches GSC.",
            retryable=False, http_status=404,
        )
    if status == 429:
        return GscError(
            ErrorCode.GOOGLE_RATE_LIMITED,
            message or "Rate limited by Google API. Retry with backoff.",
            retryable=True, http_status=429,
        )
    if status >= 500:
        return GscError(
            ErrorCode.GOOGLE_API_ERROR,
            message or f"Google API error (HTTP {status}).",
            retryable=True, http_status=status,
        )
    return GscError(
        ErrorCode.GOOGLE_API_ERROR,
        message or f"Google API error (HTTP {status}).",
        retryable=False, http_status=status,
    )


def sanitize_exception_text(text: str) -> str:
    """Strip potential credential-path leakage from raw exception text."""
    if _is_sensitive(text):
        return "An internal error occurred. See server logs for details."
    return text


__all__ = ["ErrorCode", "GscError", "map_http_error", "sanitize_exception_text"]

"""Common response envelope (spec 7.2, 7.3).

Every tool returns a JSON string conforming to this envelope so the AI agent
can rely on a stable shape for parsing success vs. error. Errors are also
flagged at the MCP level via `isError=true` (the MCP SDK surfaces this when a
tool raises; here we return a structured string AND raise for the SDK to mark
the call as failed).
"""
from __future__ import annotations

import json
from typing import Any

from .errors import ErrorCode, GscError, sanitize_exception_text


def build_ok(meta: dict[str, Any], data: Any) -> str:
    """Build a success envelope.

    `meta` must include: client_id, client_name, site_url, date_range
    {start, end, timezone}, search_type, data_state, data_may_be_incomplete,
    first_incomplete_date, response_aggregation_type, rows_examined, warnings.
    `data` is the tool-specific payload.
    """
    envelope = {
        "ok": True,
        "meta": meta,
        "data": data,
    }
    return json.dumps(envelope, default=str, ensure_ascii=False)


def build_error(
    code: ErrorCode | str,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> str:
    """Build an error envelope (spec 7.3)."""
    envelope = {
        "ok": False,
        "error": {
            "code": code.value if isinstance(code, ErrorCode) else str(code),
            "message": message,
            "retryable": bool(retryable),
            "details": details or {},
        },
    }
    return json.dumps(envelope, default=str, ensure_ascii=False)


def error_from_gsc_error(err: GscError) -> str:
    """Convenience: build an error envelope from a GscError."""
    return build_error(
        err.code, err.message, retryable=err.retryable, details=err.details,
    )


def error_from_exception(exc: Exception) -> str:
    """Build an error envelope from an arbitrary exception.

    Credential-path / token leakage is sanitized out (spec 13: no raw exception
    carrying sensitive info reaches tool output).
    """
    if isinstance(exc, GscError):
        return error_from_gsc_error(exc)
    return build_error(
        ErrorCode.INTERNAL_ERROR,
        sanitize_exception_text(str(exc)),
        retryable=False,
    )


# Meta builder used by all analytics tools for consistency.
def build_meta(
    *,
    site_url: str,
    date_range: dict[str, Any],
    search_type: str = "web",
    data_state: str = "final",
    data_may_be_incomplete: bool = False,
    first_incomplete_date: str | None = None,
    response_aggregation_type: str = "auto",
    rows_examined: int = 0,
    warnings: list[str] | None = None,
    client_id: str | None = None,
    client_name: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the standard `meta` block for a success envelope (spec 7.2)."""
    meta: dict[str, Any] = {
        "client_id": client_id,
        "client_name": client_name,
        "site_url": site_url,
        "date_range": date_range,
        "search_type": search_type,
        "data_state": data_state,
        "data_may_be_incomplete": data_may_be_incomplete,
        "first_incomplete_date": first_incomplete_date,
        "response_aggregation_type": response_aggregation_type,
        "rows_examined": rows_examined,
        "warnings": warnings or [],
    }
    if extra:
        meta.update(extra)
    return meta


__all__ = [
    "build_ok", "build_error", "error_from_gsc_error", "error_from_exception",
    "build_meta",
]

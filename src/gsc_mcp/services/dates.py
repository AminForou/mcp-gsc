"""Date math for Search Analytics (spec 4.8).

All default date math uses America/Los_Angeles (Pacific Time). Ranges are
inclusive: a 28-day window is start = end - 27 days. The strategic-report
default is data_state=final with end = current_PT - 3 days.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .. import config


def _pt_today() -> date:
    """Return today's date in Pacific Time."""
    return datetime.now(config.GSC_TIMEZONE).date()


def default_end_date(data_state: str | None = None) -> date:
    """Strategic default end date (spec 4.8).

    For `final` (default): current_PT - 3 days (data confirmed).
    For `all`: current_PT (matches dashboard, may be incomplete).
    """
    state = (data_state or config.DEFAULT_DATA_STATE).lower()
    today = _pt_today()
    if state == "final":
        return today - timedelta(days=config.DEFAULT_REPORT_LAG_DAYS)
    return today


def default_start_date(
    days: int = config.DEFAULT_REPORT_WINDOW_DAYS,
    end: date | None = None,
) -> date:
    """Inclusive start = end - (days - 1). For a 28-day window, subtract 27."""
    anchor = end or default_end_date()
    return anchor - timedelta(days=days - 1)


def parse_date(s: str, *, label: str = "date") -> date:
    """Parse a YYYY-MM-DD string; raises ValueError on bad input."""
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} {s!r}. Use YYYY-MM-DD.") from exc


def validate_range(start: date, end: date) -> None:
    """Enforce start <= end and no future dates (spec 8.3)."""
    if start > end:
        raise ValueError(f"start_date {start.isoformat()} is after end_date {end.isoformat()}.")
    today = _pt_today()
    if end > today:
        raise ValueError(f"end_date {end.isoformat()} is in the future (today PT: {today.isoformat()}).")


def first_incomplete_date_for_all(end: date) -> str | None:
    """For data_state=all, the last few days may be incomplete (spec 4.8)."""
    today = _pt_today()
    lag = (today - end).days
    if lag < config.DEFAULT_REPORT_LAG_DAYS:
        # Anything within the 3-day freshness window is potentially incomplete.
        return (today - timedelta(days=config.DEFAULT_REPORT_LAG_DAYS - 1)).isoformat()
    return None


def previous_range(start: date, end: date) -> tuple[date, date]:
    """Return the prior period of the same length (inclusive)."""
    length_days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length_days - 1)
    return prev_start, prev_end


__all__ = [
    "default_end_date", "default_start_date", "parse_date", "validate_range",
    "first_incomplete_date_for_all", "previous_range", "_pt_today",
]

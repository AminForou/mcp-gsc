"""Search Analytics service (spec 4.4, 4.5, 4.6, 8.3, 8.4, 8.5).

Holds the shared core for querying Google's Search Analytics API, computing
deltas, and comparing periods. Enforces:
- NO `orderBy` in the request body (sort is client-side; spec 4.4).
- The request field is `type` not `searchType` (spec 4.5).
- Delta math per spec 4.6 (positive delta = growth; positive
  position_improvement = rank got better).
- Pagination per spec 8.3 with the constant "top rows" warning.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import config
from ..errors import ErrorCode, GscError
from ..models.analytics import (
    BreakdownEntry, Change, ComparisonRow, DailyTrend, Metrics,
    PerformancePrevious, PerformanceTotals, SearchAnalyticsRow,
)
from ..models.common import Filter, Pagination
from ..retry import call_with_retry

logger = logging.getLogger("gsc_mcp.search_analytics")

_DIMENSION_SET_ORDER = ("query", "page", "country", "device", "date", "hour", "searchAppearance")


def _build_dimension_filter_groups(filters: list[Filter] | None) -> list[dict[str, Any]]:
    if not filters:
        return []
    return [{
        "groupType": "and",
        "filters": [f.model_dump() for f in filters],
    }]


def _validate_dimensions(dimensions: list[str]) -> list[str]:
    cleaned: list[str] = []
    for d in dimensions:
        d = d.strip()
        if d not in config.VALID_DIMENSIONS:
            raise GscError(
                ErrorCode.INVALID_ARGUMENT,
                f"Invalid dimension {d!r}. Valid: {config.VALID_DIMENSIONS}.",
                retryable=False,
            )
        cleaned.append(d)
    return cleaned


def _validate_page_size(page_size: int) -> int:
    if page_size < 1:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            "page_size must be >= 1.",
            retryable=False,
        )
    if page_size > config.MAX_PAGE_SIZE:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"page_size must be <= {config.MAX_PAGE_SIZE}.",
            retryable=False,
        )
    return page_size


def _validate_start_row(start_row: int) -> int:
    if start_row < 0:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            "start_row must be >= 0.",
            retryable=False,
        )
    return start_row


def _validate_search_type(search_type: str) -> str:
    st = (search_type or "web").strip().lower()
    if st not in config.VALID_SEARCH_TYPES:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"Invalid search_type {search_type!r}. Valid: {config.VALID_SEARCH_TYPES}.",
            retryable=False,
        )
    return st


def _build_request_body(
    *,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    search_type: str,
    data_state: str,
    page_size: int,
    start_row: int,
    filters: list[Filter] | None,
) -> dict[str, Any]:
    """Build the request body (spec 8.3 contract).

    NOTE: NO `orderBy`. NO `searchType`. Uses `type` (spec 4.4/4.5).
    """
    body: dict[str, Any] = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "type": search_type,  # NOT searchType
        "dataState": data_state,
        "rowLimit": page_size,
        "startRow": start_row,
        "dimensionFilterGroups": _build_dimension_filter_groups(filters),
    }
    return body


def _map_rows(response: dict[str, Any], dimensions: list[str]) -> list[SearchAnalyticsRow]:
    rows: list[SearchAnalyticsRow] = []
    for raw in response.get("rows", []) or []:
        keys_list = raw.get("keys", []) or []
        keys: dict[str, str] = {}
        for i, dim in enumerate(dimensions):
            if i < len(keys_list):
                keys[dim] = keys_list[i]
        rows.append(SearchAnalyticsRow(
            keys=keys,
            clicks=int(raw.get("clicks", 0) or 0),
            impressions=int(raw.get("impressions", 0) or 0),
            ctr=round(float(raw.get("ctr", 0) or 0.0), 4),
            position=round(float(raw.get("position", 0) or 0.0), 1),
        ))
    return rows


def _sort_rows(
    rows: list[SearchAnalyticsRow],
    *,
    sort_by: str | None,
    sort_direction: str,
) -> list[SearchAnalyticsRow]:
    """Client-side sort (spec 4.4: orderBy never sent to Google)."""
    if not sort_by:
        return rows
    metric_map = {
        "clicks": lambda r: r.clicks,
        "impressions": lambda r: r.impressions,
        "ctr": lambda r: r.ctr,
        "position": lambda r: r.position,
    }
    if sort_by not in metric_map:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"Invalid sort_by {sort_by!r}. Valid: clicks, impressions, ctr, position.",
            retryable=False,
        )
    reverse = (sort_direction or "descending").lower() == "descending"
    # For position, "descending" is ambiguous; we treat it literally per user input.
    return sorted(rows, key=metric_map[sort_by], reverse=reverse)


def query_search_analytics(
    service: Any,
    *,
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    search_type: str = "web",
    data_state: str | None = None,
    page_size: int = config.DEFAULT_PAGE_SIZE,
    start_row: int = 0,
    sort_by: str | None = None,
    sort_direction: str = "descending",
    filters: list[Filter] | None = None,
    row_limit_override: int | None = None,
) -> tuple[list[SearchAnalyticsRow], Pagination, bool]:
    """Core query with validation + client-side sort.

    Returns (rows, pagination, data_may_be_incomplete).
    """
    dimensions = _validate_dimensions(dimensions)
    page_size = _validate_page_size(page_size)
    start_row = _validate_start_row(start_row)
    st = _validate_search_type(search_type)
    state = (data_state or config.DEFAULT_DATA_STATE).lower()
    if state not in ("all", "final"):
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"Invalid data_state {data_state!r}. Use 'all' or 'final'.",
            retryable=False,
        )

    effective_limit = row_limit_override or page_size
    body = _build_request_body(
        start_date=start_date, end_date=end_date, dimensions=dimensions,
        search_type=st, data_state=state, page_size=effective_limit,
        start_row=start_row, filters=filters,
    )

    logger.debug("search analytics request: %s", {k: v for k, v in body.items() if k != "dimensionFilterGroups"})

    response = call_with_retry(lambda: service.searchanalytics().query(siteUrl=site_url, body=body).execute())

    rows = _map_rows(response, dimensions)
    rows = _sort_rows(rows, sort_by=sort_by, sort_direction=sort_direction)

    returned = len(rows)
    # `has_more` heuristic: API returned as many rows as we asked for.
    has_more = returned >= effective_limit and returned > 0
    pagination = Pagination(
        start_row=start_row, page_size=page_size, returned_rows=returned,
        has_more=has_more, next_start_row=(start_row + effective_limit) if has_more else None,
    )
    data_may_be_incomplete = state == "all"
    return rows, pagination, data_may_be_incomplete


def get_totals(
    service: Any, *, site_url: str, start_date: str, end_date: str,
    search_type: str = "web", data_state: str | None = None,
    filters: list[Filter] | None = None,
) -> PerformanceTotals:
    """Totals from a dimensionless query (spec 8.4: NOT summed daily)."""
    body = _build_request_body(
        start_date=start_date, end_date=end_date, dimensions=[],
        search_type=_validate_search_type(search_type),
        data_state=(data_state or config.DEFAULT_DATA_STATE).lower(),
        page_size=1, start_row=0, filters=filters,
    )
    response = call_with_retry(lambda: service.searchanalytics().query(siteUrl=site_url, body=body).execute())
    rows = response.get("rows", []) or []
    if not rows:
        return PerformanceTotals()
    r = rows[0]
    return PerformanceTotals(
        clicks=int(r.get("clicks", 0) or 0),
        impressions=int(r.get("impressions", 0) or 0),
        ctr=round(float(r.get("ctr", 0) or 0.0), 4),
        position=round(float(r.get("position", 0) or 0.0), 1),
    )


def get_breakdown(
    service: Any, *, site_url: str, start_date: str, end_date: str,
    dimension: str, search_type: str = "web", data_state: str | None = None,
    filters: list[Filter] | None = None, limit: int = 50,
) -> list[BreakdownEntry]:
    """Breakdown by a single dimension (device/country/searchAppearance/date)."""
    if dimension not in config.VALID_DIMENSIONS:
        raise GscError(ErrorCode.INVALID_ARGUMENT, f"Invalid dimension {dimension!r}.", retryable=False)
    body = _build_request_body(
        start_date=start_date, end_date=end_date, dimensions=[dimension],
        search_type=_validate_search_type(search_type),
        data_state=(data_state or config.DEFAULT_DATA_STATE).lower(),
        page_size=min(max(limit, 1), 1000), start_row=0, filters=filters,
    )
    response = call_with_retry(lambda: service.searchanalytics().query(siteUrl=site_url, body=body).execute())
    out: list[BreakdownEntry] = []
    for r in response.get("rows", []) or []:
        keys = r.get("keys", []) or []
        out.append(BreakdownEntry(
            key=keys[0] if keys else "",
            clicks=int(r.get("clicks", 0) or 0),
            impressions=int(r.get("impressions", 0) or 0),
            ctr=round(float(r.get("ctr", 0) or 0.0), 4),
            position=round(float(r.get("position", 0) or 0.0), 1),
        ))
    return out


def compute_change(current: Metrics, previous: Metrics) -> Change:
    """Delta block per spec 4.6.

    - delta = current - previous (positive = growth for clicks/impressions)
    - percent_change = (current - previous) / previous * 100; null when previous=0
    - position_improvement = previous.position - current.position (positive = better)
    - status: 'new' when previous all-zero; 'lost' when current zero & previous>0
    """
    def _pct(cur: float, prev: float) -> float | None:
        if prev == 0:
            return None
        return round((cur - prev) / prev * 100, 1)

    clicks_pct = _pct(float(current.clicks), float(previous.clicks))
    imp_pct = _pct(float(current.impressions), float(previous.impressions))
    pos_imp = round(float(previous.position) - float(current.position), 1) if (previous.position or current.position) else None

    prev_nonzero = previous.clicks > 0 or previous.impressions > 0
    cur_zero = current.clicks == 0 and current.impressions == 0
    status = "changed"
    if not prev_nonzero:
        status = "new"
    elif cur_zero and prev_nonzero:
        status = "lost"

    return Change(
        clicks=current.clicks - previous.clicks,
        clicks_percent=clicks_pct,
        impressions=current.impressions - previous.impressions,
        impressions_percent=imp_pct,
        ctr_points=round(float(current.ctr) - float(previous.ctr), 4),
        position_improvement=pos_imp,
        status=status,
    )


def compare_periods(
    service: Any,
    *,
    site_url: str,
    current_start: str, current_end: str,
    previous_start: str, previous_end: str,
    dimensions: list[str],
    search_type: str = "web",
    data_state: str | None = None,
    filters: list[Filter] | None = None,
    limit: int = 500,
) -> list[ComparisonRow]:
    """Fetch both periods, join on keys, compute Change (spec 8.5)."""
    dimensions = _validate_dimensions(dimensions)
    st = _validate_search_type(search_type)
    state = (data_state or config.DEFAULT_DATA_STATE).lower()
    if limit < 1 or limit > 500:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "limit must be between 1 and 500.", retryable=False)

    def _fetch(s: str, e: str) -> list[SearchAnalyticsRow]:
        body = _build_request_body(
            start_date=s, end_date=e, dimensions=dimensions, search_type=st,
            data_state=state, page_size=min(limit, config.MAX_PAGE_SIZE),
            start_row=0, filters=filters,
        )
        resp = call_with_retry(lambda: service.searchanalytics().query(siteUrl=site_url, body=body).execute())
        return _map_rows(resp, dimensions)

    cur_rows = _fetch(current_start, current_end)
    prev_rows = _fetch(previous_start, previous_end)

    prev_by_key: dict[tuple[str, ...], SearchAnalyticsRow] = {
        tuple(r.keys.get(d, "") for d in dimensions): r for r in prev_rows
    }
    cur_by_key: dict[tuple[str, ...], SearchAnalyticsRow] = {
        tuple(r.keys.get(d, "") for d in dimensions): r for r in cur_rows
    }

    all_keys = set(prev_by_key.keys()) | set(cur_by_key.keys())
    out: list[ComparisonRow] = []
    for key in all_keys:
        c = cur_by_key.get(key)
        p = prev_by_key.get(key)
        if c is None:
            # Existed before, gone now → "lost".
            p_m = Metrics(clicks=p.clicks, impressions=p.impressions, ctr=p.ctr, position=p.position)  # type: ignore[union-attr]
            ch = compute_change(Metrics(), p_m)
            keys_dict = {d: p.keys.get(d, "") for d in dimensions} if p else {}  # type: ignore[union-attr]
            out.append(ComparisonRow(keys=keys_dict, current=Metrics(), previous=p_m, change=ch))
            continue
        if p is None:
            c_m = Metrics(clicks=c.clicks, impressions=c.impressions, ctr=c.ctr, position=c.position)
            ch = compute_change(c_m, Metrics())
            out.append(ComparisonRow(
                keys={d: c.keys.get(d, "") for d in dimensions},
                current=c_m, previous=Metrics(), change=ch,
            ))
            continue
        c_m = Metrics(clicks=c.clicks, impressions=c.impressions, ctr=c.ctr, position=c.position)
        p_m = Metrics(clicks=p.clicks, impressions=p.impressions, ctr=p.ctr, position=p.position)
        ch = compute_change(c_m, p_m)
        out.append(ComparisonRow(
            keys={d: c.keys.get(d, "") for d in dimensions},
            current=c_m, previous=p_m, change=ch,
        ))

    # Sort by absolute click change (biggest movers first).
    out.sort(key=lambda r: abs(r.change.clicks), reverse=True)
    return out[:limit]


__all__ = [
    "query_search_analytics", "get_totals", "get_breakdown", "compute_change",
    "compare_periods",
]

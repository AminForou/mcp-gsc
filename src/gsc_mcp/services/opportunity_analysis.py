"""Opportunity analysis service (spec 8.7, 8.8, 8.9).

Implements:
- gsc_find_opportunities: striking_distance, high_impression_low_ctr,
  position_one_page_two, zero_click. CTR baseline is configurable and its
  version is surfaced in output (spec 8.7 — no unsourced numbers as hard truth).
- gsc_find_content_decay: pages/queries that declined vs prior same-length period.
- gsc_find_cannibalization: queries where multiple pages split traffic; results
  are labeled "possible cannibalization", never proof (spec 8.9, section 19).
"""
from __future__ import annotations

import logging
from typing import Any

from .. import config
from ..errors import ErrorCode, GscError
from ..models.analytics import SearchAnalyticsRow
from ..models.common import Filter
from ..retry import call_with_retry
from .search_analytics import _build_request_body, _map_rows, _validate_dimensions

logger = logging.getLogger("gsc_mcp.opportunity_analysis")


def _fetch_rows(
    service: Any, *, site_url: str, start_date: str, end_date: str,
    dimensions: list[str], search_type: str, data_state: str,
    filters: list[Filter] | None, limit: int,
) -> list[SearchAnalyticsRow]:
    body = _build_request_body(
        start_date=start_date, end_date=end_date, dimensions=dimensions,
        search_type=search_type, data_state=data_state, page_size=limit,
        start_row=0, filters=filters,
    )
    resp = call_with_retry(lambda: service.searchanalytics().query(siteUrl=site_url, body=body).execute())
    return _map_rows(resp, dimensions)


def find_opportunities(
    service: Any,
    *,
    site_url: str,
    start_date: str,
    end_date: str,
    opportunity_types: list[str],
    min_impressions: int = 100,
    max_rows_to_scan: int = 10000,
    limit: int = 100,
    search_type: str = "web",
    data_state: str | None = None,
    ctr_baseline: dict[int, float] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Spec 8.7. Returns (opportunities, meta_with_baseline_version)."""
    valid_types = {
        "striking_distance", "high_impression_low_ctr",
        "position_one_page_two", "zero_click",
    }
    for t in opportunity_types:
        if t not in valid_types:
            raise GscError(
                ErrorCode.INVALID_ARGUMENT,
                f"Invalid opportunity_type {t!r}. Valid: {sorted(valid_types)}.",
                retryable=False,
            )
    if min_impressions < 0:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "min_impressions must be >= 0.", retryable=False)
    if limit < 1 or limit > 500:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "limit must be 1..500.", retryable=False)
    if max_rows_to_scan < 1 or max_rows_to_scan > config.MAX_ANALYSIS_ROWS:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"max_rows_to_scan must be 1..{config.MAX_ANALYSIS_ROWS}.",
            retryable=False,
        )

    rows = _fetch_rows(
        service, site_url=site_url, start_date=start_date, end_date=end_date,
        dimensions=["query", "page"], search_type=search_type,
        data_state=(data_state or config.DEFAULT_DATA_STATE).lower(),
        filters=None, limit=min(max_rows_to_scan, config.MAX_PAGE_SIZE),
    )

    results: list[dict[str, Any]] = []
    baseline_used = ctr_baseline or config.CTR_BASELINE

    for r in rows:
        if r.impressions < min_impressions:
            continue
        pos = r.position
        matched: list[str] = []

        if "striking_distance" in opportunity_types and 4 <= pos <= 15 and r.impressions >= min_impressions:
            matched.append("striking_distance")
        if "high_impression_low_ctr" in opportunity_types and 1 <= pos <= 10:
            expected = config.expected_ctr_for_position(pos, baseline_used)
            if r.ctr < expected:
                matched.append("high_impression_low_ctr")
        if "position_one_page_two" in opportunity_types and 8 <= pos <= 20 and r.impressions >= min_impressions:
            matched.append("position_one_page_two")
        if "zero_click" in opportunity_types and r.clicks == 0 and r.impressions >= min_impressions:
            matched.append("zero_click")

        if not matched:
            continue
        results.append({
            "query": r.keys.get("query", ""),
            "page": r.keys.get("page", ""),
            "clicks": r.clicks,
            "impressions": r.impressions,
            "ctr": r.ctr,
            "position": r.position,
            "opportunity_types": matched,
        })
        if len(results) >= limit:
            break

    meta = {
        "ctr_baseline_version": config.CTR_BASELINE_VERSION,
        "ctr_baseline_overridden": ctr_baseline is not None,
    }
    return results, meta


def find_content_decay(
    service: Any,
    *,
    site_url: str,
    current_start: str, current_end: str,
    previous_start: str, previous_end: str,
    search_type: str = "web",
    data_state: str | None = None,
    min_previous_clicks: int = 10,
    decline_threshold_pct: float = 20.0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Spec 8.8: pages/queries that declined vs prior same-length period.

    Entry rules:
    - previous_clicks >= min_previous_clicks
    - clicks_percent <= -decline_threshold_pct OR impressions_percent <= -decline_threshold_pct
    - results sorted by impact score.
    """
    if limit < 1 or limit > 500:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "limit must be 1..500.", retryable=False)
    state = (data_state or config.DEFAULT_DATA_STATE).lower()
    st = (search_type or "web").lower()
    if st not in config.VALID_SEARCH_TYPES:
        raise GscError(ErrorCode.INVALID_ARGUMENT, f"Invalid search_type {search_type!r}.", retryable=False)

    dimensions = ["query", "page"]

    def _fetch(s: str, e: str) -> list[SearchAnalyticsRow]:
        return _fetch_rows(
            service, site_url=site_url, start_date=s, end_date=e,
            dimensions=dimensions, search_type=st, data_state=state,
            filters=None, limit=config.MAX_PAGE_SIZE,
        )

    cur_rows = _fetch(current_start, current_end)
    prev_rows = _fetch(previous_start, previous_end)

    prev_by_key = {tuple(r.keys.get(d, "") for d in dimensions): r for r in prev_rows}
    cur_by_key = {tuple(r.keys.get(d, "") for d in dimensions): r for r in cur_rows}

    results: list[dict[str, Any]] = []
    for key, prev in prev_by_key.items():
        if prev.clicks < min_previous_clicks:
            continue
        cur = cur_by_key.get(key)
        cur_clicks = cur.clicks if cur else 0
        cur_imp = cur.impressions if cur else 0

        clicks_pct = (
            round((cur_clicks - prev.clicks) / prev.clicks * 100, 1) if prev.clicks > 0 else None
        )
        imp_pct = (
            round((cur_imp - prev.impressions) / prev.impressions * 100, 1) if prev.impressions > 0 else None
        )

        signals: list[str] = []
        if clicks_pct is not None and clicks_pct <= -decline_threshold_pct:
            signals.append("clicks_declined")
        if imp_pct is not None and imp_pct <= -decline_threshold_pct:
            signals.append("impressions_declined")
        if not signals:
            continue

        lost_clicks = max(prev.clicks - cur_clicks, 0)
        lost_impressions = max(prev.impressions - cur_imp, 0)
        prev_ctr = prev.ctr
        impact_score = round(lost_clicks + lost_impressions * prev_ctr, 2)

        results.append({
            "query": prev.keys.get("query", ""),
            "page": prev.keys.get("page", ""),
            "current_clicks": cur_clicks,
            "previous_clicks": prev.clicks,
            "clicks_percent": clicks_pct,
            "current_impressions": cur_imp,
            "previous_impressions": prev.impressions,
            "impressions_percent": imp_pct,
            "impact_score": impact_score,
            "signals": signals,
        })

    results.sort(key=lambda r: r["impact_score"], reverse=True)
    return results[:limit]


def find_cannibalization(
    service: Any,
    *,
    site_url: str,
    start_date: str,
    end_date: str,
    search_type: str = "web",
    data_state: str | None = None,
    min_query_impressions: int = 100,
    dominant_share_threshold: float = 0.90,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Spec 8.9: queries where multiple pages split traffic.

    Rules:
    - drop blank/anonymous queries
    - require >= 2 distinct pages per query
    - min_query_impressions default 100
    - if one page > dominant_share_threshold of impressions, severity=low or dropped
    - results are labeled "possible cannibalization" (not proof)
    """
    if limit < 1 or limit > 500:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "limit must be 1..500.", retryable=False)
    rows = _fetch_rows(
        service, site_url=site_url, start_date=start_date, end_date=end_date,
        dimensions=["query", "page"], search_type=(search_type or "web").lower(),
        data_state=(data_state or config.DEFAULT_DATA_STATE).lower(),
        filters=None, limit=config.MAX_PAGE_SIZE,
    )

    # Group by query.
    by_query: dict[str, list[SearchAnalyticsRow]] = {}
    for r in rows:
        q = (r.keys.get("query") or "").strip()
        if not q:
            continue
        by_query.setdefault(q, []).append(r)

    results: list[dict[str, Any]] = []
    for q, group in by_query.items():
        total_imp = sum(r.impressions for r in group)
        if total_imp < min_query_impressions:
            continue
        if len(group) < 2:
            continue
        pages = []
        for r in group:
            share = r.impressions / total_imp if total_imp > 0 else 0.0
            pages.append({
                "page": r.keys.get("page", ""),
                "impressions": r.impressions,
                "share": round(share, 3),
                "position": r.position,
            })
        pages.sort(key=lambda p: p["impressions"], reverse=True)

        top_share = pages[0]["share"] if pages else 0.0
        severity = "low" if top_share > dominant_share_threshold else (
            "high" if len(pages) >= 3 or top_share < 0.6 else "medium"
        )
        signals: list[str] = ["traffic_split"]
        # Close positions across pages is another signal.
        positions = [p["position"] for p in pages if p["position"] > 0]
        if positions and (max(positions) - min(positions)) <= 5:
            signals.append("close_positions")

        results.append({
            "query": q,
            "total_impressions": total_imp,
            "pages": pages,
            "severity": severity,
            "signals": signals,
            "note": "Possible cannibalization — multiple URLs do not prove it.",
        })
        if len(results) >= limit:
            break

    results.sort(key=lambda r: r["total_impressions"], reverse=True)
    return results


__all__ = ["find_opportunities", "find_content_decay", "find_cannibalization"]

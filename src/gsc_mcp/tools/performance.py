"""Performance tools (spec 8.3, 8.4, 8.5, 8.6)."""
from __future__ import annotations

import logging
from typing import Any

from .. import auth, config
from ..envelope import build_meta, build_ok, error_from_exception
from ..errors import ErrorCode, GscError
from ..models.common import Filter
from ..registry import assert_property_allowed
from ..server import mcp
from ..services import dates
from ..services.search_analytics import (
    compare_periods as compare_periods_svc,
    get_breakdown, get_totals, query_search_analytics,
)

logger = logging.getLogger("gsc_mcp.tools.performance")


def _client_meta_for(site_url: str) -> dict[str, Any]:
    """Resolve the owning client for a property (raises PROPERTY_NOT_ALLOWED)."""
    client = assert_property_allowed(site_url)
    return {"client_id": client.id if client else None,
            "client_name": client.name if client else None}


def _coerce_filters(filters: list[dict[str, Any]] | None) -> list[Filter] | None:
    if not filters:
        return None
    return [Filter(**f) for f in filters]


@mcp.tool()
async def gsc_query_search_analytics(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    search_type: str = "web",
    aggregation_type: str = "auto",
    data_state: str | None = None,
    page_size: int = 500,
    start_row: int = 0,
    sort_by: str | None = None,
    sort_direction: str = "descending",
) -> str:
    """General search analytics query (spec 8.3). Source of raw GSC data.

    Pagination output includes has_more/next_start_row. Output always carries the
    constant warning that Google may return top rows rather than every row.
    """
    try:
        client = _client_meta_for(site_url)
        service = auth.get_gsc_service()

        end_d = dates.parse_date(end_date) if end_date else dates.default_end_date(data_state)
        start_d = dates.parse_date(start_date) if start_date else dates.default_start_date(end=end_d)
        dates.validate_range(start_d, end_d)

        dims = dimensions or ["query"]
        filter_objs = _coerce_filters(filters)

        state = (data_state or config.DEFAULT_DATA_STATE).lower()
        rows, pagination, may_be_incomplete = query_search_analytics(
            service,
            site_url=site_url, start_date=start_d.isoformat(), end_date=end_d.isoformat(),
            dimensions=dims, search_type=search_type, data_state=state,
            page_size=page_size, start_row=start_row,
            sort_by=sort_by, sort_direction=sort_direction,
            filters=filter_objs,
        )

        warnings = [config.GSC_TOP_ROWS_WARNING]
        first_inc = dates.first_incomplete_date_for_all(end_d) if state == "all" else None

        meta = build_meta(
            site_url=site_url,
            date_range={"start": start_d.isoformat(), "end": end_d.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state,
            data_may_be_incomplete=may_be_incomplete, first_incomplete_date=first_inc,
            response_aggregation_type=aggregation_type, rows_examined=len(rows),
            warnings=warnings, client_id=client["client_id"],
            client_name=client["client_name"],
            extra={"sort_applied_locally": bool(sort_by), "pagination": pagination.model_dump()},
        )
        return build_ok(meta, {
            "rows": [r.model_dump() for r in rows],
        })
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_get_performance_overview(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 28,
    compare_previous: bool = True,
    search_type: str = "web",
    data_state: str | None = None,
) -> str:
    """High-level performance summary for a period (spec 8.4).

    Totals come from a dimensionless query (NOT summed from daily rows).
    Includes device/country/searchAppearance breakdowns and a daily trend.
    """
    try:
        client = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        state = (data_state or config.DEFAULT_DATA_STATE).lower()

        end_d = dates.parse_date(end_date) if end_date else dates.default_end_date(state)
        if start_date:
            start_d = dates.parse_date(start_date)
        else:
            start_d = dates.default_start_date(days=days, end=end_d)
        dates.validate_range(start_d, end_d)

        totals = get_totals(service, site_url=site_url, start_date=start_d.isoformat(),
                            end_date=end_d.isoformat(), search_type=search_type,
                            data_state=state)

        prev_totals = None
        if compare_previous:
            prev_start, prev_end = dates.previous_range(start_d, end_d)
            prev_totals = get_totals(service, site_url=site_url,
                                     start_date=prev_start.isoformat(),
                                     end_date=prev_end.isoformat(),
                                     search_type=search_type, data_state=state)

        # Daily trend via date dimension.
        daily = get_breakdown(service, site_url=site_url,
                              start_date=start_d.isoformat(), end_date=end_d.isoformat(),
                              dimension="date", search_type=search_type,
                              data_state=state, limit=days)
        device = get_breakdown(service, site_url=site_url,
                               start_date=start_d.isoformat(), end_date=end_d.isoformat(),
                               dimension="device", search_type=search_type, data_state=state)
        country = get_breakdown(service, site_url=site_url,
                                start_date=start_d.isoformat(), end_date=end_d.isoformat(),
                                dimension="country", search_type=search_type, data_state=state)
        appearance = get_breakdown(service, site_url=site_url,
                                   start_date=start_d.isoformat(), end_date=end_d.isoformat(),
                                   dimension="searchAppearance", search_type=search_type, data_state=state)

        first_inc = dates.first_incomplete_date_for_all(end_d) if state == "all" else None
        meta = build_meta(
            site_url=site_url,
            date_range={"start": start_d.isoformat(), "end": end_d.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state,
            data_may_be_incomplete=(state == "all"), first_incomplete_date=first_inc,
            response_aggregation_type="byProperty", rows_examined=len(daily),
            client_id=client["client_id"], client_name=client["client_name"],
        )
        data = {
            "totals": totals.model_dump(),
            "previous_totals": prev_totals.model_dump() if prev_totals else None,
            "daily_trend": [d.model_dump() for d in daily],
            "device_breakdown": [d.model_dump() for d in device],
            "country_breakdown": [d.model_dump() for d in country],
            "search_appearance_breakdown": [d.model_dump() for d in appearance],
        }
        return build_ok(meta, data)
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_compare_periods(
    site_url: str,
    current_start: str,
    current_end: str,
    previous_start: str,
    previous_end: str,
    dimensions: list[str] | None = None,
    filters: list[dict[str, Any]] | None = None,
    sort_by: str = "clicks",
    limit: int = 500,
    search_type: str = "web",
    data_state: str | None = None,
) -> str:
    """Compare two explicit periods (spec 8.5). Returns per-key current/previous
    metrics and a change block (delta, percent, position_improvement, status).
    """
    try:
        client = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        dims = dimensions or ["query"]
        filter_objs = _coerce_filters(filters)
        state = (data_state or config.DEFAULT_DATA_STATE).lower()

        cs = dates.parse_date(current_start, label="current_start")
        ce = dates.parse_date(current_end, label="current_end")
        ps = dates.parse_date(previous_start, label="previous_start")
        pe = dates.parse_date(previous_end, label="previous_end")
        dates.validate_range(cs, ce)
        dates.validate_range(ps, pe)

        rows = compare_periods_svc(
            service, site_url=site_url,
            current_start=cs.isoformat(), current_end=ce.isoformat(),
            previous_start=ps.isoformat(), previous_end=pe.isoformat(),
            dimensions=dims, search_type=search_type, data_state=state,
            filters=filter_objs, limit=limit,
        )
        # sort_by applied locally; orderBy never sent to Google.
        metric_key = {
            "clicks": lambda r: abs(r.change.clicks),
            "impressions": lambda r: abs(r.change.impressions),
            "position_improvement": lambda r: r.change.position_improvement or 0,
        }.get(sort_by, lambda r: abs(r.change.clicks))
        rows = sorted(rows, key=metric_key, reverse=True)

        meta = build_meta(
            site_url=site_url,
            date_range={"start": cs.isoformat(), "end": ce.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state,
            rows_examined=len(rows), client_id=client["client_id"],
            client_name=client["client_name"],
            extra={"previous_range": {"start": ps.isoformat(), "end": pe.isoformat()},
                   "sort_applied_locally": bool(sort_by)},
        )
        return build_ok(meta, {"comparison": [r.model_dump() for r in rows]})
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_analyze_page(
    site_url: str,
    page_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 28,
    compare_previous: bool = True,
    include_inspection: bool = False,
    search_type: str = "web",
    data_state: str | None = None,
) -> str:
    """Full analysis of a single URL (spec 8.6).

    Returns current/previous performance for the page, top/winning/declining
    queries, device/country breakdown. Optional URL inspection. Does NOT crawl
    the page's HTML — only GSC data.
    """
    try:
        client = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        state = (data_state or config.DEFAULT_DATA_STATE).lower()

        end_d = dates.parse_date(end_date) if end_date else dates.default_end_date(state)
        if start_date:
            start_d = dates.parse_date(start_date)
        else:
            start_d = dates.default_start_date(days=days, end=end_d)
        dates.validate_range(start_d, end_d)

        page_filter = [Filter(dimension="page", operator="equals", expression=page_url)]

        # Page totals (dimensionless + page filter).
        cur_totals = get_totals(service, site_url=site_url, start_date=start_d.isoformat(),
                                end_date=end_d.isoformat(), search_type=search_type,
                                data_state=state, filters=page_filter)
        prev_totals = None
        if compare_previous:
            ps, pe = dates.previous_range(start_d, end_d)
            prev_totals = get_totals(service, site_url=site_url,
                                     start_date=ps.isoformat(), end_date=pe.isoformat(),
                                     search_type=search_type, data_state=state,
                                     filters=page_filter)

        # Queries driving traffic to this page.
        from ..services.search_analytics import query_search_analytics
        q_rows, _, _ = query_search_analytics(
            service, site_url=site_url, start_date=start_d.isoformat(),
            end_date=end_d.isoformat(), dimensions=["query"], search_type=search_type,
            data_state=state, page_size=500, filters=page_filter,
            sort_by="clicks", sort_direction="descending",
        )
        prev_q_rows, _, _ = (query_search_analytics(
            service, site_url=site_url, start_date=ps.isoformat(),
            end_date=pe.isoformat(), dimensions=["query"], search_type=search_type,
            data_state=state, page_size=500, filters=page_filter,
            sort_by="clicks", sort_direction="descending",
        ) if compare_previous else (None, None, None))

        # Winning/declining: compare query-by-query.
        prev_by_q = {r.keys.get("query", ""): r for r in (prev_q_rows or [])}
        winning: list[dict[str, Any]] = []
        declining: list[dict[str, Any]] = []
        for r in q_rows:
            q = r.keys.get("query", "")
            p = prev_by_q.get(q)
            if not p:
                continue
            d_clicks = r.clicks - p.clicks
            if d_clicks > 0:
                winning.append({"query": q, "current_clicks": r.clicks,
                                "previous_clicks": p.clicks, "delta": d_clicks})
            elif d_clicks < 0:
                declining.append({"query": q, "current_clicks": r.clicks,
                                  "previous_clicks": p.clicks, "delta": d_clicks})
        winning.sort(key=lambda x: x["delta"], reverse=True)
        declining.sort(key=lambda x: x["delta"])

        device = get_breakdown(service, site_url=site_url,
                               start_date=start_d.isoformat(), end_date=end_d.isoformat(),
                               dimension="device", search_type=search_type, data_state=state,
                               filters=page_filter)
        country = get_breakdown(service, site_url=site_url,
                                start_date=start_d.isoformat(), end_date=end_d.isoformat(),
                                dimension="country", search_type=search_type, data_state=state,
                                filters=page_filter)

        inspection = None
        if include_inspection:
            from ..services.url_inspection import inspect_single
            inspection = inspect_single(service, site_url=site_url, page_url=page_url).model_dump()

        meta = build_meta(
            site_url=site_url,
            date_range={"start": start_d.isoformat(), "end": end_d.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state,
            rows_examined=len(q_rows), client_id=client["client_id"],
            client_name=client["client_name"],
            extra={"page_url": page_url},
        )
        data = {
            "page_url": page_url,
            "current_totals": cur_totals.model_dump(),
            "previous_totals": prev_totals.model_dump() if prev_totals else None,
            "top_queries": [r.model_dump() for r in q_rows[:20]],
            "winning_queries": winning[:10],
            "declining_queries": declining[:10],
            "device_breakdown": [d.model_dump() for d in device],
            "country_breakdown": [d.model_dump() for d in country],
            "inspection": inspection,
        }
        return build_ok(meta, data)
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)

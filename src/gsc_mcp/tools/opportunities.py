"""Opportunity tools (spec 8.7, 8.8, 8.9)."""
from __future__ import annotations

import logging
from typing import Any

from .. import auth, config
from ..envelope import build_meta, build_ok, error_from_exception
from ..errors import GscError
from ..registry import assert_property_allowed
from ..server import mcp
from ..services import dates
from ..services.opportunity_analysis import (
    find_cannibalization, find_content_decay, find_opportunities,
)

logger = logging.getLogger("gsc_mcp.tools.opportunities")


def _client_meta_for(site_url: str) -> dict[str, Any]:
    client = assert_property_allowed(site_url)
    return {"client_id": client.id if client else None,
            "client_name": client.name if client else None}


@mcp.tool()
async def gsc_find_opportunities(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    opportunity_types: list[str] | None = None,
    min_impressions: int = 100,
    max_rows_to_scan: int = 10000,
    limit: int = 100,
    search_type: str = "web",
    data_state: str | None = None,
) -> str:
    """Find actionable SEO opportunities (spec 8.7).

    Types: striking_distance (pos 4-15), high_impression_low_ctr (pos 1-10, CTR
    below baseline), position_one_page_two (pos 8-20), zero_click (clicks=0).
    The CTR baseline version is surfaced in meta — no unsourced numbers as hard
    truth.
    """
    try:
        client = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        state = (data_state or config.DEFAULT_DATA_STATE).lower()

        end_d = dates.parse_date(end_date) if end_date else dates.default_end_date(state)
        if start_date:
            start_d = dates.parse_date(start_date)
        else:
            start_d = dates.default_start_date(end=end_d)
        dates.validate_range(start_d, end_d)

        opps, opp_meta = find_opportunities(
            service, site_url=site_url, start_date=start_d.isoformat(),
            end_date=end_d.isoformat(),
            opportunity_types=opportunity_types or ["striking_distance"],
            min_impressions=min_impressions, max_rows_to_scan=max_rows_to_scan,
            limit=limit, search_type=search_type, data_state=state,
        )

        meta = build_meta(
            site_url=site_url,
            date_range={"start": start_d.isoformat(), "end": end_d.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state,
            rows_examined=len(opps), client_id=client["client_id"],
            client_name=client["client_name"], extra=opp_meta,
        )
        return build_ok(meta, {"opportunities": opps})
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_find_content_decay(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 28,
    min_previous_clicks: int = 10,
    decline_threshold_pct: float = 20.0,
    limit: int = 100,
    search_type: str = "web",
    data_state: str | None = None,
) -> str:
    """Find pages/queries that declined vs the prior same-length period (spec 8.8).

    Entry: previous_clicks >= min_previous_clicks AND
    (clicks_percent <= -threshold OR impressions_percent <= -threshold).
    Sorted by impact_score = lost_clicks + lost_impressions * previous_ctr.
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
        ps, pe = dates.previous_range(start_d, end_d)

        results = find_content_decay(
            service, site_url=site_url,
            current_start=start_d.isoformat(), current_end=end_d.isoformat(),
            previous_start=ps.isoformat(), previous_end=pe.isoformat(),
            search_type=search_type, data_state=state,
            min_previous_clicks=min_previous_clicks,
            decline_threshold_pct=decline_threshold_pct, limit=limit,
        )

        meta = build_meta(
            site_url=site_url,
            date_range={"start": start_d.isoformat(), "end": end_d.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state, rows_examined=len(results),
            client_id=client["client_id"], client_name=client["client_name"],
            extra={"previous_range": {"start": ps.isoformat(), "end": pe.isoformat()}},
        )
        return build_ok(meta, {"decayed_items": results})
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_find_cannibalization(
    site_url: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 28,
    min_query_impressions: int = 100,
    limit: int = 100,
    search_type: str = "web",
    data_state: str | None = None,
) -> str:
    """Detect *possible* keyword cannibalization (spec 8.9, section 19).

    Finds queries where multiple URLs split impressions/clicks. Results are
    labeled 'possible cannibalization' — multiple URLs are a signal, not proof.
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

        results = find_cannibalization(
            service, site_url=site_url, start_date=start_d.isoformat(),
            end_date=end_d.isoformat(), search_type=search_type, data_state=state,
            min_query_impressions=min_query_impressions, limit=limit,
        )

        meta = build_meta(
            site_url=site_url,
            date_range={"start": start_d.isoformat(), "end": end_d.isoformat(),
                        "timezone": str(config.GSC_TIMEZONE)},
            search_type=search_type, data_state=state, rows_examined=len(results),
            client_id=client["client_id"], client_name=client["client_name"],
            warnings=["Results indicate possible cannibalization, not proof."],
        )
        return build_ok(meta, {"cannibalization_candidates": results})
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)

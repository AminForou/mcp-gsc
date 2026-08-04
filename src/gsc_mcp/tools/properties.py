"""Property tools (spec 8.1, 8.2)."""
from __future__ import annotations

import logging
from typing import Any

from .. import auth, config
from ..envelope import build_error, build_ok, build_meta, error_from_exception
from ..errors import ErrorCode, GscError
from ..registry import assert_property_allowed, get_registry
from ..server import mcp

logger = logging.getLogger("gsc_mcp.tools.properties")


@mcp.tool()
async def gsc_get_capabilities() -> str:
    """Get the server version, auth mode, auth status, client count, default
    data state, and active tools. Call this first to discover what's available.
    Does NOT expose credential or token paths.
    """
    try:
        service = auth.get_gsc_service()
        auth_ok = True
    except GscError as e:
        auth_ok = False
        service = None
        logger.info("capabilities check: auth not ready (%s)", e.code.value)
    except Exception as e:
        auth_ok = False
        service = None
        logger.info("capabilities check: auth not ready (%s)", type(e).__name__)

    registry = get_registry()
    client_count = len(registry.clients) if registry else 0

    meta = build_meta(
        site_url="",
        date_range={"start": None, "end": None, "timezone": str(config.GSC_TIMEZONE)},
        search_type="web",
        data_state=config.DEFAULT_DATA_STATE,
        rows_examined=0,
        extra={
            "version": "1.0.0",
            "auth_mode": config.AUTH_MODE,
            "authenticated": auth_ok,
            "client_count": client_count,
            "default_page_size": config.DEFAULT_PAGE_SIZE,
            "max_page_size": config.MAX_PAGE_SIZE,
            "transport": config.TRANSPORT,
        },
    )
    data = {
        "tools": [
            "gsc_get_capabilities", "gsc_list_properties",
            "gsc_query_search_analytics", "gsc_get_performance_overview",
            "gsc_compare_periods", "gsc_analyze_page",
            "gsc_find_opportunities", "gsc_find_content_decay",
            "gsc_find_cannibalization", "gsc_inspect_url",
            "gsc_inspect_urls_batch", "gsc_list_sitemaps",
            "gsc_get_sitemap_details",
        ],
    }
    return build_ok(meta, data)


@mcp.tool()
async def gsc_list_properties(client_id: str | None = None) -> str:
    """List all Google Search Console properties the authenticated account can
    access, intersected with the client registry's allowlist (if configured).
    Each property includes client_id and client_name when a registry is set.

    Args:
        client_id: Optional client id from clients.yaml to filter to one client.
    """
    try:
        service = auth.get_gsc_service()
        site_list = service.sites().list().execute()
        sites = site_list.get("siteEntry", []) or []

        registry = get_registry()
        allowed = registry.allowed_properties() if registry else None

        props: list[dict[str, Any]] = []
        for site in sites:
            site_url = site.get("siteUrl", "")
            if allowed is not None and site_url not in allowed:
                continue
            owner = registry.lookup(site_url) if registry else None
            if owner is None and registry is not None:
                continue
            if client_id and (owner is None or owner.id != client_id):
                continue
            props.append({
                "client_id": owner.id if owner else None,
                "client_name": owner.name if owner else None,
                "site_url": site_url,
                "permission_level": site.get("permissionLevel", "Unknown"),
                "label": next(
                    (p.label for p in owner.properties if p.site_url == site_url), None
                ) if owner else None,
            })

        meta = build_meta(
            site_url="",
            date_range={"start": None, "end": None, "timezone": str(config.GSC_TIMEZONE)},
            rows_examined=len(props),
            extra={"client_filter": client_id},
        )
        return build_ok(meta, {"count": len(props), "properties": props})
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)

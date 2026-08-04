"""Sitemap tools (spec 8.12, 8.13)."""
from __future__ import annotations

import logging

from .. import auth, config
from ..envelope import build_meta, build_ok, error_from_exception
from ..errors import GscError
from ..registry import assert_property_allowed
from ..server import mcp
from ..services.sitemaps import get_sitemap_details, list_sitemaps

logger = logging.getLogger("gsc_mcp.tools.sitemaps")


def _client_meta_for(site_url: str):
    client = assert_property_allowed(site_url)
    return client.id if client else None, client.name if client else None


@mcp.tool()
async def gsc_list_sitemaps(site_url: str, sitemap_index: str | None = None) -> str:
    """List all sitemaps for a property (spec 8.12).

    Output carries distinct submitted_urls and indexed_urls per content type.
    """
    try:
        cid, cname = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        sitemaps = list_sitemaps(service, site_url=site_url, sitemap_index=sitemap_index)

        meta = build_meta(
            site_url=site_url,
            date_range={"start": None, "end": None, "timezone": str(config.GSC_TIMEZONE)},
            rows_examined=len(sitemaps), client_id=cid, client_name=cname,
            extra={"sitemap_index": sitemap_index},
        )
        return build_ok(meta, {
            "count": len(sitemaps),
            "sitemaps": [s.model_dump() for s in sitemaps],
        })
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_get_sitemap_details(site_url: str, sitemap_url: str) -> str:
    """Get detailed info for one sitemap (spec 8.13).

    Only accepts a sitemap belonging to an allowed property.
    """
    try:
        cid, cname = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        details = get_sitemap_details(service, site_url=site_url, sitemap_url=sitemap_url)

        meta = build_meta(
            site_url=site_url,
            date_range={"start": None, "end": None, "timezone": str(config.GSC_TIMEZONE)},
            rows_examined=1, client_id=cid, client_name=cname,
            extra={"sitemap_url": sitemap_url},
        )
        return build_ok(meta, details.model_dump())
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)

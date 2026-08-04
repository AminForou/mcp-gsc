"""Inspection tools (spec 8.10, 8.11)."""
from __future__ import annotations

import logging

from .. import auth, config
from ..envelope import build_meta, build_ok, error_from_exception
from ..errors import GscError
from ..registry import assert_property_allowed
from ..server import mcp
from ..services.url_inspection import inspect_batch, inspect_single

logger = logging.getLogger("gsc_mcp.tools.inspection")


def _client_meta_for(site_url: str):
    client = assert_property_allowed(site_url)
    return client.id if client else None, client.name if client else None


@mcp.tool()
async def gsc_inspect_url(site_url: str, page_url: str) -> str:
    """Get the index/coverage status of a single URL (spec 8.10)."""
    try:
        cid, cname = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        result = inspect_single(service, site_url=site_url, page_url=page_url)

        meta = build_meta(
            site_url=site_url,
            date_range={"start": None, "end": None, "timezone": str(config.GSC_TIMEZONE)},
            rows_examined=1, client_id=cid, client_name=cname,
            extra={"page_url": page_url},
        )
        return build_ok(meta, result.model_dump())
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)


@mcp.tool()
async def gsc_inspect_urls_batch(site_url: str, urls: list[str]) -> str:
    """Inspect up to 10 URLs with controlled concurrency (spec 8.11).

    Takes a typed array (not a multiline string). Partial failure is tolerated;
    the summary reports succeeded/failed/indexed/not_indexed.
    """
    try:
        cid, cname = _client_meta_for(site_url)
        service = auth.get_gsc_service()
        items, summary = await inspect_batch(service, site_url=site_url, urls=urls)

        meta = build_meta(
            site_url=site_url,
            date_range={"start": None, "end": None, "timezone": str(config.GSC_TIMEZONE)},
            rows_examined=len(items), client_id=cid, client_name=cname,
            extra={"requested_count": len(urls)},
        )
        return build_ok(meta, {
            "results": [i.model_dump() for i in items],
            "summary": summary.model_dump(),
        })
    except GscError as e:
        return error_from_exception(e)
    except Exception as e:
        return error_from_exception(e)

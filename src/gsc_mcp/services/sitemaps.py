"""Sitemap service (spec 4.7, 8.12, 8.13).

Fixes the bug where `submitted` was labeled as `indexed_urls`. The two counts
are now distinct fields: `submitted_urls` and `indexed_urls`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from ..errors import ErrorCode, GscError
from ..models.sitemap import Sitemap, SitemapContent, SitemapDetails

logger = logging.getLogger("gsc_mcp.sitemaps")


def _fmt_dt(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return raw


def _parse_contents(raw_contents: list[dict[str, Any]] | None) -> list[SitemapContent]:
    """Map GSC contents → SitemapContent with distinct submitted/indexed (spec 4.7)."""
    out: list[SitemapContent] = []
    for c in raw_contents or []:
        out.append(SitemapContent(
            type=(c.get("type") or "web").upper(),
            submitted_urls=int(c.get("submitted", 0) or 0),
            indexed_urls=int(c.get("indexed", 0)) if c.get("indexed") is not None else None,
        ))
    return out


def list_sitemaps(
    service: Any, *, site_url: str, sitemap_index: str | None = None,
) -> list[Sitemap]:
    """Spec 8.12: list all sitemaps with distinct submitted/indexed counts."""
    if sitemap_index:
        kwargs: dict[str, Any] = {"siteUrl": site_url, "sitemapIndex": sitemap_index}
    else:
        kwargs = {"siteUrl": site_url}
    response = service.sitemaps().list(**kwargs).execute()
    raw_list = response.get("sitemap", []) or []
    out: list[Sitemap] = []
    for sm in raw_list:
        errors = int(sm.get("errors", 0) or 0)
        warnings = int(sm.get("warnings", 0) or 0)
        out.append(Sitemap(
            path=sm.get("path", "Unknown"),
            last_submitted=_fmt_dt(sm.get("lastSubmitted")),
            last_downloaded=_fmt_dt(sm.get("lastDownloaded")),
            is_pending=bool(sm.get("isPending", False)),
            is_sitemap_index=bool(sm.get("isSitemapsIndex", False)),
            errors=errors,
            warnings=warnings,
            contents=_parse_contents(sm.get("contents")),
        ))
    return out


def get_sitemap_details(
    service: Any, *, site_url: str, sitemap_url: str,
) -> SitemapDetails:
    """Spec 8.13: details for one sitemap (must belong to an allowed property)."""
    if not sitemap_url:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "sitemap_url is required.", retryable=False)
    details = service.sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
    if not details:
        raise GscError(ErrorCode.NO_DATA, f"No details found for sitemap {sitemap_url!r}.", retryable=False)
    is_index = bool(details.get("isSitemapsIndex", False))
    return SitemapDetails(
        sitemap_url=sitemap_url,
        site_url=site_url,
        type="Index" if is_index else "Sitemap",
        status="pending" if details.get("isPending", False) else "processed",
        last_submitted=_fmt_dt(details.get("lastSubmitted")),
        last_downloaded=_fmt_dt(details.get("lastDownloaded")),
        errors=int(details.get("errors", 0) or 0),
        warnings=int(details.get("warnings", 0) or 0),
        contents=_parse_contents(details.get("contents")),
        is_index=is_index,
    )


__all__ = ["list_sitemaps", "get_sitemap_details"]

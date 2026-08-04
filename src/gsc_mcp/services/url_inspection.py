"""URL Inspection service (spec 8.10, 8.11).

Single + batch inspection with controlled concurrency, per-URL timeout, and
partial-failure tolerance. Retries only 429/5xx (spec 13).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from .. import config
from ..errors import ErrorCode, GscError
from ..models.inspection import (
    BatchInspectionItem, BatchInspectionSummary, InspectionResult, RichResults,
)
from ..retry import call_with_retry, map_exception

logger = logging.getLogger("gsc_mcp.url_inspection")


def _fmt_dt(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return raw


def _build_rich_results(inspection: dict[str, Any]) -> RichResults | None:
    raw = inspection.get("richResultsResult")
    if not raw:
        return None
    return RichResults(
        verdict=raw.get("verdict", "UNKNOWN"),
        detected_types=[item.get("richResultType", "Unknown") for item in raw.get("detectedItems", []) or []],
        issues=[
            {"severity": i.get("severity"), "message": i.get("message")}
            for i in raw.get("richResultsIssues", []) or []
        ],
    )


def inspect_single(
    service: Any, *, site_url: str, page_url: str,
) -> InspectionResult:
    """Spec 8.10: detailed crawl/index status for one URL."""
    request = {"inspectionUrl": page_url, "siteUrl": site_url}
    response = call_with_retry(
        lambda: service.urlInspection().index().inspect(body=request).execute()
    )
    if not response or "inspectionResult" not in response:
        return InspectionResult(page_url=page_url, site_url=site_url, verdict="NO_DATA")

    inspection = response["inspectionResult"]
    idx = inspection.get("indexStatusResult", {}) or {}
    return InspectionResult(
        page_url=page_url,
        site_url=site_url,
        inspection_result_link=inspection.get("inspectionResultLink"),
        verdict=idx.get("verdict", "UNKNOWN"),
        coverage_state=idx.get("coverageState"),
        indexing_state=idx.get("indexingState"),
        last_crawl_time=_fmt_dt(idx.get("lastCrawlTime")),
        crawled_as=idx.get("crawledAs"),
        robots_txt_state=idx.get("robotsTxtState"),
        page_fetch_state=idx.get("pageFetchState"),
        user_canonical=idx.get("userCanonical"),
        google_canonical=idx.get("googleCanonical"),
        referring_urls=(idx.get("referringUrls", []) or [])[:5],
        rich_results=_build_rich_results(inspection),
    )


async def inspect_batch(
    service: Any, *, site_url: str, urls: list[str],
) -> tuple[list[BatchInspectionItem], BatchInspectionSummary]:
    """Spec 8.11: batch inspection with concurrency cap and partial failure.

    Rules:
    - typed array input (not a multiline string)
    - max 10 URLs per call
    - concurrency = config.INSPECTION_CONCURRENCY (default 2)
    - per-URL timeout
    - retry only 429/5xx
    - one URL's failure does NOT fail the batch
    - summary includes succeeded/failed/indexed/not_indexed
    """
    if len(urls) > 10:
        raise GscError(
            ErrorCode.INVALID_ARGUMENT,
            f"Batch inspection limited to 10 URLs per call; got {len(urls)}.",
            retryable=False,
        )
    if len(urls) == 0:
        raise GscError(ErrorCode.INVALID_ARGUMENT, "No URLs provided.", retryable=False)

    sem = asyncio.Semaphore(max(1, config.INSPECTION_CONCURRENCY))

    async def _one(url: str) -> BatchInspectionItem:
        async with sem:
            try:
                result = await asyncio.to_thread(
                    lambda: inspect_single(service, site_url=site_url, page_url=url)
                )
                rich = (
                    ", ".join(result.rich_results.detected_types)
                    if result.rich_results and result.rich_results.detected_types
                    else "None"
                )
                return BatchInspectionItem(
                    url=url, ok=True, verdict=result.verdict,
                    coverage_state=result.coverage_state,
                    last_crawl_time=result.last_crawl_time,
                    rich_results=rich,
                )
            except Exception as exc:
                gsc_err = map_exception(exc)
                logger.warning("batch inspection failed for %s: %s", url, gsc_err.message)
                return BatchInspectionItem(url=url, ok=False, error=gsc_err.message)

    items = await asyncio.gather(*[_one(u) for u in urls])
    summary = BatchInspectionSummary(
        succeeded=sum(1 for i in items if i.ok),
        failed=sum(1 for i in items if not i.ok),
        indexed=sum(1 for i in items if i.ok and i.verdict == "PASS"),
        not_indexed=sum(1 for i in items if i.ok and i.verdict != "PASS"),
    )
    return list(items), summary


__all__ = ["inspect_single", "inspect_batch"]

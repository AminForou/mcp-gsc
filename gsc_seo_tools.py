"""Higher-level, read-only SEO analysis tools for the remote GSC MCP server.

The functions in this module intentionally return JSON strings so they can be
registered beside the existing upstream tools in ``chatgpt_server.py``.

Search Analytics is not an exhaustive URL/index export. Tools that use it label
those URLs as observed Search Analytics pages. URL Inspection results are only
available for explicitly inspected candidate URLs and remain subject to Google
API quotas.
"""

from __future__ import annotations

import gzip
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from typing import Any, Sequence

import gsc_server as upstream

_SEARCH_TYPES = {
    "WEB": "web",
    "IMAGE": "image",
    "VIDEO": "video",
    "NEWS": "news",
    "DISCOVER": "discover",
    "GOOGLE_NEWS": "googleNews",
    "GOOGLENEWS": "googleNews",
}
_MAX_API_PAGE_SIZE = 25_000
_MAX_SITEMAP_BYTES = 10 * 1024 * 1024
_DEFAULT_USER_AGENT = "mp-gsc-mcp/seo-tools"


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=False)


def _error(code: str, message: str, **details: Any) -> str:
    payload: dict[str, Any] = {"error": code, "message": message}
    if details:
        payload["details"] = details
    return _json(payload)


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date in YYYY-MM-DD format") from exc


def _validate_date_range(start_date: str, end_date: str) -> None:
    start = _parse_iso_date(start_date, "start_date")
    end = _parse_iso_date(end_date, "end_date")
    if start > end:
        raise ValueError("start_date must be on or before end_date")


def _normalise_search_type(search_type: str) -> str:
    key = search_type.strip().upper().replace("-", "_").replace(" ", "_")
    try:
        return _SEARCH_TYPES[key]
    except KeyError as exc:
        raise ValueError(
            "search_type must be one of WEB, IMAGE, VIDEO, NEWS, DISCOVER, GOOGLE_NEWS"
        ) from exc


def _search_filter(dimension: str, expression: str | None) -> dict[str, str] | None:
    if expression is None or not expression.strip():
        return None
    return {
        "dimension": dimension,
        "operator": "contains",
        "expression": expression.strip(),
    }


def _query_search_analytics(
    *,
    site_url: str,
    start_date: str,
    end_date: str,
    dimensions: Sequence[str],
    search_type: str = "WEB",
    row_limit: int = 5_000,
    filters: Sequence[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve all requested Search Analytics rows up to ``row_limit``."""

    _validate_date_range(start_date, end_date)
    if row_limit < 1:
        raise ValueError("row_limit must be at least 1")
    if not dimensions:
        raise ValueError("at least one dimension is required")

    service = upstream.get_gsc_service()
    api_type = _normalise_search_type(search_type)
    rows: list[dict[str, Any]] = []
    start_row = 0

    while len(rows) < row_limit:
        request_count = min(_MAX_API_PAGE_SIZE, row_limit - len(rows))
        body: dict[str, Any] = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": list(dimensions),
            "rowLimit": request_count,
            "startRow": start_row,
            "dataState": upstream.DATA_STATE,
            "type": api_type,
        }
        active_filters = [item for item in (filters or []) if item]
        if active_filters:
            body["dimensionFilterGroups"] = [
                {"groupType": "and", "filters": active_filters}
            ]

        response = (
            service.searchanalytics()
            .query(siteUrl=site_url, body=body)
            .execute()
        )
        response_rows = response.get("rows", [])
        if not response_rows:
            break

        for raw in response_rows:
            keys = raw.get("keys", [])
            item = {
                dimension: keys[index] if index < len(keys) else None
                for index, dimension in enumerate(dimensions)
            }
            item.update(
                {
                    "clicks": int(raw.get("clicks", 0)),
                    "impressions": int(raw.get("impressions", 0)),
                    "ctr": round(float(raw.get("ctr", 0.0)), 6),
                    "position": round(float(raw.get("position", 0.0)), 3),
                }
            )
            rows.append(item)
            if len(rows) >= row_limit:
                break

        if len(response_rows) < request_count:
            break
        start_row += len(response_rows)

    return rows


def _comparison_number(current: float, previous: float) -> dict[str, float | None]:
    difference = current - previous
    percentage = None if previous == 0 else round((difference / previous) * 100, 2)
    return {"difference": round(difference, 6), "percentage": percentage}


def _url_lines(urls: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for raw in urls.replace(",", "\n").splitlines():
        value = raw.strip()
        if not value or value in seen:
            continue
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"Invalid HTTP(S) URL: {value}")
        values.append(value)
        seen.add(value)
    return values


def _canonical_compare_value(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname
    path = parsed.path or "/"
    query = urllib.parse.urlencode(sorted(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)))
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _variant_group_key(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    path = urllib.parse.unquote(parsed.path or "/").lower()
    if path != "/":
        path = path.rstrip("/")
    # Group query-string variants with the same base path so parameterised URLs
    # can be assessed as candidate variants rather than being split into separate groups.
    return urllib.parse.urlunsplit(("https", hostname, path, "", ""))


def _property_allows_url(site_url: str, target_url: str) -> bool:
    parsed = urllib.parse.urlsplit(target_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        return False
    if site_url.startswith("sc-domain:"):
        domain = site_url.removeprefix("sc-domain:").lower().rstrip(".")
        return host == domain or host.endswith(f".{domain}")

    property_url = urllib.parse.urlsplit(site_url)
    property_host = (property_url.hostname or "").lower().rstrip(".")
    if host != property_host:
        return False
    property_path = property_url.path or "/"
    target_path = parsed.path or "/"
    return target_path.startswith(property_path)


def _assert_public_address(hostname: str) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Unable to resolve sitemap host: {hostname}") from exc
    if not addresses:
        raise ValueError(f"Unable to resolve sitemap host: {hostname}")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError(f"Sitemap host resolves to a non-public address: {ip}")


def _validate_fetch_url(site_url: str, target_url: str) -> None:
    parsed = urllib.parse.urlsplit(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Sitemap URL must use HTTP or HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Sitemap URLs containing credentials are not allowed")
    if not _property_allows_url(site_url, target_url):
        raise ValueError("Sitemap URL is outside the approved Search Console property")
    _assert_public_address(parsed.hostname)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, site_url: str) -> None:
        super().__init__()
        self.site_url = site_url

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        _validate_fetch_url(self.site_url, absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _fetch_sitemap(site_url: str, sitemap_url: str) -> bytes:
    _validate_fetch_url(site_url, sitemap_url)
    opener = urllib.request.build_opener(_SafeRedirectHandler(site_url))
    request = urllib.request.Request(
        sitemap_url,
        headers={"User-Agent": _DEFAULT_USER_AGENT, "Accept-Encoding": "gzip"},
    )
    try:
        with opener.open(request, timeout=20) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > _MAX_SITEMAP_BYTES:
                raise ValueError("Sitemap exceeds the maximum allowed size")
            payload = response.read(_MAX_SITEMAP_BYTES + 1)
            if len(payload) > _MAX_SITEMAP_BYTES:
                raise ValueError("Sitemap exceeds the maximum allowed size")
            content_encoding = response.headers.get("Content-Encoding", "").lower()
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Sitemap returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Unable to fetch sitemap: {exc.reason}") from exc

    if content_encoding == "gzip" or sitemap_url.lower().endswith(".gz"):
        try:
            payload = gzip.decompress(payload)
        except OSError as exc:
            raise ValueError("Sitemap gzip content is invalid") from exc
    return payload


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_sitemap_document(payload: bytes) -> tuple[str, list[str]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError(f"Sitemap XML is invalid: {exc}") from exc

    root_type = _xml_local_name(root.tag)
    if root_type not in {"urlset", "sitemapindex"}:
        raise ValueError(f"Unsupported sitemap root element: {root_type}")

    locations: list[str] = []
    for element in root.iter():
        if _xml_local_name(element.tag) == "loc" and element.text:
            location = element.text.strip()
            if location:
                locations.append(location)
    return root_type, locations


def _collect_sitemap_urls(
    site_url: str,
    sitemap_url: str,
    *,
    max_urls: int,
    max_child_sitemaps: int = 50,
) -> tuple[list[str], list[str]]:
    queue = [sitemap_url]
    visited_sitemaps: set[str] = set()
    page_urls: list[str] = []
    warnings: list[str] = []

    while queue and len(page_urls) < max_urls:
        current = queue.pop(0)
        if current in visited_sitemaps:
            continue
        if len(visited_sitemaps) >= max_child_sitemaps:
            warnings.append("Stopped after reaching the child-sitemap limit")
            break
        visited_sitemaps.add(current)
        payload = _fetch_sitemap(site_url, current)
        document_type, locations = _parse_sitemap_document(payload)
        if document_type == "sitemapindex":
            for child in locations:
                if len(visited_sitemaps) + len(queue) >= max_child_sitemaps:
                    warnings.append("Some child sitemaps were skipped due to the configured limit")
                    break
                _validate_fetch_url(site_url, child)
                queue.append(child)
        else:
            for page_url in locations:
                if not _property_allows_url(site_url, page_url):
                    warnings.append(f"Skipped out-of-property URL: {page_url}")
                    continue
                page_urls.append(page_url)
                if len(page_urls) >= max_urls:
                    warnings.append("Stopped after reaching the sitemap URL limit")
                    break

    return list(dict.fromkeys(page_urls)), warnings


def _list_sitemaps_payload(site_url: str) -> dict[str, Any]:
    service = upstream.get_gsc_service()
    response = service.sitemaps().list(siteUrl=site_url).execute()
    sitemaps: list[dict[str, Any]] = []
    for raw in response.get("sitemap", []):
        contents = raw.get("contents", [])
        sitemaps.append(
            {
                "path": raw.get("path"),
                "last_submitted": raw.get("lastSubmitted"),
                "last_downloaded": raw.get("lastDownloaded"),
                "is_pending": bool(raw.get("isPending", False)),
                "is_sitemaps_index": bool(raw.get("isSitemapsIndex", False)),
                "type": raw.get("type"),
                "errors": int(raw.get("errors", 0)),
                "warnings": int(raw.get("warnings", 0)),
                "contents": [
                    {
                        "type": item.get("type"),
                        "submitted": int(item.get("submitted", 0)),
                        "indexed": int(item.get("indexed", 0)),
                    }
                    for item in contents
                ],
            }
        )
    return {"site_url": site_url, "count": len(sitemaps), "sitemaps": sitemaps}


def _sitemap_details_payload(site_url: str, sitemap_url: str) -> dict[str, Any]:
    service = upstream.get_gsc_service()
    raw = service.sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
    return {
        "site_url": site_url,
        "sitemap_url": sitemap_url,
        "path": raw.get("path", sitemap_url),
        "last_submitted": raw.get("lastSubmitted"),
        "last_downloaded": raw.get("lastDownloaded"),
        "is_pending": bool(raw.get("isPending", False)),
        "is_sitemaps_index": bool(raw.get("isSitemapsIndex", False)),
        "type": raw.get("type"),
        "errors": int(raw.get("errors", 0)),
        "warnings": int(raw.get("warnings", 0)),
        "contents": [
            {
                "type": item.get("type"),
                "submitted": int(item.get("submitted", 0)),
                "indexed": int(item.get("indexed", 0)),
            }
            for item in raw.get("contents", [])
        ],
    }


def _inspection_payload(site_url: str, page_url: str) -> dict[str, Any]:
    service = upstream.get_gsc_service()
    response = (
        service.urlInspection()
        .index()
        .inspect(body={"inspectionUrl": page_url, "siteUrl": site_url})
        .execute()
    )
    result = response.get("inspectionResult", {})
    index = result.get("indexStatusResult", {})
    rich = result.get("richResultsResult")
    return {
        "page_url": page_url,
        "site_url": site_url,
        "inspection_result_link": result.get("inspectionResultLink"),
        "verdict": index.get("verdict"),
        "coverage_state": index.get("coverageState"),
        "last_crawled": index.get("lastCrawlTime"),
        "page_fetch_state": index.get("pageFetchState"),
        "robots_txt_state": index.get("robotsTxtState"),
        "indexing_state": index.get("indexingState"),
        "google_canonical": index.get("googleCanonical"),
        "user_canonical": index.get("userCanonical"),
        "crawled_as": index.get("crawledAs"),
        "referring_urls": index.get("referringUrls", []),
        "rich_results": rich,
    }


def _inspect_many(site_url: str, urls: Sequence[str]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for page_url in urls:
        try:
            results.append(_inspection_payload(site_url, page_url))
        except Exception as exc:  # Preserve partial results when quota/URL errors occur.
            errors.append({"page_url": page_url, "error": str(exc)})
    return results, errors


async def get_query_page_performance(
    site_url: str,
    start_date: str,
    end_date: str,
    query_filter: str | None = None,
    page_filter: str | None = None,
    search_type: str = "WEB",
    row_limit: int = 5_000,
) -> str:
    """Return query-by-page Search Analytics performance with automatic pagination."""
    try:
        filters = [
            item
            for item in (
                _search_filter("query", query_filter),
                _search_filter("page", page_filter),
            )
            if item
        ]
        rows = _query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=("query", "page"),
            search_type=search_type,
            row_limit=row_limit,
            filters=filters,
        )
        return _json(
            {
                "site_url": site_url,
                "date_range": {"start": start_date, "end": end_date},
                "search_type": search_type.upper(),
                "row_count": len(rows),
                "row_limit": row_limit,
                "is_exhaustive": False,
                "limitations": [
                    "Search Console returns top rows and may omit anonymised or low-volume queries."
                ],
                "rows": rows,
            }
        )
    except Exception as exc:
        return _error("query_page_performance_failed", str(exc))


async def compare_query_page_periods(
    site_url: str,
    period1_start: str,
    period1_end: str,
    period2_start: str,
    period2_end: str,
    query_filter: str | None = None,
    page_filter: str | None = None,
    search_type: str = "WEB",
    row_limit_per_period: int = 10_000,
    result_limit: int = 1_000,
    sort_by: str = "click_difference",
) -> str:
    """Compare query-page combinations between two explicit date periods."""
    try:
        filters = [
            item
            for item in (
                _search_filter("query", query_filter),
                _search_filter("page", page_filter),
            )
            if item
        ]
        common = {
            "site_url": site_url,
            "dimensions": ("query", "page"),
            "search_type": search_type,
            "row_limit": row_limit_per_period,
            "filters": filters,
        }
        period1 = _query_search_analytics(
            start_date=period1_start, end_date=period1_end, **common
        )
        period2 = _query_search_analytics(
            start_date=period2_start, end_date=period2_end, **common
        )
        p1 = {(row["query"], row["page"]): row for row in period1}
        p2 = {(row["query"], row["page"]): row for row in period2}
        comparison: list[dict[str, Any]] = []
        for key in sorted(set(p1) | set(p2)):
            left = p1.get(key, {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0})
            right = p2.get(key, {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0})
            click_change = _comparison_number(float(right["clicks"]), float(left["clicks"]))
            impression_change = _comparison_number(
                float(right["impressions"]), float(left["impressions"])
            )
            ctr_change = _comparison_number(float(right["ctr"]), float(left["ctr"]))
            # Lower average position is better; expose signed movement as p1 - p2.
            position_movement = round(float(left["position"]) - float(right["position"]), 3)
            if key not in p1:
                status = "new"
            elif key not in p2:
                status = "lost"
            elif click_change["difference"] > 0:
                status = "improved"
            elif click_change["difference"] < 0:
                status = "declined"
            else:
                status = "unchanged"
            comparison.append(
                {
                    "query": key[0],
                    "page": key[1],
                    "status": status,
                    "period1": left,
                    "period2": right,
                    "click_difference": click_change["difference"],
                    "click_percentage": click_change["percentage"],
                    "impression_difference": impression_change["difference"],
                    "impression_percentage": impression_change["percentage"],
                    "ctr_difference": ctr_change["difference"],
                    "ctr_percentage": ctr_change["percentage"],
                    "position_movement": position_movement,
                }
            )

        valid_sort_fields = {
            "click_difference",
            "impression_difference",
            "ctr_difference",
            "position_movement",
        }
        if sort_by not in valid_sort_fields:
            raise ValueError(f"sort_by must be one of {', '.join(sorted(valid_sort_fields))}")
        comparison.sort(key=lambda row: abs(float(row[sort_by])), reverse=True)
        return _json(
            {
                "site_url": site_url,
                "period1": {"start": period1_start, "end": period1_end},
                "period2": {"start": period2_start, "end": period2_end},
                "total_items": len(comparison),
                "showing": min(len(comparison), result_limit),
                "is_exhaustive": False,
                "comparison": comparison[: max(1, result_limit)],
            }
        )
    except Exception as exc:
        return _error("query_page_period_comparison_failed", str(exc))


async def find_query_cannibalisation(
    site_url: str,
    start_date: str,
    end_date: str,
    minimum_query_impressions: int = 20,
    minimum_page_impressions: int = 5,
    minimum_competing_pages: int = 2,
    search_type: str = "WEB",
    row_limit: int = 25_000,
    result_limit: int = 500,
) -> str:
    """Find queries with meaningful visibility split across multiple pages."""
    try:
        if minimum_competing_pages < 2:
            raise ValueError("minimum_competing_pages must be at least 2")
        rows = _query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=("query", "page"),
            search_type=search_type,
            row_limit=row_limit,
        )
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            if row["impressions"] >= minimum_page_impressions:
                grouped[str(row["query"])].append(row)

        findings: list[dict[str, Any]] = []
        for query, pages in grouped.items():
            if len(pages) < minimum_competing_pages:
                continue
            total_impressions = sum(int(page["impressions"]) for page in pages)
            if total_impressions < minimum_query_impressions:
                continue
            total_clicks = sum(int(page["clicks"]) for page in pages)
            pages.sort(key=lambda page: int(page["impressions"]), reverse=True)
            enriched = []
            for page in pages:
                enriched.append(
                    {
                        **page,
                        "impression_share": round(
                            int(page["impressions"]) / total_impressions, 4
                        ),
                        "click_share": (
                            round(int(page["clicks"]) / total_clicks, 4)
                            if total_clicks
                            else 0.0
                        ),
                    }
                )
            second_share = enriched[1]["impression_share"]
            if len(enriched) >= 3 and second_share >= 0.2:
                severity = "high"
            elif second_share >= 0.25:
                severity = "high"
            elif second_share >= 0.1:
                severity = "medium"
            else:
                severity = "low"
            findings.append(
                {
                    "query": query,
                    "severity": severity,
                    "competing_page_count": len(enriched),
                    "total_clicks": total_clicks,
                    "total_impressions": total_impressions,
                    "pages": enriched,
                }
            )

        severity_order = {"high": 3, "medium": 2, "low": 1}
        findings.sort(
            key=lambda item: (
                severity_order[item["severity"]], item["total_impressions"]
            ),
            reverse=True,
        )
        return _json(
            {
                "site_url": site_url,
                "date_range": {"start": start_date, "end": end_date},
                "finding_count": len(findings),
                "showing": min(len(findings), result_limit),
                "is_exhaustive": False,
                "definition": (
                    "Observed query-page competition in Search Analytics; this is not "
                    "a complete index-wide cannibalisation inventory."
                ),
                "findings": findings[: max(1, result_limit)],
            }
        )
    except Exception as exc:
        return _error("query_cannibalisation_analysis_failed", str(exc))


async def inspect_url_index_status(site_url: str, page_url: str) -> str:
    """Inspect Google's indexed-version status for one URL."""
    try:
        return _json(_inspection_payload(site_url, page_url))
    except Exception as exc:
        return _error("url_inspection_failed", str(exc), page_url=page_url)


async def batch_inspect_urls(site_url: str, urls: str, max_urls: int = 100) -> str:
    """Inspect multiple candidate URLs and preserve partial results."""
    try:
        values = _url_lines(urls)
        if not values:
            raise ValueError("At least one URL is required")
        if len(values) > max_urls:
            raise ValueError(f"Received {len(values)} URLs; maximum is {max_urls}")
        results, errors = _inspect_many(site_url, values)
        return _json(
            {
                "site_url": site_url,
                "requested": len(values),
                "completed": len(results),
                "failed": len(errors),
                "results": results,
                "errors": errors,
            }
        )
    except Exception as exc:
        return _error("batch_url_inspection_failed", str(exc))


async def list_sitemaps(site_url: str) -> str:
    """List submitted sitemaps and their current Search Console metadata."""
    try:
        return _json(_list_sitemaps_payload(site_url))
    except Exception as exc:
        return _error("list_sitemaps_failed", str(exc))


async def get_sitemap_status(site_url: str, sitemap_url: str) -> str:
    """Return Search Console status and content counts for one sitemap."""
    try:
        return _json(_sitemap_details_payload(site_url, sitemap_url))
    except Exception as exc:
        return _error("get_sitemap_status_failed", str(exc), sitemap_url=sitemap_url)


async def compare_sitemap_to_gsc_pages(
    site_url: str,
    sitemap_url: str,
    start_date: str,
    end_date: str,
    search_type: str = "WEB",
    max_sitemap_urls: int = 10_000,
    analytics_row_limit: int = 25_000,
    result_limit_per_category: int = 2_000,
) -> str:
    """Compare sitemap URLs with pages observed in Search Analytics."""
    try:
        sitemap_urls, warnings = _collect_sitemap_urls(
            site_url, sitemap_url, max_urls=max_sitemap_urls
        )
        analytics_rows = _query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=("page",),
            search_type=search_type,
            row_limit=analytics_row_limit,
        )
        sitemap_map = {_canonical_compare_value(url): url for url in sitemap_urls}
        analytics_map = {
            _canonical_compare_value(str(row["page"])): row for row in analytics_rows
        }
        both_keys = sorted(set(sitemap_map) & set(analytics_map))
        sitemap_only_keys = sorted(set(sitemap_map) - set(analytics_map))
        analytics_only_keys = sorted(set(analytics_map) - set(sitemap_map))

        return _json(
            {
                "site_url": site_url,
                "sitemap_url": sitemap_url,
                "date_range": {"start": start_date, "end": end_date},
                "comparison_basis": "sitemap_urls_vs_search_analytics_observed_pages",
                "limitations": [
                    "Search Analytics pages are not a complete export of indexed or discovered URLs.",
                    "A sitemap-only URL may still be indexed but have no reportable search performance in the selected period.",
                ],
                "counts": {
                    "sitemap_urls": len(sitemap_map),
                    "search_analytics_pages": len(analytics_map),
                    "in_both": len(both_keys),
                    "sitemap_only": len(sitemap_only_keys),
                    "search_analytics_only": len(analytics_only_keys),
                },
                "in_both": [
                    {"url": sitemap_map[key], "search_performance": analytics_map[key]}
                    for key in both_keys[:result_limit_per_category]
                ],
                "sitemap_only": [
                    sitemap_map[key] for key in sitemap_only_keys[:result_limit_per_category]
                ],
                "search_analytics_only": [
                    analytics_map[key]
                    for key in analytics_only_keys[:result_limit_per_category]
                ],
                "warnings": warnings,
            }
        )
    except Exception as exc:
        return _error("sitemap_gsc_page_comparison_failed", str(exc))


async def find_indexed_url_variants(
    site_url: str,
    start_date: str,
    end_date: str,
    sitemap_url: str | None = None,
    urls: str = "",
    search_type: str = "WEB",
    analytics_row_limit: int = 25_000,
    max_sitemap_urls: int = 10_000,
    max_inspections: int = 100,
) -> str:
    """Find equivalent URL variants from supplied, sitemap and GSC-observed candidates."""
    try:
        candidate_sources: dict[str, set[str]] = defaultdict(set)
        for value in _url_lines(urls) if urls.strip() else []:
            candidate_sources[value].add("supplied")

        warnings: list[str] = []
        if sitemap_url:
            sitemap_urls, sitemap_warnings = _collect_sitemap_urls(
                site_url, sitemap_url, max_urls=max_sitemap_urls
            )
            warnings.extend(sitemap_warnings)
            for value in sitemap_urls:
                candidate_sources[value].add("sitemap")

        analytics_rows = _query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=("page",),
            search_type=search_type,
            row_limit=analytics_row_limit,
        )
        for row in analytics_rows:
            candidate_sources[str(row["page"])].add("search_analytics")

        grouped: dict[str, list[str]] = defaultdict(list)
        for candidate in candidate_sources:
            grouped[_variant_group_key(candidate)].append(candidate)
        variant_groups = {
            key: sorted(set(values)) for key, values in grouped.items() if len(set(values)) > 1
        }
        inspection_candidates = [
            value
            for values in variant_groups.values()
            for value in values
        ]
        inspection_candidates = list(dict.fromkeys(inspection_candidates))
        if len(inspection_candidates) > max_inspections:
            warnings.append(
                f"Only the first {max_inspections} variant URLs were inspected due to the configured limit"
            )
        inspected, errors = _inspect_many(
            site_url, inspection_candidates[: max(1, max_inspections)]
        )
        inspection_by_url = {item["page_url"]: item for item in inspected}

        findings: list[dict[str, Any]] = []
        for group_key, variants in sorted(variant_groups.items()):
            evidence = []
            indexed_count = 0
            for variant in variants:
                inspection = inspection_by_url.get(variant)
                is_indexed = bool(inspection and inspection.get("verdict") == "PASS")
                indexed_count += int(is_indexed)
                evidence.append(
                    {
                        "url": variant,
                        "sources": sorted(candidate_sources[variant]),
                        "inspected": inspection is not None,
                        "is_indexed": is_indexed,
                        "inspection": inspection,
                    }
                )
            findings.append(
                {
                    "normalised_group": group_key,
                    "variant_count": len(variants),
                    "indexed_variant_count": indexed_count,
                    "multiple_indexed_variants": indexed_count > 1,
                    "variants": evidence,
                }
            )

        findings.sort(
            key=lambda item: (
                item["multiple_indexed_variants"],
                item["indexed_variant_count"],
                item["variant_count"],
            ),
            reverse=True,
        )
        return _json(
            {
                "site_url": site_url,
                "candidate_count": len(candidate_sources),
                "variant_group_count": len(findings),
                "inspection_count": len(inspected),
                "limitations": [
                    "Google Search Console does not provide a complete export of all indexed URLs.",
                    "This tool only assesses URL variants discovered from supplied URLs, sitemap URLs and Search Analytics pages.",
                ],
                "findings": findings,
                "inspection_errors": errors,
                "warnings": warnings,
            }
        )
    except Exception as exc:
        return _error("indexed_url_variant_analysis_failed", str(exc))


async def find_google_canonical_conflicts(
    site_url: str,
    urls: str = "",
    sitemap_url: str | None = None,
    max_sitemap_urls: int = 100,
    max_inspections: int = 100,
    include_matching: bool = False,
) -> str:
    """Compare Google-selected and user-declared canonicals for candidate URLs."""
    try:
        candidates = _url_lines(urls) if urls.strip() else []
        warnings: list[str] = []
        if sitemap_url:
            sitemap_candidates, sitemap_warnings = _collect_sitemap_urls(
                site_url, sitemap_url, max_urls=max_sitemap_urls
            )
            candidates.extend(sitemap_candidates)
            warnings.extend(sitemap_warnings)
        candidates = list(dict.fromkeys(candidates))
        if not candidates:
            raise ValueError("Provide urls or sitemap_url")
        if len(candidates) > max_inspections:
            warnings.append(
                f"Only the first {max_inspections} URLs were inspected due to the configured limit"
            )
        inspected, errors = _inspect_many(site_url, candidates[: max(1, max_inspections)])

        findings: list[dict[str, Any]] = []
        matching_count = 0
        conflict_count = 0
        incomplete_count = 0
        for item in inspected:
            user = item.get("user_canonical")
            google = item.get("google_canonical")
            if not user or not google:
                status = "canonical_evidence_incomplete"
                incomplete_count += 1
                equivalent_variant = False
            else:
                raw_match = _canonical_compare_value(user) == _canonical_compare_value(google)
                equivalent_variant = _variant_group_key(user) == _variant_group_key(google)
                if raw_match:
                    status = "canonical_matches"
                    matching_count += 1
                elif equivalent_variant:
                    status = "google_selected_equivalent_url_variant"
                    conflict_count += 1
                else:
                    status = "google_selected_different_canonical"
                    conflict_count += 1
            finding = {
                "page_url": item["page_url"],
                "status": status,
                "user_canonical": user,
                "google_canonical": google,
                "equivalent_url_variant": equivalent_variant,
                "verdict": item.get("verdict"),
                "coverage_state": item.get("coverage_state"),
                "last_crawled": item.get("last_crawled"),
            }
            if status != "canonical_matches" or include_matching:
                findings.append(finding)

        return _json(
            {
                "site_url": site_url,
                "requested": min(len(candidates), max_inspections),
                "matching_count": matching_count,
                "conflict_count": conflict_count,
                "incomplete_count": incomplete_count,
                "findings": findings,
                "inspection_errors": errors,
                "warnings": warnings,
            }
        )
    except Exception as exc:
        return _error("google_canonical_conflict_analysis_failed", str(exc))


async def get_search_appearance_performance(
    site_url: str,
    start_date: str,
    end_date: str,
    search_type: str = "WEB",
    appearance_filter: str | None = None,
    include_date_breakdown: bool = False,
    row_limit: int = 5_000,
) -> str:
    """Return Search Analytics performance grouped by search appearance."""
    try:
        dimensions: tuple[str, ...] = (
            ("date", "searchAppearance")
            if include_date_breakdown
            else ("searchAppearance",)
        )
        filters = [
            item
            for item in (_search_filter("searchAppearance", appearance_filter),)
            if item
        ]
        rows = _query_search_analytics(
            site_url=site_url,
            start_date=start_date,
            end_date=end_date,
            dimensions=dimensions,
            search_type=search_type,
            row_limit=row_limit,
            filters=filters,
        )
        return _json(
            {
                "site_url": site_url,
                "date_range": {"start": start_date, "end": end_date},
                "search_type": search_type.upper(),
                "include_date_breakdown": include_date_breakdown,
                "row_count": len(rows),
                "no_data": not rows,
                "message": (
                    "No search-appearance rows were returned for the selected period."
                    if not rows
                    else None
                ),
                "rows": rows,
            }
        )
    except Exception as exc:
        return _error("search_appearance_performance_failed", str(exc))

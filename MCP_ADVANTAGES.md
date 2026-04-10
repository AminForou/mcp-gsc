# What Our MCP Has That the Other Agent Lacks

## 1. Site Verification & Permission Details — `get_site_details`

Returns the full property profile from GSC: permission level, verification state, verified user, and verification method. The other agent has no equivalent — it can list properties but cannot answer questions like *"who verified this site?"* or *"what permission level do I have?"*.

---

## 2. Indexing Issue Triage — `check_indexing_issues`

Inspects up to 10 URLs in one call and automatically buckets them into categories:

- Not indexed
- Canonical mismatch
- Robots-blocked
- Fetch/crawl errors
- Indexed (healthy)

The other agent's `bulk_inspect_urls` returns raw inspection data for each URL. `check_indexing_issues` goes further by aggregating results into a structured issue report, making it faster to spot patterns across a batch of URLs without reading individual records.

---

## 3. Performance Overview with Built-in Trend — `get_performance_overview`

Fetches total clicks, impressions, average CTR, and average position for the property **and** a daily breakdown in a single call. The other agent requires separate calls (`get_search_analytics` for totals + `get_performance_trend` for the time series). This tool produces a ready-to-read summary in one shot.

---

## 4. Per-Page Query Breakdown — `get_search_by_page_query`

Given a specific page URL, returns all the queries driving traffic to that page ranked by clicks. The other agent has no dedicated equivalent — you would need to construct a filtered `get_search_analytics` call with `dimensions=query,page` and a page filter manually. This tool does that in one clean call and is purpose-built for page-level SEO audits.

---

## 5. Advanced Analytics with Pagination & Multi-Filters — `get_advanced_search_analytics`

Significantly more capable than the basic `get_search_analytics` available in both agents:

| Capability | Basic `get_search_analytics` | `get_advanced_search_analytics` |
|---|---|---|
| Max rows | ~20 (default) | Up to 25,000 |
| Pagination | No | Yes (`start_row`) |
| Multiple filters | No | Yes (JSON filter array with AND logic) |
| Search type | Web only | Web, Image, Video, News, Discover |
| Sort control | No | Any metric, ascending or descending |
| Custom date range | No (days offset only) | Yes (`start_date` / `end_date`) |
| Data state override | No | Yes (`all` or `final`) |

The other agent's `get_search_analytics` covers the basic case. `get_advanced_search_analytics` is required for bulk exports, multi-filter queries, or non-web search types.

---

## 6. Detailed Sitemap Inspection — `list_sitemaps_enhanced` + `get_sitemap_details`

The other agent's `get_sitemaps` lists submitted sitemaps with basic status. Our MCP adds:

- **`list_sitemaps_enhanced`** — includes last submitted date, last downloaded date, URL counts, error counts, warnings, and support for drilling into a sitemap index to list its child sitemaps.
- **`get_sitemap_details`** — fetches the full record for a single sitemap: type (sitemap vs. index), processing status, per-content-type URL counts, and all errors/warnings with descriptions.

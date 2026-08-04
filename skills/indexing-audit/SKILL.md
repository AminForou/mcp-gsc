---
name: indexing-audit
description: Audit indexing status across top pages. Use when asked about crawling,
  indexing issues, or whether pages are indexed by Google.
---

# Indexing Audit

Audit the indexing status of top pages and produce a prioritized action list.

## Steps

1. Call `gsc_list_properties` to confirm the exact `site_url`.
2. Call `gsc_query_search_analytics` with `dimensions=["page"]`, `page_size=20`,
   `sort_by="impressions"` to identify the 20 most-visible pages.
3. Extract the page URLs from the results.
4. Call `gsc_inspect_urls_batch` with up to 10 URLs at a time (API limit). Run
   twice if needed to cover all 20 pages. The tool uses concurrency 2 and
   tolerates partial failure — the summary reports succeeded/failed/
   indexed/not_indexed.
5. Categorize each URL by verdict:
   - Indexed (PASS)
   - Soft 404 / Excluded
   - Not indexed / Blocked
   - Canonical mismatch (Google chose a different canonical)
6. For each issue, surface the specific `coverage_state`, `page_fetch_state`,
   or `robots_txt_state`.

## Output format

Present a prioritized action list:

1. **Critical** — Not indexed pages that have impressions (visibility being lost)
2. **High** — Canonical mismatches on high-traffic pages
3. **Medium** — Robots.txt or fetch blocks
4. **Low** — Soft exclusions on low-traffic pages

Include a summary table: page URL | verdict | issue | recommended action.
URL Inspection shows current index state, not a full technical crawl — note
this limitation in the final report.

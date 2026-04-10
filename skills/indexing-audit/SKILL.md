---
name: indexing-audit
description: Audit indexing status across top pages. Use when asked about crawling,
  indexing issues, or whether pages are indexed by Google.
---

# Indexing Audit

Audit the indexing status of the top pages on a site and produce a prioritized action list.

## Steps

1. Call `list_properties` to confirm the exact `site_url`.
2. Call `get_search_analytics` with `dimensions=page`, `sort_by=impressions`, `row_limit=20` to identify the 20 most-visible pages.
3. Extract the list of page URLs from the results.
4. Call `batch_url_inspection` with up to 10 URLs at a time (API limit). Run twice if needed to cover all 20 pages.
5. Categorize each URL by verdict:
   - ✅ **Indexed** (PASS)
   - ⚠️ **Soft 404 / Excluded**
   - ❌ **Not indexed / Blocked**
   - 🔍 **Canonical mismatch** (Google chose a different canonical)
6. For each issue, provide the specific `coverageState`, `pageFetchState`, or `robotsTxtState` from the inspection.

## Output format

Present as a prioritized action list:

1. **Critical** — Not indexed pages that have impressions (visibility being lost)
2. **High** — Canonical mismatches on high-traffic pages
3. **Medium** — Robots.txt or fetch blocks
4. **Low** — Soft exclusions on low-traffic pages

Include a summary table: page URL | verdict | issue | recommended action.

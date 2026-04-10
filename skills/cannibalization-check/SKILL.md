---
name: cannibalization-check
description: Detect keyword cannibalization — queries where multiple pages compete
  for the same rankings. Use when asked about competing pages, keyword overlap, or cannibalization.
---

# Keyword Cannibalization Check

Identify queries where multiple pages on the same site are competing for rankings.

## Steps

1. Call `list_properties` to confirm the exact `site_url`.
2. Call `get_advanced_search_analytics` with `dimensions=query,page`, `sort_by=impressions`, `row_limit=1000` to get all query+page combinations.
3. Group rows by `query`. Queries with **two or more distinct pages** in the top results are cannibalization candidates.
4. For each cannibalizing query, collect: both page URLs, their individual clicks, impressions, CTR, and position.
5. Sort candidates by total impressions (most valuable cannibalization conflicts first).
6. Limit the output to the top 20 most severe cases.

## Output format

For each cannibalization case:
- **Query**: the competing keyword
- **Pages**: list each URL with its metrics
- **Severity**: High / Medium / Low based on impressions at stake
- **Recommendation**: which page to consolidate to (pick the one with better position or CTR), and whether to use a canonical, redirect, or content merge

Present as a markdown table followed by a prioritized action list.

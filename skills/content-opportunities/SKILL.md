---
name: content-opportunities
description: Find quick-win content optimization targets — high impressions, low CTR,
  position 11-20. Use when asked for content ideas or optimization opportunities.
---

# Content Opportunities

Surface quick-win content optimization targets: pages or queries sitting in positions 11–20 with high impression volume but low CTR.

## Steps

1. Call `list_properties` to confirm the exact `site_url`.
2. Call `get_advanced_search_analytics` with:
   - `dimensions=query,page`
   - `sort_by=impressions`
   - `sort_direction=descending`
   - `row_limit=1000`
   - `start_date` = 28 days ago, `end_date` = today
3. Filter the results to keep only rows where:
   - `position` is between **11 and 20** (page 2, just below the fold)
   - `impressions` > 100 (meaningful search volume)
   - `ctr` < 0.03 (3% — below average for these positions)
4. Sort the filtered set by `impressions` descending.
5. Return the top 20 rows.

## Output format

Present as a table: **Query | Page | Position | Impressions | CTR | Opportunity Score**

Opportunity Score = `impressions × (0.05 − ctr)` — a rough estimate of clicks gained if CTR reaches 5%.

Follow the table with specific recommendations for each entry:
- Title/meta description optimization ideas
- Whether to merge with a better-ranking page
- Whether to add internal links to boost the page

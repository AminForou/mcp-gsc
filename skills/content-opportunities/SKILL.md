---
name: content-opportunities
description: Find quick-win content optimization targets — high impressions, low
  CTR, striking-distance positions. Use when asked for content ideas or
  optimization opportunities.
---

# Content Opportunities

Surface quick-win optimization targets via `gsc_find_opportunities`.

## Steps

1. Call `gsc_list_properties` to confirm the exact `site_url`.
2. Call `gsc_find_opportunities` with the property and a 28-day window.
   Opportunity types:
   - `striking_distance` — position 4–15 with meaningful impressions.
   - `high_impression_low_ctr` — position 1–10 with CTR below the position
     baseline. The baseline version is surfaced in `meta`; treat it as a
     heuristic, not a hard truth.
   - `position_one_page_two` — position 8–20 with meaningful impressions.
   - `zero_click` — clicks = 0 with meaningful impressions.
3. Use `min_impressions` (default 100) to filter out noise.
4. Sort the results by impressions descending.

## Output format

Present a table: **Query | Page | Position | Impressions | CTR | Opportunity Type(s)**

Follow with specific, evidence-backed recommendations:
- Title/meta description improvements (grounded in search intent).
- Whether to merge with a better-ranking page.
- Whether internal links could help.
- Avoid guaranteed-outcome claims; GSC has no conversion data.

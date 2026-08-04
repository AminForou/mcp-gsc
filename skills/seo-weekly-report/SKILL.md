---
name: seo-weekly-report
description: Generate a complete weekly SEO performance report for a property.
  Use when asked for a site summary, performance overview, or weekly report.
---

# SEO Weekly Report

Generate a full SEO performance report for a Google Search Console property.

## Steps

1. Call `gsc_list_properties` to confirm the exact `site_url`.
2. Call `gsc_get_performance_overview` with `days=28` and `compare_previous=true`
   to retrieve totals (clicks, impressions, CTR, position), the daily trend,
   and device/country/search-appearance breakdowns. Totals come from a
   dimensionless query — they are NOT summed from daily rows.
3. Call `gsc_compare_periods` comparing the last 28 days against the prior
   28-day period with `dimensions=["query"]` and `limit=20`.
4. Flag any queries where `change.clicks_percent <= -20`.
5. Call `gsc_find_content_decay` to surface pages/queries that declined
   vs the prior same-length period (entry: `previous_clicks >= 10` and
   `clicks_percent <= -20%` or `impressions_percent <= -20%`).
6. Summarize all results in a structured report with:
   - Overall performance snapshot (totals + period-over-period change)
   - Alerts: queries with > 20% click decline
   - Top movers (winning and declining queries)
   - Decayed pages with impact scores

## Output format

Present the report as a clear markdown document with headings, a summary
table, and an action list. Note the data-state (`final` may lag 2–3 days)
and that GSC provides no conversion/revenue data. Avoid guaranteeing ranking
or traffic improvements — correlation is not causation.

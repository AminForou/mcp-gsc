---
name: seo-weekly-report
description: Generate a complete weekly SEO performance report for a site.
  Use when asked for a site summary, performance overview, or weekly report.
---

# SEO Weekly Report

Generate a full weekly SEO performance report for a Google Search Console property.

## Steps

1. Call `list_properties` to confirm the exact `site_url` to use.
2. Call `get_performance_overview` with `days=28` to retrieve totals (clicks, impressions, CTR, position) and the daily trend.
3. Call `compare_search_periods` comparing the last 28 days against the prior 28-day period, using `dimensions=query` and `limit=20`.
4. Flag any queries where clicks dropped by more than 20% between periods.
5. Call `get_search_analytics` with `dimensions=query` and `row_limit=10` to get the top 10 queries by clicks.
6. Summarize all results in a structured report with:
   - Overall performance snapshot (totals + period-over-period change)
   - Alerts: queries with >20% click decline
   - Top 10 queries by clicks
   - One-sentence recommendation for each alert

## Output format

Present the report as a clear markdown document with headings, a summary table, and an action list.

---
name: cannibalization-check
description: Detect possible keyword cannibalization — queries where multiple pages
  compete for the same rankings. Use when asked about competing pages, keyword overlap,
  or cannibalization. Results are a signal, not proof.
---

# Keyword Cannibalization Check (possible)

Identify queries where multiple pages on the same site may be competing.
Multiple URLs for one query is a **signal**, not proof of cannibalization
(see spec section 19).

## Steps

1. Call `gsc_list_properties` to confirm the exact `site_url`.
2. Call `gsc_find_cannibalization` with the property and a 28-day window. The
   tool fetches query+page rows, groups by query, and surfaces queries with
   >= 2 pages and `min_query_impressions` (default 100).
3. The tool already computes per-page impression/click share and a severity
   label. Review the `pages` array and `signals` for each candidate.
4. Prioritize candidates where impression share is split roughly evenly; a
   single page holding > 90% of impressions is flagged low or dropped.
5. Limit the output to the most valuable cases.

## Output format

For each candidate:
- **Query**: the competing keyword
- **Pages**: each URL with its impressions, share, and position
- **Severity**: High / Medium / Low (from the tool)
- **Signals**: e.g. `traffic_split`, `close_positions`
- **Recommendation**: investigate before acting — consider canonical, redirect,
  or content merge. Do NOT guarantee ranking improvements.

Present as a markdown table followed by a prioritized, evidence-backed action
list. Always note that cannibalization is a hypothesis requiring content review.

# Higher-level GSC SEO analysis tools

These tools extend the remote, read-only ChatGPT MCP surface. They use the
existing Search Console API credentials and property allowlist.

## Tool catalogue

| Tool | Purpose |
|---|---|
| `get_query_page_performance` | Paginated query-by-page clicks, impressions, CTR and position |
| `compare_query_page_periods` | Outer-join comparison of query-page rows across two periods |
| `find_query_cannibalisation` | Deterministic detection of queries with visibility split across pages |
| `inspect_url_index_status` | Single URL Inspection result under the requested naming contract |
| `batch_inspect_urls` | Multi-URL inspection with partial-result preservation |
| `list_sitemaps` | Submitted sitemap metadata |
| `get_sitemap_status` | Status and submitted/indexed counts for one sitemap |
| `compare_sitemap_to_gsc_pages` | Sitemap URLs versus pages observed in Search Analytics |
| `find_indexed_url_variants` | Variant groups from supplied, sitemap and Search Analytics candidates, enriched by URL Inspection |
| `find_google_canonical_conflicts` | Google-selected versus user-declared canonical comparison |
| `get_search_appearance_performance` | Performance grouped by Search Appearance |

## Accuracy constraints

- Search Analytics returns top rows. It is not an exhaustive index export and
  can omit anonymised or low-volume queries.
- URL Inspection only reports explicitly inspected URLs and is quota limited.
- `compare_sitemap_to_gsc_pages` compares sitemap URLs to pages observed in
  Search Analytics. A sitemap-only URL is not necessarily unindexed.
- `find_indexed_url_variants` is candidate-based because Google does not expose
  a complete list of all indexed URLs through the Search Console API.

## Sitemap fetch security

The sitemap reader:

- permits only HTTP and HTTPS;
- rejects embedded credentials;
- restricts targets to the configured Search Console property;
- rejects hosts resolving to loopback, private, link-local or other non-public addresses;
- revalidates redirects;
- limits downloaded XML to 10 MiB;
- limits sitemap-index recursion and total collected URLs.

## Suggested calls

### Query-page performance

```json
{
  "site_url": "sc-domain:makeuppalace.com.au",
  "start_date": "2026-06-15",
  "end_date": "2026-07-12",
  "row_limit": 10000
}
```

### Canonical conflicts from the current sitemap

```json
{
  "site_url": "sc-domain:makeuppalace.com.au",
  "sitemap_url": "https://www.makeuppalace.com.au/sitemap.xml",
  "max_sitemap_urls": 100,
  "max_inspections": 100
}
```

# Changelog

## [1.0.0] — 2026-08 — Fork redesign (gsc-seo-analyst-mcp)

This release is a **breaking redesign** of the package per the secure, read-only,
multi-client fork spec. The package is renamed from `mcp-search-console` to
**`gsc-seo-analyst-mcp`**. The old `mcp-gsc` / `mcp-search-console` console
scripts are replaced by `gsc-mcp`.

### Breaking changes

- **Read-only scope by default.** The OAuth scope is now
  `https://www.googleapis.com/auth/webmasters.readonly` (was the full
  `webmasters` scope). **Existing OAuth tokens are rejected at startup** —
  run `gsc-mcp auth login` to obtain a read-only token.
- **Write tools removed entirely.** `add_site`, `delete_site`, `submit_sitemap`,
  `delete_sitemap`, `manage_sitemaps`, `reauthenticate`, and `get_creator_info`
  are deleted. `GSC_ALLOW_DESTRUCTIVE` is removed. Sitemap/site changes require
  a code change and a separate release (by design).
- **stdio transport only.** SSE/HTTP transport and the DNS-rebinding-protection
  bypass have been removed. `MCP_TRANSPORT` must be `stdio` (the default); any
  other value exits with a clear error. Docker remote/SSE usage is no longer
  supported in v1.0.
- **No implicit credential discovery.** The server no longer searches the script
  directory or current working directory for credential files. Only
  `GSC_OAUTH_CLIENT_SECRETS_FILE`, `GSC_CREDENTIALS_PATH`, and `GSC_CONFIG_DIR`
  are consulted, and all must be **absolute paths**.
- **Explicit auth mode.** `GSC_SKIP_OAUTH` is removed. Use
  `GSC_AUTH_MODE=oauth|service_account`. Silent OAuth→service-account fallback
  is disabled — a clear error is preferred over unexpected credential selection.
- **Monolith split into a modular package** under `src/gsc_mcp/` (models,
  services, tools). The single-file `gsc_server.py` is removed.

### Correctness fixes

- **`orderBy` is never sent to Google.** The Search Analytics API does not
  support it; sorting is now performed client-side and the output notes that
  sorting applies only to the fetched set.
- **Request field is `type`, not `searchType`.**
- **Delta math is directionally correct.** `delta = current - previous`;
  `percent_change = (current - previous) / previous * 100` (null when previous
  is zero, with `status="new"`); `position_improvement = previous - current`
  (positive = rank got better); `current=0 & previous>0` → `status="lost"`.
- **Sitemap `submitted` vs `indexed` are distinct.** The previous code labeled
  `submitted` as `indexed_urls`; they are now separate fields.
- **Pacific Time default date math.** All default dates use
  `America/Los_Angeles`. A 28-day window is inclusive (`start = end - 27 days`).
  Strategic default: `data_state=final`, `end = current_PT - 3 days`.
  `data_state=all` flags potential incompleteness in the output.

### New tool set (13 tools, `gsc_` prefix)

`gsc_get_capabilities`, `gsc_list_properties`, `gsc_query_search_analytics`,
`gsc_get_performance_overview`, `gsc_compare_periods`, `gsc_analyze_page`,
`gsc_find_opportunities`, `gsc_find_content_decay`, `gsc_find_cannibalization`,
`gsc_inspect_url`, `gsc_inspect_urls_batch`, `gsc_list_sitemaps`,
`gsc_get_sitemap_details`.

All tools return a common `{ok, meta, data}` envelope; errors return
`{ok:false, error:{code, message, retryable, details}}` with a stable error
code set. All tools carry `readOnlyHint=true, destructiveHint=false,
idempotentHint=true, openWorldHint=true`.

### Client registry & property allowlist

Optional `clients.yaml` (point `GSC_CLIENTS_CONFIG` at an absolute path)
enforces that a property belongs to exactly one client. `gsc_list_properties`
intersects Google's properties with the registry, and every output includes
`client_id` / `client_name`. Duplicate properties across clients fail startup.
The registry must not contain credentials.

### Retry & error mapping

400/401/403/404 are not retried. 429 and 5xx get up to 3 retries with
exponential backoff + jitter; timeouts get a single retry. Raw exceptions
carrying credential paths are sanitized before reaching tool output.

### Logging & privacy

Logs include tool name, duration, status code, row count, retry count, and
internal error code. Token/credential contents, OAuth client secrets, and (by
default) user query text are never logged. `GSC_LOG_QUERY_VALUES` and
`GSC_LOG_PROPERTY_URLS` control the two opt-in sensitive fields.

### CLI

`gsc-mcp auth login | status | logout` handles authentication interactively
from the terminal — account switching no longer happens via an MCP tool.

---

## [0.3.3] — July 2026

- Pinned `mcp[cli]<2.0.0` to unbreak fresh installs (mcp SDK 2.0 removed
  `mcp.server.fastmcp`).

## [0.3.2] — April 2026

- OAuth browser flow fixed for uvx.
- `get_capabilities` tool added.
- Better auth error messages.

## [0.3.0] — April 2026

- Cursor Marketplace plugin with 4 bundled SEO skills.
- Stable token storage in platform user config dir.
- Structured JSON output for all data tools.

## [0.2.0] — March 2026

- Safety mode for destructive tools (disabled by default).
- HTTP/SSE transport for remote deployments.
- Dockerfile.

## [0.1.0] — Initial release

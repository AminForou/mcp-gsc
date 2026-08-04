# gsc-seo-analyst-mcp

A secure, **read-only**, multi-client [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for [Google Search Console](https://search.google.com/search-console/about) — built for SEO analytics via an AI agent.

> **Why read-only?** v1.0 deliberately exposes **no write operations** (no add/remove properties, no sitemap submit/delete, no indexing requests). The only OAuth scope requested is `webmasters.readonly`. Write operations require a code change and a separate release — by design.

---

## What's New in 1.0.0

A full fork redesign (package renamed from `mcp-search-console` to
`gsc-seo-analyst-mcp`). Highlights:

- **Read-only scope** — OAuth tokens are scoped to `webmasters.readonly`. Old
  full-scope tokens are rejected at startup.
- **13 `gsc_`-prefixed tools** with a common `{ok, meta, data}` envelope and
  stable error codes.
- **No `orderBy` / `searchType` in Google requests** — sorting is client-side,
  the request field is `type`. (Both were API-contract bugs in the old code.)
- **Directionally correct delta math** — `position_improvement` is positive
  when rank improves; `previous=0` yields `null` percent and `status="new"`.
- **Client registry & property allowlist** — prevents analyzing one client's
  property under another's name.
- **stdio transport only** — SSE/HTTP and the DNS-rebinding bypass removed.
- **No implicit credential discovery** — only explicit, absolute env-var paths.
- **`gsc-mcp auth login | status | logout`** CLI — account switching happens
  at the terminal, not via an MCP tool.

See [CHANGELOG.md](CHANGELOG.md) for the full breaking-change list.

---

## Tools (13)

| Tool | Purpose |
|---|---|
| `gsc_get_capabilities` | Server version, auth status, client count, active tools. |
| `gsc_list_properties` | List GSC properties intersected with the client allowlist. |
| `gsc_query_search_analytics` | General query with filters, pagination, client-side sort. |
| `gsc_get_performance_overview` | Totals (from a dimensionless query) + daily trend + breakdowns. |
| `gsc_compare_periods` | Compare two explicit periods; per-key current/previous/change. |
| `gsc_analyze_page` | Full analysis of one URL: queries, winning/declining, breakdowns. |
| `gsc_find_opportunities` | striking_distance / high_impression_low_ctr / position_one_page_two / zero_click. |
| `gsc_find_content_decay` | Pages/queries that declined vs the prior same-length period. |
| `gsc_find_cannibalization` | *Possible* cannibalization: queries split across multiple URLs. |
| `gsc_inspect_url` | Index/coverage status for one URL. |
| `gsc_inspect_urls_batch` | Up to 10 URLs, concurrency 2, partial-failure tolerant. |
| `gsc_list_sitemaps` | List sitemaps with distinct `submitted_urls` / `indexed_urls`. |
| `gsc_get_sitemap_details` | Details for one sitemap. |

---

## Getting Started

### Step 1 — Google API credentials

Pick one method.

**OAuth (interactive):**
1. [Google Cloud Console](https://console.cloud.google.com/) → create/select project.
2. [Enable the Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com).
3. Credentials → Create Credentials → **OAuth client ID** → **Desktop app**.
4. Download the JSON, save it somewhere permanent (e.g. `~/Documents/client_secrets.json`).

**Service account (automation):**
1. Same as above through step 2.
2. Credentials → Create Credentials → **Service account** → Keys tab → Add key → JSON.
3. Save the JSON key somewhere permanent (e.g. `~/Documents/service_account.json`).
4. Add the service account email to your GSC property: Search Console → Settings → Users and permissions → Add user.

### Step 2 — Install

**uvx (recommended):**

```bash
# install uv (macOS/Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
echo 'source $HOME/.local/bin/env' >> ~/.zshrc
```

Then point your MCP client at `uvx gsc-seo-analyst-mcp`.

**Clone (advanced):**

```bash
git clone https://github.com/AminForou/mcp-gsc.git
cd mcp-gsc
uv venv .venv
uv pip install -e .
```

> Requires **Python 3.11 or 3.12**.

### Step 3 — Authenticate (OAuth only)

Run the CLI once in a terminal:

```bash
GSC_OAUTH_CLIENT_SECRETS_FILE=/abs/path/client_secrets.json \
  gsc-mcp auth login
```

A browser window opens; after login a read-only token is stored. Service-account
users skip this step.

### Step 4 — Configure your MCP client

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):

OAuth:
```json
{
  "mcpServers": {
    "gsc": {
      "command": "/FULL/PATH/TO/uvx",
      "args": ["gsc-seo-analyst-mcp"],
      "env": {
        "GSC_AUTH_MODE": "oauth",
        "GSC_OAUTH_CLIENT_SECRETS_FILE": "/abs/path/client_secrets.json"
      }
    }
  }
}
```

Service account:
```json
{
  "mcpServers": {
    "gsc": {
      "command": "/FULL/PATH/TO/uvx",
      "args": ["gsc-seo-analyst-mcp"],
      "env": {
        "GSC_AUTH_MODE": "service_account",
        "GSC_CREDENTIALS_PATH": "/abs/path/service_account.json"
      }
    }
  }
}
```

> On macOS find uvx with `which uvx`. On Windows PowerShell:
> `Get-Command uvx | Select-Object -ExpandProperty Source`. GUI apps don't read
> your shell config, so use the **full path**.

### Step 5 — (Optional) Client registry

For multi-client work, copy `config/clients.example.yaml` to `clients.yaml`
and point `GSC_CLIENTS_CONFIG` at its absolute path. The registry enforces that
each property belongs to exactly one client and tags every output with
`client_id` / `client_name`. The registry must **not** contain credentials.

### Step 6 — Test

Ask your AI assistant: **"Call gsc_get_capabilities"** to verify auth and list
available tools, then **"List my GSC properties"**.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GSC_AUTH_MODE` | No | `oauth` | `oauth` or `service_account`. No silent fallback. |
| `GSC_OAUTH_CLIENT_SECRETS_FILE` | OAuth | — | Absolute path to OAuth client secrets JSON. |
| `GSC_CREDENTIALS_PATH` | Service account | — | Absolute path to service-account JSON key. |
| `GSC_CONFIG_DIR` | No | platform user dir | Absolute path to the token/config directory. |
| `GSC_CLIENTS_CONFIG` | No | — | Absolute path to `clients.yaml`. |
| `GSC_DEFAULT_DATA_STATE` | No | `final` | `final` (confirmed, 2-3 day lag) or `all` (dashboard, may be incomplete). |
| `GSC_DEFAULT_PAGE_SIZE` | No | `500` | Default rows per analytics query. |
| `GSC_MAX_PAGE_SIZE` | No | `5000` | Hard cap on `page_size`. |
| `GSC_MAX_ANALYSIS_ROWS` | No | `10000` | Cap on rows scanned in opportunity/decay analysis. |
| `GSC_INSPECTION_CONCURRENCY` | No | `2` | Concurrent URL inspections per batch. |
| `GSC_REQUEST_TIMEOUT_SECONDS` | No | `30` | Per-request timeout. |
| `MCP_TRANSPORT` | No | `stdio` | Must be `stdio` (other values exit with an error). |
| `GSC_LOG_LEVEL` | No | `INFO` | Logging level. |
| `GSC_LOG_QUERY_VALUES` | No | `false` | If true, log user query text. Off by default. |
| `GSC_LOG_PROPERTY_URLS` | No | `true` | If false, suppress property URLs from logs. |

All credential paths **must be absolute**.

---

## Limitations (surfaced to the AI agent)

- GSC does not expose every query (privacy/internal limits).
- The API may return top rows rather than all rows — even with pagination,
  completeness is not guaranteed. Tools carry this warning.
- `data_state=all` may be incomplete and is in flux.
- Average Position is not a live ranking.
- Detected cannibalization is a **signal**, not proof.
- GSC provides no conversion, revenue, backlink, or full-site crawl data.
- URL Inspection shows current index state, not a technical crawl substitute.
- Correlation does not imply causation for trends.

These are emitted in tool descriptions and the agent's final report.

---

## Contributing

Open an issue or PR on [GitHub](https://github.com/AminForou/mcp-gsc). Every PR
should: reference a requirement, include positive **and** negative tests, avoid
schema/contract changes without docs, justify new dependencies, keep secrets
out of fixtures, and pass `ruff`, `mypy`, `pytest --cov-fail-under=85`, and
`pip-audit`.

## License

MIT — see [LICENSE](LICENSE).

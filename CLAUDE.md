# CLAUDE.md

Context for AI coding assistants (Claude, Cursor, Copilot, etc.) working in this repo.

> **This is Klartika's fork. Read [`AGENTS.md`](AGENTS.md) before changing
> anything** — it carries rules that keep this fork rebaseable on upstream, and
> breaking them is easy to do by accident while following the sections below.
>
> The most important one: **never edit `gsc_server.py`.** All fork behaviour
> lives in `gsc_remote/`.

## What this is

Two servers in one repo:

- **Upstream's local (stdio) server** — `gsc_server.py`, a single ~1,700-line
  file built with FastMCP. Unmodified. The sections below describe it.
- **This fork's remote server** — `gsc_remote/`, an OAuth 2.1-protected HTTP
  transport where each user signs in with their own Google account. This is
  what is actually deployed. See [`AGENTS.md`](AGENTS.md) for its layout and
  [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for running it.

Per-request credentials reach upstream's unchanged tools through a runtime
monkeypatch of `get_gsc_service()` bound to a `ContextVar` — that is the single
seam between the two, and `tests/remote/credentials_test.py` guards it.

## Running locally

```bash
uv sync
uv run python gsc_server.py
```

## Auth

Two modes, tried in order:

1. **OAuth (default):** Place `client_secrets.json` in the repo root. On first run, a browser window opens for Google login. Token saved to `token.json` (gitignored), auto-refreshes when expired.
2. **Service account:** Set `GSC_CREDENTIALS_PATH` to the path of your service account JSON key file.

Set `GSC_SKIP_OAUTH=true` to force service account mode and skip OAuth entirely.

## Key environment variables

These are upstream's, for the local server. The remote server's are a different
set entirely — see [`DEPLOY.md`](DEPLOY.md).

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Set to `sse` for remote/Docker/network use |
| `MCP_HOST` | `127.0.0.1` | Host to bind when `MCP_TRANSPORT=sse` |
| `MCP_PORT` | `3001` | Port to bind when `MCP_TRANSPORT=sse` |
| `GSC_DATA_STATE` | `all` | `all` = matches GSC dashboard; `final` = confirmed data only (2–3 day lag) |
| `GSC_ALLOW_DESTRUCTIVE` | `false` | Set `true` to enable `add_site`, `delete_site`, `delete_sitemap` |
| `GSC_CREDENTIALS_PATH` | — | Path to service account JSON key file |
| `GSC_OAUTH_CLIENT_SECRETS_FILE` | `client_secrets.json` | Path to OAuth client secrets file |
| `GSC_SKIP_OAUTH` | `false` | Set `true` to skip OAuth and use service account only |

## Adding a new tool

**In this fork, don't** — not without deciding what it means for the remote
server first. Two things will stop you, both deliberately:

- Editing `gsc_server.py` breaks `AGENTS.md` rule 2 and makes every future
  upstream rebase harder.
- `tests/remote/tools_test.py` asserts the **exact** set of tools the remote
  server exposes. A new tool fails that test until it is explicitly classified
  as read or write. A write tool must not be exposed at all: the remote server
  holds only `webmasters.readonly`, so it would 403 at runtime — and it should
  never reach the model in the first place.

The upstream procedure, for working on the local server or for contributing
back to `AminForou/mcp-gsc`:

1. Add an `@mcp.tool()` decorated async function anywhere in `gsc_server.py`
2. Use `get_gsc_service()` for auth — it handles OAuth and service account automatically
3. Return `json.dumps(result)` not formatted text strings (LLMs work better with structured data)
4. Handle `HttpError` and return a plain string error message on failure

```python
@mcp.tool()
async def my_new_tool(site_url: str) -> str:
    """One-line description shown to the AI as the tool's purpose."""
    try:
        service = get_gsc_service()
        result = service.someApi().someMethod(siteUrl=site_url).execute()
        return json.dumps(result)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error: {str(e)}"
```

## Running tests

```bash
uv run pytest -q
```

Runs all 121 tests — upstream's `test_gsc_server.py` plus this fork's
`tests/remote/`. Passing in any file order.

`pytest test_gsc_server.py -v` is upstream's command and runs only 43 of them,
skipping every test covering the remote transport.

No credentials needed — all Google API calls are mocked.

## Docker

Two images, and the one you want is almost certainly the second.

Upstream's stdio server, from `Dockerfile`:

```bash
docker build -t mcp-gsc .
docker run -e MCP_TRANSPORT=sse -e MCP_PORT=3001 \
  -v /path/to/client_secrets.json:/app/client_secrets.json \
  -p 3001:3001 mcp-gsc
```

This fork's remote server, from `Dockerfile.remote` — the one published to GHCR
on a `v*` tag and actually deployed:

```bash
docker buildx build --platform linux/arm64 -f Dockerfile.remote -t gsc-mcp:test --load .
```

See [`DEPLOY.md`](DEPLOY.md) for the environment it needs.

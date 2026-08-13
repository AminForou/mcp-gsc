# Remote Google Search Console MCP server — design

**Date:** 2026-08-13
**Status:** approved for planning

## Goal

A remotely accessible, OAuth-protected MCP server for Google Search Console,
reachable from Claude at `https://<gsc-host>/mcp`, where each user signs in
with their own Google account. It joins the existing GTM and GA4 remote MCP
servers, but is deployed the newer `infra-ops` way rather than the way those two
were.

## Approach

Fork [`AminForou/mcp-gsc`](https://github.com/AminForou/mcp-gsc) (Python,
FastMCP, MIT, 1.4k stars, active — v0.3.3 in July 2026) to
`Klartika/gsc-mcp-server`, and add a remote OAuth 2.1 HTTP transport in new
files, mirroring what `Klartika/google-analytics-mcp` did to its own upstream.
Upstream's tool code is not edited, so the fork stays rebaseable.

Alternatives considered and rejected:

- **Write GSC tools from scratch.** The GSC API surface is small (sites,
  searchanalytics, sitemaps, urlInspection), but upstream's 21 tools include
  useful derived work (period comparison, batch URL inspection, indexing-issue
  triage) that we would otherwise reimplement. Rejected: more code, no upstream.
- **Fork and restructure** the 1705-line `gsc_server.py` into modules. Cleaner,
  but abandons rebaseability and makes us the owner of all future GSC API
  changes. Rejected: cost outweighs the tidiness.

## Repository layout

`Klartika/gsc-mcp-server`, forked from `AminForou/mcp-gsc` with `upstream`
remote configured.

Upstream files — treat as read-only:

- `gsc_server.py` — the FastMCP server and all 21 tools.
- `test_gsc_server.py`, `README.md`, `skills/`, `CHANGELOG.md`.

This fork adds (new files only):

| Path | Purpose |
| --- | --- |
| `gsc_remote/config.py` | env → `Config` dataclass. No deployment values in code. GA4 also carries an `ALLOWED_HOSTS` field that nothing reads; it is dropped here. |
| `gsc_remote/store.py` | `TokenStore`: SQLite (clients, tokens ↔ Google tokens, auth codes, federation states), WAL, survives restarts. |
| `gsc_remote/google.py` | Google federation: auth URL (`access_type=offline`, `prompt=consent`), code exchange, userinfo, `Credentials` builder. |
| `gsc_remote/credentials.py` | Request-scoped credentials `ContextVar` + the `get_gsc_service` monkeypatch (the credential seam). |
| `gsc_remote/allowlist.py` | Email / hosted-domain (`hd`) allowlist. Fails closed when unset; open mode needs `ALLOW_OPEN_ACCESS=true`. |
| `gsc_remote/statebinding.py` | HttpOnly `SameSite=Lax` cookie binding the Google federation leg to the initiating browser. |
| `gsc_remote/ratelimit.py` | Per-IP token bucket + body-size limit middleware. |
| `gsc_remote/provider.py` | `GoogleMCPProvider(OAuthAuthorizationServerProvider)`. |
| `gsc_remote/tools.py` | Startup filter that removes write and local-only tools from the FastMCP registry. |
| `gsc_remote/app.py` | Starlette wiring (SDK auth routes + `/oauth/callback` + authenticated `/mcp` + `/health`) and `main()`. |
| `tests/remote/*_test.py` | Test suite mirroring the GA4 fork's. |
| `Dockerfile.remote` | Image for the HTTP server. Additive — upstream's stdio `Dockerfile` is left alone. arm64, non-root, `/data` volume. |
| `.github/workflows/publish-image.yml` | Tag → GHCR image. |
| `AGENTS.md`, `DEPLOY.md` | Fork maintenance and deployment docs. |

`pyproject.toml` is the one upstream file that changes, additively and
minimally — the smallest possible rebase surface:

- Add deps: `starlette`, `uvicorn`, `httpx`.
- Raise the `mcp` lower bound from `>=1.3.0` to `>=1.28.1` (the OAuth framework
  in `mcp.server.auth` needs it), keeping `<2.0.0`.
- Add `packages = ["gsc_remote"]` alongside the existing
  `py-modules = ["gsc_server"]`.
- Add console script `gsc-mcp-http = "gsc_remote.app:main"`.
- Add dev extras: `pytest`, `pytest-asyncio`, `respx`.

## Hard rules

1. **Public repository — no identifiable information.** No real domains, emails,
   hostnames, secrets or tokens in code, tests or docs. Use RFC-reserved
   placeholders (`example.com`, `<your-host>`). Deployment values come only from
   environment variables set by the deploy workflow.
2. **Stay rebaseable on upstream.** Do not edit `gsc_server.py`. All fork
   behaviour lives in `gsc_remote/`; the only seams into upstream are runtime
   monkeypatches, not source edits. Periodically
   `git fetch upstream && git rebase upstream/main`.
3. **Never commit to `main`.** Branch, PR, merge — even for docs.
4. **TDD.** Failing test first, then implementation. Keep the suite green.

This document obeys rule 1: `<gsc-host>` stands for the real public hostname,
which lives only in `infra-ops` and the Google Cloud OAuth client. Secrets live
only in Infisical.

## Architecture

### Request flow

```
Claude ──▶ NPM (TLS, <gsc-host>)
            │
            ▼
        Starlette app (gsc_remote/app.py)
            ├── /health
            ├── /.well-known/oauth-protected-resource   (RFC 9728)
            ├── SDK auth routes  (authorize, token, register, revoke)
            ├── /oauth/callback  ← Google federation return
            └── /mcp  [RequireAuthMiddleware]
                     │  look up access token → Google credentials
                     │  bind ContextVar
                     ▼
                 StreamableHTTPSessionManager(app=gsc_server.mcp._mcp_server)
                     ▼
                 upstream tool → get_gsc_service() → patched → per-user service
```

### OAuth model

The server is both an OAuth 2.1 **authorization server** to the MCP client and
an OAuth **client** to Google. `GoogleMCPProvider` implements the MCP SDK's
`OAuthAuthorizationServerProvider`: it issues its own client registrations,
authorization codes and access tokens, and stores each token's Google
access/refresh pair alongside it in SQLite. Dynamic client registration is
enabled so Claude can register itself.

Access-token TTL defaults to 24 h (`ACCESS_TOKEN_TTL_SECONDS`). Google refresh
tokens are obtained with `access_type=offline` + `prompt=consent` and used to
refresh silently.

### Credential seam

Upstream resolves credentials through one function, `get_gsc_service()`
(`gsc_server.py:107`), called by every tool. `gsc_remote/credentials.py` captures
the original and rebinds the module attribute:

```python
def _patched_get_gsc_service():
    creds = current_credentials.get()
    if creds is not None:
        return build("searchconsole", "v1", credentials=creds,
                     cache_discovery=False)
    return _original_get_gsc_service()
```

A `ContextVar` makes this concurrency-safe — each request sees only its own
credentials — and the fallback keeps upstream's stdio mode working unchanged.

### FastMCP integration risk

The GA4 fork wraps a low-level `Server` (`coordinator.app`). Upstream mcp-gsc is
a `FastMCP` instance, whose low-level server is the private attribute
`mcp._mcp_server`. `StreamableHTTPSessionManager` needs that low-level object.

This is the one place we depend on a private upstream/SDK attribute. Mitigation:
a dedicated test asserts `gsc_server.mcp._mcp_server` exists and is a
`mcp.server.lowlevel.Server`, so a rebase that changes it fails loudly in CI
rather than at runtime.

### Tool surface — read-only

Requested scopes: `openid`, `email`,
`https://www.googleapis.com/auth/webmasters.readonly`.

At startup `gsc_remote/tools.py` removes 8 of upstream's 21 tools from the
FastMCP registry rather than editing upstream:

| Removed | Reason |
| --- | --- |
| `add_site`, `delete_site` | write — 403 under readonly |
| `submit_sitemap`, `delete_sitemap`, `manage_sitemaps` | write — 403 under readonly |
| `reauthenticate`, `get_capabilities` | local-file-auth diagnostics, meaningless remotely |
| `get_creator_info` | upstream promotional tool |

The 13 remaining tools: `list_properties`, `get_site_details`,
`get_search_analytics`, `get_advanced_search_analytics`,
`get_performance_overview`, `compare_search_periods`, `get_search_by_page_query`,
`get_sitemaps`, `list_sitemaps_enhanced`, `get_sitemap_details`,
`inspect_url_enhanced`, `batch_url_inspection`, `check_indexing_issues`.

A test asserts the exact registered tool-name set, so an upstream rebase that
adds a write tool fails CI instead of silently exposing it.

### Access control

Sign-in is gated by `ALLOWED_GOOGLE_DOMAINS` (Google `hd` claim) and
`ALLOWED_EMAILS`. Both unset **refuses every sign-in** — an unset allowlist is
far more often a forgotten environment variable than a decision to admit every
Google account. Running open requires `ALLOW_OPEN_ACCESS=true`. The allowlist is
re-evaluated on every token refresh, not only at sign-in, because refresh tokens
here do not expire.

The Google federation leg is bound to the initiating browser by an HttpOnly,
`SameSite=Lax` cookie whose hash is stored beside the state row. Without that
binding, open dynamic client registration lets an attacker mint a state, lure a
victim through consent, and receive an authorization code backed by the victim's
Google credentials.

Per-IP token-bucket rate limiting and a request body-size cap sit in front of
everything. `TRUST_PROXY=true` behind NPM so `X-Forwarded-For` is honoured.

### Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `PORT` | `8080` | |
| `BASE_URL` | `http://localhost:8080` | Public HTTPS URL, no trailing slash |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | Secret |
| `JWT_SECRET` | — | Secret, `openssl rand -base64 32` |
| `ALLOWED_GOOGLE_DOMAINS` / `ALLOWED_EMAILS` | empty | Empty ⇒ all sign-ins refused |
| `ALLOW_OPEN_ACCESS` | `false` | Explicit opt-in to running with no allowlist |
| `ACCESS_TOKEN_TTL_SECONDS` | `86400` | |
| `TRUST_PROXY` | `false` | `true` behind NPM |
| `TOKEN_DB_PATH` | `/data/tokens.db` | |
| `LOG_LEVEL` | `info` | |

## Deployment

Follows the `infra-ops` GitOps convention, not the older GTM/GA4 pattern
(compose in the app repo, host builds, secrets typed into Portainer's UI). The
`infra-ops` README names that older pattern as the thing it replaced.

Since an `infra-ops` stack clones only `infra-ops`, it cannot build from the app
repo — so the app repo must publish an image.

### App repo

`.github/workflows/publish-image.yml`: on a `v*` tag, buildx builds
`Dockerfile.remote` → `ghcr.io/klartika/gsc-mcp-server:vX.Y.Z` plus a
`sha-<short>` tag. Platform `linux/arm64` — the Portainer host is ARM.

### infra-ops repo

- `gsc-mcp/docker-compose.yml` — service `mcp-google-search-console`, pinned
  `image:` tag (never `:latest`), external `docker_bridge` network,
  `mcp_gsc_data:/data` volume, stdlib-urllib healthcheck against `/health`,
  json-file logging with rotation. `BASE_URL=https://<gsc-host>` and other
  non-secrets sit literally in the compose (hostnames already do — see
  `grafana-loki/`); secrets are `${VAR:-}` refs with empty-safe defaults.
- `gsc-mcp/README.md` — secrets, Google Cloud setup, NPM configuration.
- `.github/workflows/deploy-gsc-mcp.yml` — copied from
  `deploy-grafana-loki.yml`, `paths: gsc-mcp/**`. Logs into Infisical, fetches
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `JWT_SECRET`,
  `ALLOWED_GOOGLE_DOMAINS`, `ALLOWED_EMAILS` from `/gsc-mcp/` plus the shared
  root `GITHUB_PAT`, `GITHUB_USERNAME`, `PORTAINER_API_TOKEN`, then calls
  `PUT /stacks/{id}/git/redeploy` — never `PUT /stacks/{id}`, which silently
  detaches a git-linked stack.
- Root `README.md` stacks table and `AGENTS.md` table updated in the same PR.
- New Infisical folder `/gsc-mcp/` under project `infra-ops`, `prod`.

### Google Cloud (human step)

In the GCP project that already backs GTM and GA4:

1. Enable the **Google Search Console API**.
2. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   type **Web application**, named for this server.
3. Authorized redirect URI: `https://<gsc-host>/oauth/callback`.
4. Ensure the consent screen offers
   `https://www.googleapis.com/auth/webmasters.readonly`.
5. Put the client ID and secret into Infisical `/gsc-mcp/`.

A dedicated client (not GA4's) keeps consent screens and token revocation
per-server.

### Nginx Proxy Manager

Proxy host `<gsc-host>` → `mcp-google-search-console:8080`, websockets on,
SSL with force-SSL. Advanced config:

```nginx
proxy_buffering off;
proxy_read_timeout 3600s;
```

Without this, streamed `text/event-stream` responses hang. Also ensure
`X-Forwarded-Proto` is forwarded, or the `/mcp` → `/mcp/` 307 downgrades to
`http://` and the Claude handshake breaks. Keep the record DNS-only (grey cloud)
if the zone is on Cloudflare.

### Bootstrap

`git/redeploy` needs an existing git-linked stack, so the first creation is
manual: Portainer → Stacks → Add stack → Repository → `infra-ops`, compose path
`gsc-mcp/docker-compose.yml`, **no environment variables**. The empty-safe
`${VAR:-}` defaults let the stack come up; the container fails its healthcheck
until the first workflow run lands the real secrets. Record the resulting stack
ID in `deploy-gsc-mcp.yml`.

Do not enable Portainer's own automatic-update polling — the workflow's
`paths:` trigger does the path-scoping GitHub's repo-scoped webhook cannot.

### Release flow

Tag the app repo → image publishes to GHCR → bump the pinned tag in
`gsc-mcp/docker-compose.yml` → push → `deploy-gsc-mcp.yml` redeploys.

## Testing

`tests/remote/`, mirroring the GA4 fork: `config_test`, `store_test`,
`google_test`, `allowlist_test`, `ratelimit_test`, `provider_test`, `app_test`
(401 without a token, protected-resource metadata shape, `/health`), plus two
new to this fork:

- `credentials_test` — the `get_gsc_service` patch is idempotent, returns a
  per-request service, falls back to the original when no ContextVar is set, and
  isolates concurrent requests.
- `tools_test` — the registered tool-name set equals the 13 above; the private
  `mcp._mcp_server` attribute exists and is a low-level `Server`.

Post-deploy verification:

```bash
curl https://<gsc-host>/health
curl https://<gsc-host>/.well-known/oauth-protected-resource
curl -i -X POST https://<gsc-host>/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'   # expect 401
```

Then connect from Claude (Settings → Connectors → Add custom connector,
`https://<gsc-host>/mcp`) and call `list_properties`.

### Final security review

A narrow security pass runs on **Fable** at the end, scoped to the auth surface
this fork actually wrote — `gsc_remote/provider.py`, `store.py`, `google.py`,
`app.py`, `allowlist.py`, `ratelimit.py`, `credentials.py`. Not upstream's
`gsc_server.py`, not the deployment YAML. Everything else (pytest, ordinary
review) runs on the default model.

## Out of scope

- Retrofitting GTM and GA4 onto the `infra-ops` pattern. Worth doing; track as
  separate issues once this proves out.
- Write access to GSC. Revisiting means a new scope, a new consent, and
  restoring the removed tools.
- Publishing this fork to the MCP registry.

# AGENTS.md — maintenance guide

Guidance for humans and AI coding agents working on **this fork** of
`AminForou/mcp-gsc`. Read this before making changes.

## What this fork adds

Upstream is a **local (stdio)** MCP server for Google Search Console. This fork
adds an optional **remote, OAuth 2.1-protected HTTP transport**: a self-hostable
server where each user signs in with their **own Google account**
(`webmasters.readonly`) — no service accounts, no credential files on disk. It
is built on the MCP Python SDK's OAuth framework (`mcp.server.auth`), federates
to Google, persists sessions in SQLite, and ships as a container image.

All of this lives in **new files** under `gsc_remote/`. The upstream server and
its tools are unchanged.

## Hard rules (do not break these)

1. **Public repository — no identifiable information.** Never commit real
   domains, emails, hostnames, company names, secrets or tokens. Use only
   RFC-reserved placeholders (`example.com`, `<your-host>`). Deployment values
   are supplied **only** via environment variables set by the deployment.
2. **Stay rebaseable on upstream.** Do **not** edit `gsc_server.py`. Put all
   fork behaviour in `gsc_remote/`. The seams into upstream are runtime
   monkeypatches, not source edits. Periodically:
   `git fetch upstream && git rebase upstream/main`.

   Two documented exceptions, both in `README.md`, both cheap to re-apply:
   the orientation banner at the top (upstream's README describes the local
   stdio server, which would otherwise be the only thing a reader sees), and
   the removal of upstream's advertisements for a competing hosted GSC MCP
   service. Nothing else in an upstream file changes. On a rebase, keep the
   banner, drop re-introduced ads, take upstream's changes in between.
3. **Never commit to `main`.** Always work on a branch, open a PR, merge the PR
   — even for docs.
4. **TDD.** Write a failing test first, then the implementation. Keep the suite
   green.

## Repository layout

Upstream (treat as read-only): `gsc_server.py`, `test_gsc_server.py`,
`README.md`, `skills/`, `CHANGELOG.md`, `Dockerfile`.

This fork's additions (`gsc_remote/`):

- `config.py` — env → `Config`. Allowlist/secret values come only from env.
- `store.py` — `TokenStore`: SQLite persistence (clients, tokens↔Google tokens,
  auth codes, federation states), WAL mode, survives restarts.
- `credentials.py` — request-scoped Google credentials `ContextVar` + the
  monkeypatch of `gsc_server.get_gsc_service` (the credential seam).
- `google.py` — Google federation: auth URL (`access_type=offline`,
  `prompt=consent`), code exchange, userinfo, `Credentials` builder.
- `allowlist.py` — email / hosted-domain (`hd`) allowlist; open mode + warning
  when unset.
- `ratelimit.py` — per-IP token bucket + body-size limit middleware.
- `provider.py` — `GoogleMCPProvider(OAuthAuthorizationServerProvider)`.
- `tools.py` — startup filter removing write and local-only tools.
- `app.py` — Starlette wiring and `main()`. Console script `gsc-mcp-http`.

- `statebinding.py` — cookie that ties the Google federation leg to the
  browser that began it.

Tests: `tests/remote/*_test.py`. Run them with `uv run pytest -q`.

Docs: `DEPLOY.md` (first-time setup), `docs/OPERATIONS.md` (running it, and
what to do when it breaks), `docs/superpowers/specs/` (why it is built this
way). Image: `Dockerfile.remote`. Deployment lives in
the `Klartika/infra-ops` repo under `gsc-mcp/`.

## Security posture

The remote layer was reviewed against its auth surface before first deploy.
Decisions worth knowing before you change them:

- **The allowlist fails closed.** With neither `ALLOWED_GOOGLE_DOMAINS` nor
  `ALLOWED_EMAILS` set, sign-in is refused. Running open is possible but has to
  be asked for with `ALLOW_OPEN_ACCESS=true`. Do not "fix" the refusal by
  defaulting it back to permissive.
- **Federation state is cookie-bound** (`gsc_remote/statebinding.py`). Removing
  the cookie check reopens authorization-code injection — an attacker can
  otherwise obtain a token backed by a victim's Google credentials. The cookie
  must stay `SameSite=Lax`; `Strict` breaks Google's cross-site redirect back.
- **Rate limiting reads the rightmost `X-Forwarded-For` entry**, because Nginx
  appends the peer address and the leftmost value is client-supplied. This
  assumes exactly one trusted proxy hop. A second proxy means skipping that
  many entries from the right.
- **The allowlist is re-checked on every refresh**, since refresh tokens here
  do not expire. `email` and `hd` are stored alongside `subject` for this.
  Note the residual window: an already-issued access token stays valid until it
  expires, so removing someone from the allowlist cuts them off within
  `ACCESS_TOKEN_TTL_SECONDS` (24 h by default), not instantly. Lower the TTL if
  that window matters more than re-authentication frequency.
- **uvicorn's `proxy_headers` follows `TRUST_PROXY`.** Do not set it
  unconditionally: with `TRUST_PROXY=false` uvicorn would still derive
  `request.client` from a client-supplied `X-Forwarded-For`, which is precisely
  the value the rate limiter falls back to.

Accepted, not fixed: Google access and refresh tokens are stored **unencrypted**
in `tokens.db`. Encrypting them would put the key in the same environment as the
database, so anyone who can read the volume can almost certainly read the key —
the protection would be nominal. Treat the `/data` volume as secret material:
do not copy it off the host, and do not include it in backups that travel.

## Two things that will break on an upstream rebase

- `gsc_server.get_gsc_service` — the single chokepoint every tool calls, and the
  function `gsc_remote/credentials.py` patches. `tests/remote/credentials_test.py`
  fails loudly if it moves.
- `gsc_server.mcp._mcp_server` — the private low-level `Server` inside FastMCP
  that `app.py` hands to `StreamableHTTPSessionManager`.
  `tests/remote/tools_test.py` asserts it exists.

If upstream adds a tool, `tests/remote/tools_test.py` fails on the exact-name-set
assertion. That is deliberate: decide explicitly whether the new tool is
read-only before exposing it.

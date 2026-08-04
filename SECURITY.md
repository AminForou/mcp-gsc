# Security Policy

## Scope

`gsc-seo-analyst-mcp` is a **read-only** Model Context Protocol (MCP) server
for Google Search Console. Version 1.0 deliberately exposes **no write
operations**: no adding/removing properties, no submitting/deleting sitemaps,
no indexing requests, no content modification. The only OAuth scope requested
is `https://www.googleapis.com/auth/webmasters.readonly`.

## Reporting a Vulnerability

Report security issues privately by emailing **aio@aminforoutan.com**. Do **not**
open a public GitHub issue for security reports.

- Acknowledgement: within 48 hours.
- Initial assessment: within 5 business days.
- Coordinated disclosure: we publish a fix and advisory after a fix is
  available, crediting reporters who wish to be named.

Please include, where possible: a description of the impact, reproduction
steps, the affected version, and any relevant logs (redacted of credentials).

## Credential Storage

- **OAuth tokens** are stored at the path resolved from `GSC_CONFIG_DIR` (or the
  platform user config directory). On POSIX systems the file is set to `0600`.
- **Service-account JSON keys** and **OAuth client secrets** are read only from
  the absolute paths you provide via `GSC_CREDENTIALS_PATH` and
  `GSC_OAUTH_CLIENT_SECRETS_FILE`. The server never searches the project
  directory or current working directory for credentials.
- **Never commit credentials to the repository.** `.gitignore` ignores the
  common credential filenames. Treat any `clients.yaml` with real property
  lists as sensitive — a `.example` file is shipped for reference.

## Token Scope Enforcement

On startup, an OAuth token granted the full `webmasters` scope (from a prior
version) is **rejected**. Run `gsc-mcp auth login` to obtain a read-only token.
This prevents silent reuse of over-privileged tokens after the scope downgrade.

## Logging

By default the server logs tool name, duration, HTTP status code, row counts,
retry counts, and internal error codes. It does **not** log:

- access/refresh tokens or the full credential JSON,
- the OAuth client secret,
- full Search Analytics output,
- user query text (unless `GSC_LOG_QUERY_VALUES=true`).

`GSC_LOG_PROPERTY_URLS` (default `true`) controls whether property URLs appear
in logs. Set it to `false` for stricter privacy.

## Transport

Only `stdio` transport is supported in v1.0. Streamable HTTP/SSE and the
DNS-rebinding-protection bypass have been removed — there is no remote attack
surface in this version.

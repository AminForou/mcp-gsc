# ChatGPT MCP deployment and authentication

The remote entrypoint is `chatgpt_server.py`. The legacy `gsc_server.py` entrypoint
remains unchanged for local stdio clients.

## Authentication modes

| `MCP_AUTH_MODE` | Purpose |
|---|---|
| `oauth` | Embedded single-owner OAuth 2.1 authorization-code flow with PKCE `S256` and dynamic client registration. This is the default for the private Cloud Run deployment. |
| `oauth_local` | Shared-secret JWT validation mode for private deployments without a JWKS-based IdP. |
| `external_jwt` | Resource-server-only mode for an established IdP that issues JWT access tokens through a JWKS endpoint. |
| `none` | Local testing only. Never expose this mode on public Cloud Run ingress. |

The embedded mode is deliberately limited to a private, single-owner deployment. For
multiple users, multiple Cloud Run instances, enterprise SSO, durable revocation, or
high-availability authorization, use `external_jwt` with an established authorization
server instead.

## Embedded OAuth runtime contract

- Streamable HTTP endpoint: `POST/GET/DELETE /mcp`
- Health endpoint: `GET /health`
- Readiness endpoint: `GET /ready`
- Protected-resource metadata: `GET /.well-known/oauth-protected-resource`
- Authorization-server metadata: `GET /.well-known/oauth-authorization-server`
- OpenID-compatible discovery alias: `GET /.well-known/openid-configuration`
- Dynamic client registration: `POST /oauth/register`
- Authorization endpoint: `GET/POST /oauth/authorize`
- Token endpoint: `POST /oauth/token`
- Grants: `authorization_code` and rotating `refresh_token`
- PKCE: only `code_challenge_method=S256`
- Token endpoint client authentication: public clients (`none`)

The server binds authorization codes, access tokens, and refresh tokens to the exact
configured OAuth resource. It validates issuer, audience, expiry, subject, client ID,
required scopes, registered redirect URI, and PKCE verifier before accepting a token.
Redirect URIs must be exact-match registered and their host must be on
`OAUTH_ALLOWED_REDIRECT_HOSTS`.

Authorization-code and refresh-token replay is rejected by an in-process one-time-use
guard. The deployment script therefore enforces `MAX_INSTANCES=1`. This guard is not
a substitute for a durable authorization server in a horizontally scaled deployment.

## Required configuration

Copy `.env.chatgpt.example` to `.env.chatgpt` and set:

```text
MCP_PUBLIC_BASE_URL
MCP_REQUIRED_SCOPES
OAUTH_ALLOWED_EMAILS
GSC_ALLOWED_PROPERTIES
```

Auth mode options:

- `MCP_AUTH_MODE=oauth` (default embedded authorization server):
  - Uses `OAUTH_TOKEN_SECRET` and `OAUTH_ADMIN_PASSWORD` (from Secret Manager)
- `MCP_AUTH_MODE=external_jwt`:
  - `MCP_OAUTH_ISSUER`
  - `MCP_OAUTH_JWKS_URI`
  - Optional: `MCP_OAUTH_AUDIENCE` (defaults to `MCP_PUBLIC_BASE_URL`)
- `MCP_AUTH_MODE=oauth_local`:
  - `MCP_OAUTH_TOKEN_SECRET` or `OAUTH_TOKEN_SECRET`
  - Optional: `MCP_OAUTH_AUDIENCE` (defaults to `MCP_PUBLIC_BASE_URL`)
  - Optional: `OAUTH_ALLOWED_EMAILS` for email-claim allowlisting

Create and mount these values from Google Secret Manager rather than storing them in
`.env.chatgpt`:

```text
OAUTH_TOKEN_SECRET
OAUTH_ADMIN_PASSWORD
```

`OAUTH_TOKEN_SECRET` must contain at least 32 random bytes. The authorization password
must contain at least 12 characters; use a generated password rather than an account
password reused elsewhere.

## Google Search Console access

The ChatGPT OAuth token authenticates ChatGPT to this MCP server. It is not forwarded
to Google. The server independently accesses Search Console with the Cloud Run runtime
service account through Application Default Credentials.

Add the runtime service account email as a Search Console user on every exact property
listed in `GSC_ALLOWED_PROPERTIES`:

```text
Search Console -> Settings -> Users and permissions -> Add user
```

For the domain property used by this deployment:

```text
sc-domain:makeuppalace.com.au
```

## Local verification without OAuth

```bash
export MCP_AUTH_MODE=none
export MCP_REQUIRE_PROPERTY_ALLOWLIST=false
export GSC_GOOGLE_AUTH_MODE=adc
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/service-account.json"
uv run mp-gsc-mcp-http
```

Connect MCP Inspector to `http://127.0.0.1:8080/mcp`. Do not deploy this configuration.

## External JWT compatibility

The previous resource-server-only implementation remains available:

```text
MCP_AUTH_MODE=external_jwt
MCP_PUBLIC_BASE_URL=https://YOUR_DEPLOYED_HOST
MCP_OAUTH_ISSUER=https://YOUR-OAUTH-ISSUER.example.com/
MCP_OAUTH_JWKS_URI=https://YOUR-OAUTH-ISSUER.example.com/.well-known/jwks.json
MCP_OAUTH_AUDIENCE=https://YOUR_DEPLOYED_HOST
MCP_OAUTH_ALGORITHMS=RS256
MCP_REQUIRED_SCOPES=gsc.read
```

## Verification

After deployment:

```bash
PUBLIC_URL="https://YOUR_DEPLOYED_HOST"

curl -fsS "$PUBLIC_URL/health" | jq .
curl -fsS "$PUBLIC_URL/.well-known/oauth-protected-resource" | jq .
curl -fsS "$PUBLIC_URL/.well-known/oauth-authorization-server" | jq .
curl -i -X POST "$PUBLIC_URL/mcp"
```

The unauthenticated MCP request must return `401` with a `WWW-Authenticate` challenge
that references the protected-resource metadata. Link the server in ChatGPT using:

```text
https://YOUR_DEPLOYED_HOST/mcp
```

# ChatGPT plugin deployment

This fork includes a separate remote entrypoint, `chatgpt_server.py`. The legacy
`gsc_server.py` entrypoint remains available for stdio clients.

## Runtime contract

- Streamable HTTP endpoint: `POST/GET/DELETE /mcp`
- Health endpoint: `GET /health`
- Readiness endpoint: `GET /ready`
- OAuth protected-resource metadata: `GET /.well-known/oauth-protected-resource`
- OAuth access tokens are validated for signature, issuer, audience, expiry and scope.
- The remote tool surface is read-only.
- `GSC_ALLOWED_PROPERTIES` restricts which Search Console properties can be queried.
- Google API access uses Application Default Credentials by default.

## Required environment variables

Copy `.env.chatgpt.example` and configure:

```text
MCP_PUBLIC_BASE_URL
MCP_OAUTH_ISSUER
MCP_OAUTH_JWKS_URI
MCP_OAUTH_AUDIENCE
MCP_REQUIRED_SCOPES
GSC_ALLOWED_PROPERTIES
```

The OAuth authorization server must publish OAuth/OIDC discovery metadata, support
authorization code with PKCE S256, accept ChatGPT's registered client mode, preserve
the `resource` parameter, and mint an access token whose audience matches
`MCP_OAUTH_AUDIENCE`.

## Google Search Console access

Add the Cloud Run runtime service account email as a user on every property listed in
`GSC_ALLOWED_PROPERTIES`:

```text
Search Console -> Settings -> Users and permissions -> Add user
```

For a domain property, use the exact identifier:

```text
sc-domain:makeuppalace.com.au
```

## Local verification without OAuth

OAuth may be disabled only for local MCP Inspector testing:

```bash
export MCP_AUTH_MODE=none
export MCP_REQUIRE_PROPERTY_ALLOWLIST=false
export GSC_GOOGLE_AUTH_MODE=adc
export GOOGLE_APPLICATION_CREDENTIALS="$PWD/service-account.json"
uv run mp-gsc-mcp-http
```

Then connect MCP Inspector to:

```text
http://127.0.0.1:8080/mcp
```

Never deploy `MCP_AUTH_MODE=none` to a public Cloud Run service.

## Cloud Run deployment outline

The Cloud Run service must be publicly reachable at the network layer because
ChatGPT is the caller. Authentication is enforced by the MCP OAuth middleware.
Use `--allow-unauthenticated` for Cloud Run ingress and do not confuse that setting
with application-level authorization.

```bash
PROJECT_ID="YOUR_PROJECT_ID"
REGION="australia-southeast1"
SERVICE="mp-gsc-mcp"
RUNTIME_SA="mp-gsc-mcp@${PROJECT_ID}.iam.gserviceaccount.com"

PUBLIC_URL="https://YOUR_DEPLOYED_HOST"
OAUTH_ISSUER="https://YOUR-OAUTH-ISSUER.example.com/"
JWKS_URI="https://YOUR-OAUTH-ISSUER.example.com/.well-known/jwks.json"

gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --set-env-vars "MCP_AUTH_MODE=oauth,MCP_PUBLIC_BASE_URL=${PUBLIC_URL},MCP_OAUTH_ISSUER=${OAUTH_ISSUER},MCP_OAUTH_JWKS_URI=${JWKS_URI},MCP_OAUTH_AUDIENCE=${PUBLIC_URL},MCP_REQUIRED_SCOPES=gsc.read,GSC_ALLOWED_PROPERTIES=sc-domain:makeuppalace.com.au,GSC_GOOGLE_AUTH_MODE=adc,GSC_SKIP_OAUTH=true"
```

After deployment, verify:

```bash
curl -fsS "$PUBLIC_URL/health"
curl -fsS "$PUBLIC_URL/.well-known/oauth-protected-resource" | jq .
curl -i -X POST "$PUBLIC_URL/mcp"
```

The unauthenticated `/mcp` request should return `401` and a `WWW-Authenticate`
challenge referencing the protected-resource metadata.

# Cloud Run deployment runbook

This runbook deploys the ChatGPT-compatible GSC MCP server with its embedded,
single-owner OAuth 2.1 authorization server.

## 1. Enable services

```bash
PROJECT_ID="YOUR_PROJECT_ID"

gcloud config set project "$PROJECT_ID"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com
```

## 2. Create the runtime service account

```bash
RUNTIME_SA_NAME="mp-gsc-mcp"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
  --display-name="MP GSC MCP Runtime"
```

Add `$RUNTIME_SA` as a Search Console user on each exact property configured in
`GSC_ALLOWED_PROPERTIES`. No extra Google Cloud role grants Search Console access.

## 3. Create OAuth secrets

```bash
SERVICE="mp-gsc-mcp"
TOKEN_SECRET_NAME="${SERVICE}-oauth-token-secret"
PASSWORD_SECRET_NAME="${SERVICE}-oauth-admin-password"

openssl rand -base64 48 | \
  gcloud secrets create "$TOKEN_SECRET_NAME" \
    --project "$PROJECT_ID" \
    --replication-policy=automatic \
    --data-file=-

read -rsp "OAuth authorization password: " OAUTH_PASSWORD
echo
printf '%s' "$OAUTH_PASSWORD" | \
  gcloud secrets create "$PASSWORD_SECRET_NAME" \
    --project "$PROJECT_ID" \
    --replication-policy=automatic \
    --data-file=-
unset OAUTH_PASSWORD
```

For existing secrets, add a new version rather than creating them again:

```bash
openssl rand -base64 48 | \
  gcloud secrets versions add "$TOKEN_SECRET_NAME" --data-file=-
```

Grant only the runtime service account access to the two secrets:

```bash
for SECRET in "$TOKEN_SECRET_NAME" "$PASSWORD_SECRET_NAME"; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --project "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

Rotating `OAUTH_TOKEN_SECRET` invalidates all existing OAuth clients and tokens and
requires reconnecting the ChatGPT connector. Rotating only the password does not
invalidate existing tokens.

## 4. Configure non-secret environment values

```bash
cp .env.chatgpt.example .env.chatgpt
```

Set at least:

```text
MCP_PUBLIC_BASE_URL=https://YOUR_DEPLOYED_HOST
MCP_REQUIRED_SCOPES=gsc.read
OAUTH_ALLOWED_EMAILS=YOUR_EMAIL
GSC_ALLOWED_PROPERTIES=sc-domain:makeuppalace.com.au
```

Do not place either OAuth secret in `.env.chatgpt`.

For a first deployment, the final Cloud Run hostname is not known until deployment.
Deploy once with the anticipated service URL, then read the actual URL and update
`MCP_PUBLIC_BASE_URL` before the final deployment:

```bash
REGION="australia-southeast1"
SERVICE="mp-gsc-mcp"
EXPECTED_URL="https://${SERVICE}-PROJECT_HASH.${REGION}.run.app"
```

A mapped custom domain is preferable because it gives the OAuth issuer and resource a
stable URL across service recreation.

## 5. Deploy

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
REGION="australia-southeast1"
SERVICE="mp-gsc-mcp"
RUNTIME_SA="mp-gsc-mcp@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

chmod +x scripts/deploy-cloud-run.sh
PROJECT_ID="$PROJECT_ID" \
REGION="$REGION" \
SERVICE="$SERVICE" \
RUNTIME_SA="$RUNTIME_SA" \
BUILD_SERVICE_ACCOUNT="$BUILD_SERVICE_ACCOUNT" \
OAUTH_TOKEN_SECRET_NAME="${SERVICE}-oauth-token-secret" \
OAUTH_ADMIN_PASSWORD_SECRET_NAME="${SERVICE}-oauth-admin-password" \
MAX_INSTANCES=1 \
./scripts/deploy-cloud-run.sh .env.chatgpt
```

The script intentionally enforces one Cloud Run instance because the embedded server
uses an in-process replay guard for one-time authorization codes and refresh-token
rotation. Use `MCP_AUTH_MODE=external_jwt` with an established IdP before scaling past
one instance or supporting multiple users.

Cloud Run remains publicly reachable at the network layer through
`--allow-unauthenticated`. The application-level OAuth middleware protects `/mcp`.

## 6. Verify discovery and authorization enforcement

```bash
PUBLIC_URL="https://YOUR_DEPLOYED_HOST"

curl -fsS "$PUBLIC_URL/health" | jq .
curl -fsS "$PUBLIC_URL/.well-known/oauth-protected-resource" | jq .
curl -fsS "$PUBLIC_URL/.well-known/oauth-authorization-server" | jq .
curl -i -X POST "$PUBLIC_URL/mcp"
```

Expected results:

- `/health` returns `status=ok` and `auth_mode=oauth`.
- Protected-resource metadata identifies `$PUBLIC_URL` and the same authorization
  server.
- Authorization-server metadata advertises authorization code, refresh token,
  dynamic client registration, and PKCE `S256`.
- An unauthenticated MCP request returns `401` with `WWW-Authenticate` referencing
  protected-resource metadata.

## 7. Link ChatGPT

Add the custom MCP server URL:

```text
https://YOUR_DEPLOYED_HOST/mcp
```

ChatGPT discovers the OAuth metadata, dynamically registers its callback, opens the
server authorization page, exchanges the authorization code with its PKCE verifier,
and then sends the returned bearer token on MCP requests.

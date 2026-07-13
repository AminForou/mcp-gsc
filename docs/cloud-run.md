# Cloud Run deployment runbook

This guide deploys the ChatGPT-compatible MCP HTTP server (`mp-gsc-mcp-http`) to
Cloud Run.

## 1) Prerequisites

- `gcloud` CLI installed and authenticated
- A Google Cloud project with billing enabled
- APIs enabled:
  - Cloud Run Admin API
  - Cloud Build API
  - Artifact Registry API
- OAuth provider configured for ChatGPT MCP connector
- Runtime service account added as a user on every GSC property listed in
  `GSC_ALLOWED_PROPERTIES`

Enable required services:

```bash
PROJECT_ID="YOUR_PROJECT_ID"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
```

## 2) Create runtime service account

```bash
PROJECT_ID="YOUR_PROJECT_ID"
RUNTIME_SA_NAME="mp-gsc-mcp"
RUNTIME_SA="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
  --display-name="MP GSC MCP Runtime"
```

`GSC_GOOGLE_AUTH_MODE=adc` uses this service account at runtime. Search Console
authorization is granted by adding this email in Search Console users/permissions,
not by extra Google Cloud IAM roles.

## 3) Create deployment env file

```bash
cp .env.chatgpt.example .env.chatgpt
```

Edit `.env.chatgpt` and set real values, especially:

- `MCP_PUBLIC_BASE_URL`
- `MCP_OAUTH_ISSUER`
- `MCP_OAUTH_JWKS_URI`
- `MCP_OAUTH_AUDIENCE`
- `MCP_REQUIRED_SCOPES`
- `GSC_ALLOWED_PROPERTIES`

## 4) Deploy

```bash
PROJECT_ID="YOUR_PROJECT_ID"
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
./scripts/deploy-cloud-run.sh .env.chatgpt
```

The script deploys from source and sets Cloud Run env vars for the MCP OAuth
resource-server contract.

If your project shows errors like:

`IAM permission denied for service account PROJECT_NUMBER@cloudbuild.gserviceaccount.com`

it usually means the legacy Cloud Build default service account is deleted or
unusable. Providing `BUILD_SERVICE_ACCOUNT` bypasses that default.

## 5) Verify

```bash
PUBLIC_URL="https://YOUR_DEPLOYED_HOST"

curl -fsS "$PUBLIC_URL/health"
curl -fsS "$PUBLIC_URL/.well-known/oauth-protected-resource" | jq .
curl -i -X POST "$PUBLIC_URL/mcp"
```

Expected behavior:

- `/health` returns JSON with `"status": "ok"`
- `/.well-known/oauth-protected-resource` returns JSON metadata
- unauthenticated `/mcp` returns `401` with `WWW-Authenticate`

## Notes

- Keep `MCP_AUTH_MODE=oauth` in production.
- Do not deploy `MCP_AUTH_MODE=none` on public Cloud Run endpoints.
- Cloud Run network access can be `--allow-unauthenticated`; OAuth enforcement is
  handled by the MCP server itself.

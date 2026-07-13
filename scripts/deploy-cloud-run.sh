#!/usr/bin/env bash

set -euo pipefail

# Usage:
#   ./scripts/deploy-cloud-run.sh [path/to/.env.chatgpt]
#
# Required shell vars before running:
#   PROJECT_ID, REGION, SERVICE, RUNTIME_SA
#
# Optional shell var:
#   BUILD_SERVICE_ACCOUNT (recommended when Cloud Build default SA is missing)
#
# The env file provides MCP/GSC runtime vars (see .env.chatgpt.example).

ENV_FILE="${1:-.env.chatgpt}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: env file not found: $ENV_FILE" >&2
  echo "Copy .env.chatgpt.example to .env.chatgpt and update values." >&2
  exit 1
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "Error: gcloud CLI is required." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required_shell_vars=(
  PROJECT_ID
  REGION
  SERVICE
  RUNTIME_SA
)

for var_name in "${required_shell_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Error: required shell variable is missing: $var_name" >&2
    exit 1
  fi
done

required_env_vars=(
  MCP_PUBLIC_BASE_URL
  MCP_OAUTH_ISSUER
  MCP_OAUTH_JWKS_URI
  MCP_OAUTH_AUDIENCE
  MCP_REQUIRED_SCOPES
  GSC_ALLOWED_PROPERTIES
)

for var_name in "${required_env_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Error: required env variable is missing in $ENV_FILE: $var_name" >&2
    exit 1
  fi
done

ENV_VARS=(
  "MCP_AUTH_MODE=oauth"
  "MCP_PUBLIC_BASE_URL=${MCP_PUBLIC_BASE_URL}"
  "MCP_OAUTH_ISSUER=${MCP_OAUTH_ISSUER}"
  "MCP_OAUTH_JWKS_URI=${MCP_OAUTH_JWKS_URI}"
  "MCP_OAUTH_AUDIENCE=${MCP_OAUTH_AUDIENCE}"
  "MCP_OAUTH_ALGORITHMS=${MCP_OAUTH_ALGORITHMS:-RS256}"
  "MCP_REQUIRED_SCOPES=${MCP_REQUIRED_SCOPES}"
  "GSC_ALLOWED_PROPERTIES=${GSC_ALLOWED_PROPERTIES}"
  "MCP_REQUIRE_PROPERTY_ALLOWLIST=${MCP_REQUIRE_PROPERTY_ALLOWLIST:-true}"
  "GSC_GOOGLE_AUTH_MODE=${GSC_GOOGLE_AUTH_MODE:-adc}"
  "GSC_SKIP_OAUTH=${GSC_SKIP_OAUTH:-true}"
  "MCP_HOST=${MCP_HOST:-0.0.0.0}"
  "MCP_HTTP_PATH=${MCP_HTTP_PATH:-/mcp}"
  "MCP_STATELESS_HTTP=${MCP_STATELESS_HTTP:-true}"
  "MCP_JSON_RESPONSE=${MCP_JSON_RESPONSE:-true}"
  "MCP_READINESS_CHECK_GSC=${MCP_READINESS_CHECK_GSC:-false}"
)

if [[ -n "${MCP_ALLOWED_HOSTS:-}" ]]; then
  ENV_VARS+=("MCP_ALLOWED_HOSTS=${MCP_ALLOWED_HOSTS}")
fi

if [[ -n "${MCP_ALLOWED_ORIGINS:-}" ]]; then
  ENV_VARS+=("MCP_ALLOWED_ORIGINS=${MCP_ALLOWED_ORIGINS}")
fi

env_csv=""
for kv in "${ENV_VARS[@]}"; do
  if [[ -n "$env_csv" ]]; then
    env_csv+=","
  fi
  env_csv+="$kv"
done

echo "Deploying ${SERVICE} to Cloud Run (${PROJECT_ID}/${REGION})..."

deploy_args=(
  --project "$PROJECT_ID"
  --region "$REGION"
  --source .
  --service-account "$RUNTIME_SA"
  --allow-unauthenticated
  --set-env-vars "$env_csv"
)

if [[ -n "${BUILD_SERVICE_ACCOUNT:-}" ]]; then
  deploy_args+=(--build-service-account "$BUILD_SERVICE_ACCOUNT")
fi

gcloud run deploy "$SERVICE" \
  "${deploy_args[@]}"

echo
echo "Deployment complete. Quick checks:"
echo "  curl -fsS ${MCP_PUBLIC_BASE_URL}/health"
echo "  curl -fsS ${MCP_PUBLIC_BASE_URL}/.well-known/oauth-protected-resource | jq ."
echo "  curl -i -X POST ${MCP_PUBLIC_BASE_URL}/mcp"

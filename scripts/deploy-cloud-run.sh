#!/usr/bin/env bash

set -euo pipefail

# Usage:
#   ./scripts/deploy-cloud-run.sh [path/to/.env.chatgpt]
#
# Required shell vars before running:
#   PROJECT_ID, REGION, SERVICE, RUNTIME_SA
#
# Optional shell vars:
#   BUILD_SERVICE_ACCOUNT
#   OAUTH_TOKEN_SECRET_NAME       (default: ${SERVICE}-oauth-token-secret)
#   OAUTH_ADMIN_PASSWORD_SECRET_NAME (default: ${SERVICE}-oauth-admin-password)
#   MAX_INSTANCES                 (must remain 1 for the embedded in-memory replay guard)
#
# The env file provides non-secret MCP/GSC runtime vars. OAuth secrets are mounted
# from Secret Manager and are never copied into the deployment environment file.

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

required_shell_vars=(PROJECT_ID REGION SERVICE RUNTIME_SA)
for var_name in "${required_shell_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Error: required shell variable is missing: $var_name" >&2
    exit 1
  fi
done

required_env_vars=(
  MCP_PUBLIC_BASE_URL
  MCP_REQUIRED_SCOPES
  OAUTH_ALLOWED_EMAILS
  GSC_ALLOWED_PROPERTIES
)
for var_name in "${required_env_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then
    echo "Error: required env variable is missing in $ENV_FILE: $var_name" >&2
    exit 1
  fi
done

OAUTH_TOKEN_SECRET_NAME="${OAUTH_TOKEN_SECRET_NAME:-${SERVICE}-oauth-token-secret}"
OAUTH_ADMIN_PASSWORD_SECRET_NAME="${OAUTH_ADMIN_PASSWORD_SECRET_NAME:-${SERVICE}-oauth-admin-password}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"
if [[ "$MAX_INSTANCES" != "1" ]]; then
  echo "Error: embedded OAuth requires MAX_INSTANCES=1 for one-time code and refresh-token replay protection." >&2
  echo "Use MCP_AUTH_MODE=external_jwt with an established identity provider for multi-instance deployment." >&2
  exit 1
fi

for secret_name in "$OAUTH_TOKEN_SECRET_NAME" "$OAUTH_ADMIN_PASSWORD_SECRET_NAME"; do
  if ! gcloud secrets describe "$secret_name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Error: Secret Manager secret does not exist: $secret_name" >&2
    exit 1
  fi
done

ENV_VARS=(
  "MCP_AUTH_MODE=oauth"
  "MCP_PUBLIC_BASE_URL=${MCP_PUBLIC_BASE_URL}"
  "MCP_REQUIRED_SCOPES=${MCP_REQUIRED_SCOPES}"
  "OAUTH_ALLOWED_EMAILS=${OAUTH_ALLOWED_EMAILS}"
  "OAUTH_ALLOWED_REDIRECT_HOSTS=${OAUTH_ALLOWED_REDIRECT_HOSTS:-chatgpt.com,chat.openai.com,.openai.com}"
  "OAUTH_ACCESS_TOKEN_TTL_SECONDS=${OAUTH_ACCESS_TOKEN_TTL_SECONDS:-3600}"
  "OAUTH_REFRESH_TOKEN_TTL_SECONDS=${OAUTH_REFRESH_TOKEN_TTL_SECONDS:-2592000}"
  "OAUTH_AUTH_CODE_TTL_SECONDS=${OAUTH_AUTH_CODE_TTL_SECONDS:-300}"
  "OAUTH_DYNAMIC_CLIENT_TTL_SECONDS=${OAUTH_DYNAMIC_CLIENT_TTL_SECONDS:-31536000}"
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

if [[ -n "${OAUTH_ISSUER_URL:-}" ]]; then
  ENV_VARS+=("OAUTH_ISSUER_URL=${OAUTH_ISSUER_URL}")
fi
if [[ -n "${OAUTH_RESOURCE_URL:-}" ]]; then
  ENV_VARS+=("OAUTH_RESOURCE_URL=${OAUTH_RESOURCE_URL}")
fi
if [[ -n "${MCP_ALLOWED_HOSTS:-}" ]]; then
  ENV_VARS+=("MCP_ALLOWED_HOSTS=${MCP_ALLOWED_HOSTS}")
fi
if [[ -n "${MCP_ALLOWED_ORIGINS:-}" ]]; then
  ENV_VARS+=("MCP_ALLOWED_ORIGINS=${MCP_ALLOWED_ORIGINS}")
fi

# Use a temporary YAML file so comma-separated allowlists are not split by gcloud.
env_yaml="$(mktemp)"
trap 'rm -f "$env_yaml"' EXIT
{
  for kv in "${ENV_VARS[@]}"; do
    key="${kv%%=*}"
    value="${kv#*=}"
    printf '%s: %s\n' "$key" "$(printf '%s' "$value" | python -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
  done
} > "$env_yaml"

echo "Deploying ${SERVICE} to Cloud Run (${PROJECT_ID}/${REGION})..."

deploy_args=(
  --project "$PROJECT_ID"
  --region "$REGION"
  --source .
  --service-account "$RUNTIME_SA"
  --allow-unauthenticated
  --max-instances "$MAX_INSTANCES"
  --env-vars-file "$env_yaml"
  --set-secrets "OAUTH_TOKEN_SECRET=${OAUTH_TOKEN_SECRET_NAME}:latest,MCP_OAUTH_TOKEN_SECRET=${OAUTH_TOKEN_SECRET_NAME}:latest,OAUTH_ADMIN_PASSWORD=${OAUTH_ADMIN_PASSWORD_SECRET_NAME}:latest,MCP_OAUTH_ADMIN_PASSWORD=${OAUTH_ADMIN_PASSWORD_SECRET_NAME}:latest"
)

if [[ -n "${BUILD_SERVICE_ACCOUNT:-}" ]]; then
  deploy_args+=(--build-service-account "$BUILD_SERVICE_ACCOUNT")
fi

gcloud run deploy "$SERVICE" "${deploy_args[@]}"

echo
echo "Deployment complete. Quick checks:"
echo "  curl -fsS ${MCP_PUBLIC_BASE_URL}/health | jq ."
echo "  curl -fsS ${MCP_PUBLIC_BASE_URL}/.well-known/oauth-protected-resource | jq ."
echo "  curl -fsS ${MCP_PUBLIC_BASE_URL}/.well-known/oauth-authorization-server | jq ."
echo "  curl -i -X POST ${MCP_PUBLIC_BASE_URL}/mcp"

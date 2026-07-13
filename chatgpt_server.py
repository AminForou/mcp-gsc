"""ChatGPT-compatible remote MCP entrypoint for Google Search Console.

This module deliberately creates a second FastMCP server rather than changing the
upstream stdio server. It exposes a constrained read-only tool surface over
Streamable HTTP, validates OAuth access tokens, and supports Google Application
Default Credentials for Cloud Run.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast
from urllib.parse import urlparse

import google.auth
import jwt
from googleapiclient.discovery import build
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse

from embedded_oauth import (
    EmbeddedOAuthConfig,
    EmbeddedOAuthTokenVerifier,
    load_embedded_oauth_config,
    register_embedded_oauth_routes,
)
import gsc_server as upstream

LOGGER = logging.getLogger("mp-gsc-mcp.chatgpt")

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

F = TypeVar("F", bound=Callable[..., Awaitable[str]])


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str, default: str = "") -> list[str]:
    return [part.strip() for part in os.getenv(name, default).split(",") if part.strip()]


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _normalise_public_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("MCP_PUBLIC_BASE_URL must be an absolute HTTPS URL")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError("MCP_PUBLIC_BASE_URL must contain only scheme and host")
    return value


def _extract_scopes(claims: dict[str, Any]) -> list[str]:
    scopes: set[str] = set()
    for claim_name in ("scope", "scp", "permissions"):
        raw = claims.get(claim_name)
        if isinstance(raw, str):
            scopes.update(part for part in raw.split() if part)
        elif isinstance(raw, list):
            scopes.update(str(part) for part in raw if str(part))
    return sorted(scopes)


class JwtTokenVerifier:
    """Verify JWT access tokens issued by the configured OAuth provider."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_uri: str,
        algorithms: list[str],
        required_scopes: list[str],
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.algorithms = algorithms
        self.required_scopes = set(required_scopes)
        self.jwks_client = PyJWKClient(jwks_uri)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            signing_key = await asyncio.to_thread(
                self.jwks_client.get_signing_key_from_jwt,
                token,
            )
            claims = cast(
                dict[str, Any],
                jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=self.algorithms,
                    audience=self.audience,
                    issuer=self.issuer,
                    leeway=30,
                    options={"require": ["exp", "iss"]},
                ),
            )
            scopes = _extract_scopes(claims)
            if not self.required_scopes.issubset(scopes):
                LOGGER.warning(
                    "Rejected OAuth token with insufficient scopes; required=%s supplied=%s",
                    sorted(self.required_scopes),
                    scopes,
                )
                return None

            client_id = (
                claims.get("azp")
                or claims.get("client_id")
                or claims.get("sub")
                or "unknown-client"
            )
            return AccessToken(
                token=token,
                client_id=str(client_id),
                scopes=scopes,
                expires_at=int(claims["exp"]),
                resource=self.audience,
                subject=str(claims["sub"]) if claims.get("sub") else None,
                claims=claims,
            )
        except Exception as exc:  # Token failures must become unauthenticated requests.
            LOGGER.warning("Rejected invalid OAuth token: %s", type(exc).__name__)
            return None


def _configure_google_auth() -> None:
    """Select Cloud Run ADC or retain the upstream credential-file/OAuth logic."""

    mode = os.getenv("GSC_GOOGLE_AUTH_MODE", "adc").strip().lower()
    if mode == "upstream":
        return
    if mode != "adc":
        raise RuntimeError("GSC_GOOGLE_AUTH_MODE must be 'adc' or 'upstream'")

    def get_gsc_service_adc() -> Any:
        credentials, _ = google.auth.default(scopes=upstream.SCOPES)
        return build(
            "searchconsole",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )

    # Upstream tools resolve this module global at invocation time, so replacing it
    # here makes every registered tool use the Cloud Run service identity.
    upstream.get_gsc_service = get_gsc_service_adc


def _allowed_properties(auth_enabled: bool) -> set[str]:
    allowed = set(_csv_env("GSC_ALLOWED_PROPERTIES"))
    require_allowlist = _env_bool("MCP_REQUIRE_PROPERTY_ALLOWLIST", auth_enabled)
    if require_allowlist and not allowed:
        raise RuntimeError(
            "GSC_ALLOWED_PROPERTIES must contain at least one exact Search Console "
            "property when MCP_REQUIRE_PROPERTY_ALLOWLIST=true"
        )
    return allowed


def _guard_property(fn: F, allowed: set[str]) -> F:
    """Reject tool calls for properties outside the configured allowlist."""

    signature = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapped(*args: Any, **kwargs: Any) -> str:
        bound = signature.bind_partial(*args, **kwargs)
        site_url = bound.arguments.get("site_url")
        if allowed and site_url not in allowed:
            return json.dumps(
                {
                    "error": "property_not_allowed",
                    "message": "The requested Search Console property is not approved.",
                }
            )
        return await fn(*args, **kwargs)

    # FastMCP follows __wrapped__, but retaining an explicit signature also protects
    # schema generation in clients that inspect the callable directly.
    wrapped.__signature__ = signature  # type: ignore[attr-defined]
    return cast(F, wrapped)


def _security_meta(auth_enabled: bool, scopes: list[str]) -> dict[str, Any]:
    schemes: list[dict[str, Any]]
    if auth_enabled:
        schemes = [{"type": "oauth2", "scopes": scopes}]
    else:
        schemes = [{"type": "noauth"}]
    return {"securitySchemes": schemes}


def build_server() -> FastMCP:
    auth_mode = os.getenv("MCP_AUTH_MODE", "oauth").strip().lower()
    if auth_mode not in {"oauth", "external_jwt", "none"}:
        raise RuntimeError(
            "MCP_AUTH_MODE must be 'oauth', 'external_jwt', or 'none'"
        )
    auth_enabled = auth_mode != "none"

    host = os.getenv("MCP_HOST", "0.0.0.0")
    try:
        port = int(os.getenv("PORT", os.getenv("MCP_PORT", "8080")))
    except ValueError as exc:
        raise RuntimeError("PORT/MCP_PORT must be an integer") from exc

    http_path = os.getenv("MCP_HTTP_PATH", "/mcp").strip()
    if not http_path.startswith("/"):
        http_path = f"/{http_path}"

    required_scopes = _csv_env("MCP_REQUIRED_SCOPES", "gsc.read")
    if auth_enabled and not required_scopes:
        raise RuntimeError("MCP_REQUIRED_SCOPES must not be empty in OAuth mode")

    auth_settings: AuthSettings | None = None
    token_verifier: Any | None = None
    embedded_oauth_config: EmbeddedOAuthConfig | None = None
    public_url: str | None = None

    if auth_enabled:
        public_url = _normalise_public_url(_required_env("MCP_PUBLIC_BASE_URL"))
        documentation_url = os.getenv(
            "MCP_SERVICE_DOCUMENTATION_URL",
            "https://github.com/ZipSites/mp-gsc-mcp/blob/main/docs/chatgpt-plugin.md",
        )

        if auth_mode == "oauth":
            embedded_oauth_config = load_embedded_oauth_config(
                public_url=public_url,
                required_scopes=required_scopes,
            )
            token_verifier = EmbeddedOAuthTokenVerifier(embedded_oauth_config)
            auth_settings = AuthSettings(
                issuer_url=embedded_oauth_config.issuer_url,
                resource_server_url=embedded_oauth_config.resource_url,
                service_documentation_url=documentation_url,
                required_scopes=required_scopes,
            )
        else:
            issuer = _required_env("MCP_OAUTH_ISSUER")
            audience = os.getenv("MCP_OAUTH_AUDIENCE", public_url).strip()
            jwks_uri = _required_env("MCP_OAUTH_JWKS_URI")
            algorithms = _csv_env("MCP_OAUTH_ALGORITHMS", "RS256")
            if not algorithms:
                raise RuntimeError("MCP_OAUTH_ALGORITHMS must not be empty")

            token_verifier = JwtTokenVerifier(
                issuer=issuer,
                audience=audience,
                jwks_uri=jwks_uri,
                algorithms=algorithms,
                required_scopes=required_scopes,
            )
            auth_settings = AuthSettings(
                issuer_url=issuer,
                resource_server_url=audience,
                service_documentation_url=documentation_url,
                required_scopes=required_scopes,
            )

    allowed = _allowed_properties(auth_enabled)
    _configure_google_auth()

    allowed_hosts = _csv_env("MCP_ALLOWED_HOSTS")
    allowed_origins = _csv_env("MCP_ALLOWED_ORIGINS")
    if public_url:
        parsed_public = urlparse(public_url)
        if parsed_public.netloc not in allowed_hosts:
            allowed_hosts.append(parsed_public.netloc)
        wildcard_host = f"{parsed_public.hostname}:*" if parsed_public.hostname else None
        if wildcard_host and wildcard_host not in allowed_hosts:
            allowed_hosts.append(wildcard_host)
        if public_url not in allowed_origins:
            allowed_origins.append(public_url)
    allowed_hosts.extend(
        host_pattern
        for host_pattern in ("127.0.0.1:*", "localhost:*", "[::1]:*")
        if host_pattern not in allowed_hosts
    )
    allowed_origins.extend(
        origin
        for origin in (
            "https://chatgpt.com",
            "https://chat.openai.com",
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
        )
        if origin not in allowed_origins
    )

    server = FastMCP(
        name="mp-gsc-mcp",
        instructions=(
            "Read-only Google Search Console access. Call list_properties first unless "
            "the exact property is already known. Use exact site_url values returned by "
            "that tool. Prefer narrow date ranges and paginated analytics queries. Never "
            "claim that Search Analytics is exhaustive because Google returns top rows."
        ),
        website_url="https://github.com/ZipSites/mp-gsc-mcp",
        host=host,
        port=port,
        streamable_http_path=http_path,
        stateless_http=_env_bool("MCP_STATELESS_HTTP", True),
        json_response=_env_bool("MCP_JSON_RESPONSE", True),
        auth=auth_settings,
        token_verifier=token_verifier,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )

    if embedded_oauth_config is not None:
        register_embedded_oauth_routes(server, embedded_oauth_config)

    meta = _security_meta(auth_enabled, required_scopes)

    @server.tool(
        name="get_gsc_capabilities",
        title="Get GSC capabilities",
        annotations=READ_ONLY_ANNOTATIONS,
        meta=meta,
        structured_output=True,
    )
    async def get_gsc_capabilities() -> dict[str, Any]:
        """Return the remote server's supported read-only tools and constraints."""

        return {
            "server": "mp-gsc-mcp",
            "transport": "streamable-http",
            "endpoint": http_path,
            "authentication": auth_mode,
            "read_only": True,
            "property_allowlist_enabled": bool(allowed),
            "tools": [
                "list_properties",
                "get_site_details",
                "get_search_analytics",
                "get_performance_overview",
                "compare_search_periods",
                "get_search_by_page_query",
                "get_advanced_search_analytics",
                "inspect_url_enhanced",
                "batch_url_inspection",
                "check_indexing_issues",
                "get_sitemaps",
                "list_sitemaps_enhanced",
                "get_sitemap_details",
            ],
        }

    async def list_properties_filtered() -> str:
        """List approved Google Search Console properties available to this server."""

        raw = await upstream.list_properties()
        if not allowed:
            return raw
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        properties = [
            item
            for item in payload.get("properties", [])
            if item.get("site_url") in allowed
        ]
        return json.dumps({"count": len(properties), "properties": properties})

    read_tools: list[tuple[str, str, Callable[..., Awaitable[str]]]] = [
        ("list_properties", "List GSC properties", list_properties_filtered),
        ("get_site_details", "Get GSC property details", upstream.get_site_details),
        ("get_search_analytics", "Get search analytics", upstream.get_search_analytics),
        ("get_performance_overview", "Get performance overview", upstream.get_performance_overview),
        ("compare_search_periods", "Compare search periods", upstream.compare_search_periods),
        ("get_search_by_page_query", "Get page query performance", upstream.get_search_by_page_query),
        (
            "get_advanced_search_analytics",
            "Query advanced search analytics",
            upstream.get_advanced_search_analytics,
        ),
        ("inspect_url_enhanced", "Inspect URL indexing", upstream.inspect_url_enhanced),
        ("batch_url_inspection", "Inspect multiple URLs", upstream.batch_url_inspection),
        ("check_indexing_issues", "Check indexing issues", upstream.check_indexing_issues),
        ("get_sitemaps", "List sitemaps", upstream.get_sitemaps),
        ("list_sitemaps_enhanced", "List detailed sitemaps", upstream.list_sitemaps_enhanced),
        ("get_sitemap_details", "Get sitemap details", upstream.get_sitemap_details),
    ]

    for name, title, fn in read_tools:
        guarded = fn if name == "list_properties" else _guard_property(fn, allowed)
        server.add_tool(
            guarded,
            name=name,
            title=title,
            annotations=READ_ONLY_ANNOTATIONS,
            meta=meta,
            structured_output=False,
        )

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "mp-gsc-mcp",
                "transport": "streamable-http",
                "auth_mode": auth_mode,
            }
        )

    @server.custom_route("/ready", methods=["GET"], include_in_schema=False)
    async def ready(_: Request) -> JSONResponse:
        try:
            if _env_bool("MCP_READINESS_CHECK_GSC", False):
                upstream.get_gsc_service()
            return JSONResponse({"status": "ready"})
        except Exception as exc:
            LOGGER.error("Readiness check failed: %s", type(exc).__name__)
            return JSONResponse({"status": "not_ready"}, status_code=503)

    @server.custom_route("/", methods=["GET"], include_in_schema=False)
    async def root(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "service": "mp-gsc-mcp",
                "mcp_endpoint": http_path,
                "health_endpoint": "/health",
                "oauth_protected_resource": (
                    "/.well-known/oauth-protected-resource" if auth_enabled else None
                ),
                "oauth_authorization_server": (
                    "/.well-known/oauth-authorization-server"
                    if auth_mode == "oauth"
                    else None
                ),
            }
        )

    return server


def main() -> None:
    """Run the ChatGPT-compatible Streamable HTTP server."""

    server = build_server()
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()

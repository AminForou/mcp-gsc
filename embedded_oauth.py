"""Embedded OAuth 2.1 authorization server for a private ChatGPT MCP deployment.

This module implements the authorization-code grant with PKCE (S256), dynamic
client registration, refresh tokens, OAuth discovery metadata, and MCP access
-token verification. It is intended for a single-owner or tightly controlled
Cloud Run deployment. Multi-user and enterprise deployments should use an
established identity provider instead.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

LOGGER = logging.getLogger("mp-gsc-mcp.oauth")

DEFAULT_SCOPE: Final[str] = "gsc.read"
DEFAULT_REDIRECT_HOSTS: Final[tuple[str, ...]] = (
    "chatgpt.com",
    "chat.openai.com",
    ".openai.com",
)
PKCE_VERIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
PKCE_CHALLENGE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{43}$")
TokenType = Literal["access", "refresh", "code", "client"]


class OAuthError(RuntimeError):
    """Protocol-safe OAuth error."""

    def __init__(self, error: str, description: str, *, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


@dataclass(frozen=True)
class EmbeddedOAuthConfig:
    """Validated runtime configuration for the embedded authorization server."""

    token_secret: str
    admin_password: str
    allowed_emails: frozenset[str]
    required_scopes: tuple[str, ...]
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    authorization_code_ttl_seconds: int
    dynamic_client_ttl_seconds: int
    allowed_redirect_hosts: tuple[str, ...]
    resource_url: str
    issuer_url: str
    service_name: str = "Google Search Console MCP"

    @property
    def scope_string(self) -> str:
        return " ".join(self.required_scopes)


class TokenReplayGuard:
    """Best-effort one-time-use enforcement for codes and rotating refresh tokens.

    Cloud Run must be deployed with one active instance for this in-process guard to
    provide deterministic replay rejection. Use a durable authorization server for
    multi-instance or multi-user deployments.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: dict[tuple[str, str], int] = {}

    def consume(
        self, payload: Mapping[str, object], token_type: Literal["code", "refresh"]
    ) -> None:
        jti = payload.get("jti")
        exp = payload.get("exp")
        if not isinstance(jti, str) or not jti or not isinstance(exp, int):
            raise OAuthError("invalid_grant", "Token replay identifier is missing.")

        now = int(time.time())
        key = (token_type, jti)
        with self._lock:
            self._consumed = {
                existing_key: existing_exp
                for existing_key, existing_exp in self._consumed.items()
                if existing_exp > now
            }
            if key in self._consumed:
                raise OAuthError(
                    "invalid_grant", f"The {token_type} token has already been used."
                )
            self._consumed[key] = exp


class EmbeddedOAuthTokenVerifier:
    """Verify HMAC-signed access tokens issued by this embedded server."""

    def __init__(self, config: EmbeddedOAuthConfig) -> None:
        self.config = config

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = _verify_payload(token, self.config.token_secret, "access")
            subject = str(payload.get("sub", "")).lower()
            issuer = str(payload.get("iss", ""))
            audience = str(payload.get("aud", ""))
            client_id = str(payload.get("client_id", ""))
            scopes = sorted(set(str(payload.get("scope", "")).split()))

            if subject not in self.config.allowed_emails:
                raise OAuthError(
                    "invalid_token", "Token subject is not permitted.", status_code=401
                )
            if issuer != self.config.issuer_url:
                raise OAuthError(
                    "invalid_token", "Token issuer does not match.", status_code=401
                )
            if audience != self.config.resource_url:
                raise OAuthError(
                    "invalid_token", "Token audience does not match.", status_code=401
                )
            if not set(self.config.required_scopes).issubset(scopes):
                raise OAuthError(
                    "invalid_token", "Token scope is insufficient.", status_code=401
                )
            if not client_id:
                raise OAuthError(
                    "invalid_token", "Token client_id is missing.", status_code=401
                )

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=int(payload["exp"]),
                resource=self.config.resource_url,
            )
        except OAuthError as exc:
            LOGGER.info("Rejected embedded OAuth access token: %s", exc.description)
            return None
        except (
            Exception
        ) as exc:  # Authentication failures must become anonymous requests.
            LOGGER.warning(
                "Rejected embedded OAuth access token: %s", type(exc).__name__
            )
            return None


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip() != "":
            return value.strip()
    return None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return parsed


def _env_list(name: str, default: Sequence[str] = ()) -> list[str]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return list(default)
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalise_origin(name: str, value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError(f"{name} must be an absolute HTTPS origin")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} must contain only scheme and host")
    return normalized


def load_embedded_oauth_config(
    *,
    public_url: str,
    required_scopes: Sequence[str],
) -> EmbeddedOAuthConfig:
    """Load and validate embedded OAuth settings from environment variables."""

    token_secret = _env_first("OAUTH_TOKEN_SECRET", "MCP_OAUTH_TOKEN_SECRET")
    admin_password = _env_first("OAUTH_ADMIN_PASSWORD", "MCP_OAUTH_ADMIN_PASSWORD")
    allowed_emails = {
        email.lower() for email in _env_list("OAUTH_ALLOWED_EMAILS") if email.strip()
    }
    scopes = tuple(
        dict.fromkeys(scope.strip() for scope in required_scopes if scope.strip())
    )
    issuer_url = _normalise_origin(
        "OAUTH_ISSUER_URL",
        _env_first("OAUTH_ISSUER_URL", "MCP_OAUTH_ISSUER_URL") or public_url,
    )
    resource_origin = _normalise_origin(
        "OAUTH_RESOURCE_URL",
        _env_first("OAUTH_RESOURCE_URL", "MCP_RESOURCE_URL") or public_url,
    )
    # Pydantic's AnyHttpUrl serializes an origin-only resource with a trailing slash.
    # Use that exact canonical value for metadata, resource parameters, and audiences.
    resource_url = f"{resource_origin}/"

    if not token_secret:
        raise RuntimeError(
            "OAUTH_TOKEN_SECRET is required for MCP_AUTH_MODE=oauth; mount it from Secret Manager"
        )
    if len(token_secret.encode("utf-8")) < 32:
        raise RuntimeError(
            "OAUTH_TOKEN_SECRET must contain at least 32 bytes of entropy"
        )
    if not admin_password:
        raise RuntimeError(
            "OAUTH_ADMIN_PASSWORD is required for MCP_AUTH_MODE=oauth; mount it from Secret Manager"
        )
    if len(admin_password) < 12:
        raise RuntimeError("OAUTH_ADMIN_PASSWORD must be at least 12 characters")
    if not allowed_emails:
        raise RuntimeError(
            "OAUTH_ALLOWED_EMAILS must contain at least one approved email address"
        )
    if any("@" not in email for email in allowed_emails):
        raise RuntimeError("OAUTH_ALLOWED_EMAILS contains an invalid email address")
    if not scopes:
        scopes = (DEFAULT_SCOPE,)

    allowed_redirect_hosts = tuple(
        host.lower()
        for host in _env_list("OAUTH_ALLOWED_REDIRECT_HOSTS", DEFAULT_REDIRECT_HOSTS)
    )
    if not allowed_redirect_hosts:
        raise RuntimeError("OAUTH_ALLOWED_REDIRECT_HOSTS must not be empty")

    return EmbeddedOAuthConfig(
        token_secret=token_secret,
        admin_password=admin_password,
        allowed_emails=frozenset(allowed_emails),
        required_scopes=scopes,
        access_token_ttl_seconds=_env_int("OAUTH_ACCESS_TOKEN_TTL_SECONDS", 3600),
        refresh_token_ttl_seconds=_env_int(
            "OAUTH_REFRESH_TOKEN_TTL_SECONDS",
            30 * 24 * 60 * 60,
        ),
        authorization_code_ttl_seconds=_env_int("OAUTH_AUTH_CODE_TTL_SECONDS", 300),
        dynamic_client_ttl_seconds=_env_int(
            "OAUTH_DYNAMIC_CLIENT_TTL_SECONDS",
            365 * 24 * 60 * 60,
        ),
        allowed_redirect_hosts=allowed_redirect_hosts,
        resource_url=resource_url,
        issuer_url=issuer_url,
    )


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _sign_payload(payload: Mapping[str, object], secret: str) -> str:
    body = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{body}.{_b64url_encode(signature)}"


def _verify_payload(
    token: str, secret: str, expected_type: TokenType
) -> dict[str, object]:
    try:
        body, signature = token.split(".", 1)
    except ValueError as exc:
        raise OAuthError("invalid_token", "Malformed token.", status_code=401) from exc

    expected_signature = _b64url_encode(
        hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise OAuthError("invalid_token", "Invalid token signature.", status_code=401)

    try:
        decoded = json.loads(_b64url_decode(body))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OAuthError(
            "invalid_token", "Invalid token payload.", status_code=401
        ) from exc
    if not isinstance(decoded, dict):
        raise OAuthError("invalid_token", "Invalid token payload.", status_code=401)

    payload = {str(key): value for key, value in decoded.items()}
    if payload.get("typ") != expected_type:
        raise OAuthError("invalid_token", "Unexpected token type.", status_code=401)

    now = int(time.time())
    exp = payload.get("exp")
    nbf = payload.get("nbf")
    if not isinstance(exp, int) or exp <= now:
        raise OAuthError("invalid_token", "Token has expired.", status_code=401)
    if isinstance(nbf, int) and nbf > now + 30:
        raise OAuthError("invalid_token", "Token is not valid yet.", status_code=401)
    return payload


def _pkce_challenge(verifier: str) -> str:
    return _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def _validate_pkce_verifier(verifier: str) -> None:
    if not PKCE_VERIFIER_RE.fullmatch(verifier):
        raise OAuthError(
            "invalid_grant",
            "PKCE code_verifier must be 43-128 RFC 7636 unreserved characters.",
        )


def _redirect_uri_host_allowed(redirect_uri: str, allowed_hosts: Sequence[str]) -> bool:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "https" or not parsed.hostname or parsed.fragment:
        return False

    hostname = parsed.hostname.lower()
    for allowed in allowed_hosts:
        normalized = allowed.strip().lower()
        if not normalized:
            continue
        if normalized.startswith(".") and hostname.endswith(normalized):
            return True
        if hostname == normalized:
            return True
    return False


def _validate_redirect_uri(redirect_uri: str, config: EmbeddedOAuthConfig) -> None:
    if not redirect_uri:
        raise OAuthError("invalid_request", "Missing redirect_uri.")
    if not _redirect_uri_host_allowed(redirect_uri, config.allowed_redirect_hosts):
        raise OAuthError(
            "invalid_request", "redirect_uri is not an approved HTTPS callback."
        )


def _create_dynamic_client_id(
    redirect_uris: Sequence[str],
    config: EmbeddedOAuthConfig,
) -> tuple[str, int, int]:
    now = int(time.time())
    expires_at = now + config.dynamic_client_ttl_seconds
    client_id = "dcr_" + _sign_payload(
        {
            "typ": "client",
            "iss": config.issuer_url,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
            "jti": secrets.token_urlsafe(16),
            "redirect_uris": list(redirect_uris),
        },
        config.token_secret,
    )
    return client_id, now, expires_at


def _validate_client_redirect(
    *,
    client_id: str,
    redirect_uri: str,
    config: EmbeddedOAuthConfig,
) -> None:
    if not client_id:
        raise OAuthError("invalid_request", "Missing client_id.")
    _validate_redirect_uri(redirect_uri, config)

    if not client_id.startswith("dcr_"):
        raise OAuthError(
            "invalid_request", "Unknown OAuth client. Dynamic registration is required."
        )

    payload = _verify_payload(client_id[4:], config.token_secret, "client")
    if str(payload.get("iss", "")) != config.issuer_url:
        raise OAuthError("invalid_request", "OAuth client issuer does not match.")
    registered_redirects = payload.get("redirect_uris", [])
    if (
        not isinstance(registered_redirects, list)
        or redirect_uri not in registered_redirects
    ):
        raise OAuthError(
            "invalid_request", "redirect_uri is not registered for this client."
        )


def _parse_form_body(body: bytes) -> dict[str, str]:
    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OAuthError("invalid_request", "Request body must be UTF-8.") from exc
    parsed = urllib.parse.parse_qs(decoded, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _oauth_json(
    payload: Mapping[str, object], *, status_code: int = 200
) -> JSONResponse:
    return JSONResponse(
        dict(payload),
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _json_error(exc: OAuthError) -> JSONResponse:
    return _oauth_json(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status_code,
    )


def _oauth_form(
    params: Mapping[str, str],
    config: EmbeddedOAuthConfig,
    *,
    error: str | None = None,
) -> HTMLResponse:
    hidden_fields = "\n".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
        for key, value in params.items()
    )
    error_html = (
        f'<p role="alert" class="error">{html.escape(error)}</p>' if error else ""
    )
    scope_text = html.escape(params.get("scope", config.scope_string))
    body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Authorize {html.escape(config.service_name)}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 2rem auto; max-width: 42rem; padding: 0 1rem; }}
    label {{ display: block; margin-top: 1rem; font-weight: 600; }}
    input {{ box-sizing: border-box; display: block; margin-top: .35rem; padding: .7rem; width: 100%; }}
    button {{ margin-top: 1.25rem; padding: .75rem 1rem; }}
    code {{ background: #f2f2f2; padding: .1rem .3rem; }}
    .error {{ color: #b00020; }}
  </style>
</head>
<body>
  <h1>Authorize {html.escape(config.service_name)}</h1>
  <p>Allow ChatGPT to use the read-only MCP tools with scope <code>{scope_text}</code>.</p>
  {error_html}
  <form method="post" action="/oauth/authorize">
    {hidden_fields}
    <label>Email
      <input type="email" name="email" autocomplete="username" required autofocus>
    </label>
    <label>Password
      <input type="password" name="password" autocomplete="current-password" required>
    </label>
    <button type="submit">Authorize</button>
  </form>
</body>
</html>"""
    return HTMLResponse(
        body,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                "base-uri 'none'; frame-ancestors 'none'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        },
    )


def _validate_authorize_params(
    form: Mapping[str, str],
    config: EmbeddedOAuthConfig,
) -> dict[str, str]:
    if form.get("response_type", "") != "code":
        raise OAuthError(
            "unsupported_response_type", "Only response_type=code is supported."
        )

    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    _validate_client_redirect(
        client_id=client_id, redirect_uri=redirect_uri, config=config
    )

    if form.get("code_challenge_method", "") != "S256":
        raise OAuthError(
            "invalid_request", "PKCE code_challenge_method=S256 is required."
        )
    code_challenge = form.get("code_challenge", "")
    if not PKCE_CHALLENGE_RE.fullmatch(code_challenge):
        raise OAuthError(
            "invalid_request", "A valid S256 PKCE code_challenge is required."
        )

    requested_scopes = tuple(
        dict.fromkeys((form.get("scope") or config.scope_string).split())
    )
    if not set(config.required_scopes).issubset(requested_scopes):
        raise OAuthError(
            "invalid_scope",
            f"Required scopes: {config.scope_string}.",
        )

    resource = form.get("resource", "")
    if not resource:
        raise OAuthError("invalid_target", "The OAuth resource parameter is required.")
    if resource != config.resource_url:
        raise OAuthError(
            "invalid_target", "OAuth resource does not match this MCP server."
        )

    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(requested_scopes),
        "state": form.get("state", ""),
        "resource": resource,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }


def _append_query(url: str, params: Mapping[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value != "")
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def _issue_token_pair(
    *,
    config: EmbeddedOAuthConfig,
    subject: str,
    client_id: str,
    resource: str,
    scope: str,
) -> dict[str, object]:
    now = int(time.time())
    access_token = _sign_payload(
        {
            "typ": "access",
            "iss": config.issuer_url,
            "sub": subject,
            "client_id": client_id,
            "aud": resource,
            "scope": scope,
            "iat": now,
            "nbf": now,
            "exp": now + config.access_token_ttl_seconds,
            "jti": secrets.token_urlsafe(16),
        },
        config.token_secret,
    )
    refresh_token = _sign_payload(
        {
            "typ": "refresh",
            "iss": config.issuer_url,
            "sub": subject,
            "client_id": client_id,
            "aud": resource,
            "scope": scope,
            "iat": now,
            "nbf": now,
            "exp": now + config.refresh_token_ttl_seconds,
            "jti": secrets.token_urlsafe(24),
        },
        config.token_secret,
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": config.access_token_ttl_seconds,
        "refresh_token": refresh_token,
        "scope": scope,
    }


def _exchange_authorization_code(
    form: Mapping[str, str],
    config: EmbeddedOAuthConfig,
    replay_guard: TokenReplayGuard,
) -> dict[str, object]:
    code = form.get("code", "")
    if not code:
        raise OAuthError("invalid_grant", "Missing authorization code.")
    try:
        payload = _verify_payload(code, config.token_secret, "code")
    except OAuthError as exc:
        raise OAuthError("invalid_grant", exc.description) from exc

    if str(payload.get("iss", "")) != config.issuer_url:
        raise OAuthError("invalid_grant", "Authorization code issuer does not match.")
    if str(payload.get("sub", "")).lower() not in config.allowed_emails:
        raise OAuthError(
            "invalid_grant", "Authorization code subject is not permitted."
        )

    client_id = form.get("client_id", "")
    redirect_uri = form.get("redirect_uri", "")
    code_verifier = form.get("code_verifier", "")
    _validate_pkce_verifier(code_verifier)

    if str(payload.get("client_id", "")) != client_id:
        raise OAuthError(
            "invalid_grant", "client_id does not match the authorization code."
        )
    if str(payload.get("redirect_uri", "")) != redirect_uri:
        raise OAuthError(
            "invalid_grant", "redirect_uri does not match the authorization code."
        )
    if not hmac.compare_digest(
        _pkce_challenge(code_verifier),
        str(payload.get("code_challenge", "")),
    ):
        raise OAuthError("invalid_grant", "PKCE code_verifier is invalid.")

    code_resource = str(payload.get("resource", ""))
    requested_resource = form.get("resource", "")
    if not requested_resource:
        raise OAuthError("invalid_target", "The OAuth resource parameter is required.")
    if code_resource != config.resource_url or requested_resource != code_resource:
        raise OAuthError(
            "invalid_target", "OAuth resource does not match the authorization code."
        )

    requested_scope = form.get("scope")
    code_scope = str(payload.get("scope", ""))
    if requested_scope and set(requested_scope.split()) != set(code_scope.split()):
        raise OAuthError(
            "invalid_scope", "Requested scope differs from the authorization code."
        )

    replay_guard.consume(payload, "code")
    return _issue_token_pair(
        config=config,
        subject=str(payload["sub"]),
        client_id=client_id,
        resource=code_resource,
        scope=code_scope,
    )


def _exchange_refresh_token(
    form: Mapping[str, str],
    config: EmbeddedOAuthConfig,
    replay_guard: TokenReplayGuard,
) -> dict[str, object]:
    refresh_token = form.get("refresh_token", "")
    if not refresh_token:
        raise OAuthError("invalid_grant", "Missing refresh_token.")
    try:
        payload = _verify_payload(refresh_token, config.token_secret, "refresh")
    except OAuthError as exc:
        raise OAuthError("invalid_grant", exc.description) from exc

    if str(payload.get("iss", "")) != config.issuer_url:
        raise OAuthError("invalid_grant", "Refresh token issuer does not match.")
    if str(payload.get("sub", "")).lower() not in config.allowed_emails:
        raise OAuthError("invalid_grant", "Refresh token subject is not permitted.")

    client_id = form.get("client_id", "")
    if not client_id:
        raise OAuthError("invalid_grant", "Missing client_id.")
    if client_id != str(payload.get("client_id", "")):
        raise OAuthError("invalid_grant", "client_id does not match the refresh token.")

    token_resource = str(payload.get("aud", ""))
    requested_resource = form.get("resource", "")
    if not requested_resource:
        raise OAuthError("invalid_target", "The OAuth resource parameter is required.")
    if token_resource != config.resource_url or requested_resource != token_resource:
        raise OAuthError(
            "invalid_target", "OAuth resource does not match the refresh token."
        )

    token_scope = str(payload.get("scope", ""))
    requested_scope = form.get("scope")
    if requested_scope:
        requested = set(requested_scope.split())
        available = set(token_scope.split())
        if not requested or not requested.issubset(available):
            raise OAuthError(
                "invalid_scope", "Requested scope exceeds the refresh token scope."
            )
        token_scope = " ".join(sorted(requested))

    replay_guard.consume(payload, "refresh")
    return _issue_token_pair(
        config=config,
        subject=str(payload["sub"]),
        client_id=client_id,
        resource=token_resource,
        scope=token_scope,
    )


def register_embedded_oauth_routes(
    server: FastMCP,
    config: EmbeddedOAuthConfig,
) -> None:
    """Register public OAuth discovery, registration, authorization and token routes."""

    replay_guard = TokenReplayGuard()

    async def authorization_server_metadata(_: Request) -> JSONResponse:
        return _oauth_json(
            {
                "issuer": config.issuer_url,
                "authorization_endpoint": f"{config.issuer_url}/oauth/authorize",
                "token_endpoint": f"{config.issuer_url}/oauth/token",
                "registration_endpoint": f"{config.issuer_url}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none"],
                "scopes_supported": list(config.required_scopes),
                "client_id_metadata_document_supported": False,
                "authorization_response_iss_parameter_supported": True,
            }
        )

    server.custom_route(
        "/.well-known/oauth-authorization-server",
        methods=["GET"],
        include_in_schema=False,
    )(authorization_server_metadata)
    server.custom_route(
        "/.well-known/openid-configuration",
        methods=["GET"],
        include_in_schema=False,
    )(authorization_server_metadata)

    @server.custom_route("/oauth/register", methods=["POST"], include_in_schema=False)
    async def oauth_register(request: Request) -> JSONResponse:
        try:
            metadata: MutableMapping[str, object] = await request.json()
        except (json.JSONDecodeError, TypeError):
            metadata = {}
        if not isinstance(metadata, dict):
            return _json_error(
                OAuthError("invalid_client_metadata", "JSON object required.")
            )

        token_auth_method = str(metadata.get("token_endpoint_auth_method", "none"))
        if token_auth_method != "none":
            return _json_error(
                OAuthError(
                    "invalid_client_metadata",
                    "Only token_endpoint_auth_method=none is supported.",
                )
            )

        redirect_uris_raw = metadata.get("redirect_uris", [])
        if not isinstance(redirect_uris_raw, list) or not redirect_uris_raw:
            return _json_error(
                OAuthError(
                    "invalid_redirect_uri", "redirect_uris must be a non-empty array."
                )
            )
        if len(redirect_uris_raw) > 10:
            return _json_error(
                OAuthError(
                    "invalid_client_metadata", "At most 10 redirect URIs are allowed."
                )
            )

        redirect_uris = list(dict.fromkeys(str(uri) for uri in redirect_uris_raw))
        try:
            for redirect_uri in redirect_uris:
                _validate_redirect_uri(redirect_uri, config)
        except OAuthError as exc:
            return _json_error(OAuthError("invalid_redirect_uri", exc.description))

        grant_types = metadata.get(
            "grant_types", ["authorization_code", "refresh_token"]
        )
        response_types = metadata.get("response_types", ["code"])
        supported_grants = {"authorization_code", "refresh_token"}
        if (
            not isinstance(grant_types, list)
            or "authorization_code" not in grant_types
            or not set(str(value) for value in grant_types).issubset(supported_grants)
        ):
            return _json_error(
                OAuthError(
                    "invalid_client_metadata",
                    "grant_types must include authorization_code.",
                )
            )
        if not isinstance(response_types, list) or response_types != ["code"]:
            return _json_error(
                OAuthError(
                    "invalid_client_metadata", 'response_types must be ["code"].'
                )
            )

        client_id, issued_at, expires_at = _create_dynamic_client_id(
            redirect_uris, config
        )
        return _oauth_json(
            {
                "client_id": client_id,
                "client_id_issued_at": issued_at,
                "client_id_expires_at": expires_at,
                "token_endpoint_auth_method": "none",
                "redirect_uris": redirect_uris,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": config.scope_string,
            },
            status_code=201,
        )

    @server.custom_route(
        "/oauth/authorize",
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    async def oauth_authorize(request: Request) -> Response:
        try:
            form = (
                _parse_form_body(await request.body())
                if request.method == "POST"
                else {key: value for key, value in request.query_params.items()}
            )
            params = _validate_authorize_params(form, config)
        except OAuthError as exc:
            return _json_error(exc)

        if request.method == "GET":
            return _oauth_form(params, config)

        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        valid_email = email in config.allowed_emails
        valid_password = hmac.compare_digest(password, config.admin_password)
        if not valid_email or not valid_password:
            await asyncio.sleep(0.5)
            LOGGER.warning("Rejected OAuth login attempt for approved=%s", valid_email)
            return _oauth_form(params, config, error="Invalid email or password.")

        now = int(time.time())
        code = _sign_payload(
            {
                "typ": "code",
                "iss": config.issuer_url,
                "sub": email,
                "client_id": params["client_id"],
                "redirect_uri": params["redirect_uri"],
                "resource": params["resource"],
                "scope": params["scope"],
                "code_challenge": params["code_challenge"],
                "iat": now,
                "nbf": now,
                "exp": now + config.authorization_code_ttl_seconds,
                "jti": secrets.token_urlsafe(16),
            },
            config.token_secret,
        )
        redirect_url = _append_query(
            params["redirect_uri"],
            {
                "code": code,
                "iss": config.issuer_url,
                **({"state": params["state"]} if params.get("state") else {}),
            },
        )
        return RedirectResponse(
            redirect_url,
            status_code=302,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @server.custom_route("/oauth/token", methods=["POST"], include_in_schema=False)
    async def oauth_token(request: Request) -> JSONResponse:
        try:
            form = _parse_form_body(await request.body())
            grant_type = form.get("grant_type", "")
            if grant_type == "authorization_code":
                payload = _exchange_authorization_code(form, config, replay_guard)
            elif grant_type == "refresh_token":
                payload = _exchange_refresh_token(form, config, replay_guard)
            else:
                raise OAuthError("unsupported_grant_type", "Unsupported grant_type.")
            return _oauth_json(payload)
        except OAuthError as exc:
            return _json_error(exc)

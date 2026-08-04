"""Authentication for the GSC MCP server (spec 4.9, 10.1, 10.2, 10.3).

Single seam `get_gsc_service()` returns an authorized Search Console service
object. Tests patch `gsc_mcp.auth.get_gsc_service`.

Security contract:
- Only the readonly scope is ever requested (spec 3.1).
- No implicit credential discovery: only explicit env-var paths are consulted,
  and they must be absolute (spec 4.9).
- No silent OAuth→service-account fallback (spec 10.3).
- Tokens stored with a full scope are rejected at load time (spec 10.1).
- Token/credential contents are never logged or placed in tool output.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from . import config
from .errors import ErrorCode, GscError

logger = logging.getLogger("gsc_mcp.auth")

_BUILTIN_FALLBACK_PATHS: list[str] = []  # spec 4.9: NO implicit discovery


def _fail_fast_missing_paths() -> None:
    """Raise immediately if an explicit credential path is set but missing.

    Without this, a typo'd path would silently fall through to the (now empty)
    fallback list, producing a misleading error. Spec 4.9 / issue #25.
    """
    if config.CREDENTIALS_PATH and not os.path.exists(config.CREDENTIALS_PATH):
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            f"GSC_CREDENTIALS_PATH is set to {config.CREDENTIALS_PATH!r} but "
            "the file does not exist. It MUST be an absolute path to your "
            "service account JSON key file.",
            retryable=False,
        )
    if config.OAUTH_CLIENT_SECRETS_FILE and not os.path.exists(config.OAUTH_CLIENT_SECRETS_FILE):
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            f"GSC_OAUTH_CLIENT_SECRETS_FILE is set to "
            f"{config.OAUTH_CLIENT_SECRETS_FILE!r} but the file does not exist. "
            "It MUST be an absolute path to your OAuth client_secrets.json.",
            retryable=False,
        )


def _validate_token_scopes(creds: Credentials) -> None:
    """Reject tokens stored with the full (write) scope (spec 10.1).

    After tightening SCOPES to readonly, an old token carrying the full
    `webmasters` scope must not be silently reused.
    """
    token_scopes = getattr(creds, "scopes", None) or []
    # Normalize to strings.
    token_scopes_str = [str(s) for s in token_scopes]
    readonly = config.SCOPES[0]
    full_scope = "https://www.googleapis.com/auth/webmasters"
    if full_scope in token_scopes_str:
        raise GscError(
            ErrorCode.AUTH_EXPIRED,
            "Stored OAuth token was granted the full 'webmasters' scope, "
            "which is no longer permitted. Please log in again via "
            "`gsc-mcp auth login` to obtain a read-only token.",
            retryable=False,
        )
    if readonly not in token_scopes_str and token_scopes_str:
        # Token has some other scope set — require re-auth.
        raise GscError(
            ErrorCode.AUTH_EXPIRED,
            "Stored OAuth token does not carry the required read-only scope. "
            "Please log in again via `gsc-mcp auth login`.",
            retryable=False,
        )


def _build_service(creds: Any) -> Any:
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def get_gsc_service_oauth() -> Any:
    """Return an authorized service via OAuth (spec 10.1)."""
    if not config.OAUTH_CLIENT_SECRETS_FILE:
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            "OAuth mode selected but GSC_OAUTH_CLIENT_SECRETS_FILE is not set. "
            "Set it to an absolute path to your client_secrets.json, then run "
            "`gsc-mcp auth login`.",
            retryable=False,
        )
    creds: Credentials | None = None
    if os.path.exists(config.TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(config.TOKEN_FILE, config.SCOPES)
            _validate_token_scopes(creds)
        except GscError:
            # Scope mismatch — force re-auth by deleting the offending token.
            try:
                os.remove(config.TOKEN_FILE)
            except OSError:
                pass
            raise
        except Exception:
            # Corrupted token file — start fresh.
            try:
                os.remove(config.TOKEN_FILE)
            except OSError:
                pass
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _write_token(creds)
        else:
            # No valid token — cannot run the interactive OAuth flow from an
            # MCP subprocess reliably. Surface a clear AUTH_REQUIRED so the
            # operator runs `gsc-mcp auth login` from a terminal.
            raise GscError(
                ErrorCode.AUTH_REQUIRED,
                "No valid OAuth token. Run `gsc-mcp auth login` in a terminal "
                "to complete the browser login flow.",
                retryable=False,
            )
    return _build_service(creds)


def get_gsc_service_service_account() -> Any:
    """Return an authorized service via a service account (spec 10.2)."""
    if not config.CREDENTIALS_PATH:
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            "Service-account mode selected but GSC_CREDENTIALS_PATH is not set. "
            "Set it to an absolute path to your service account JSON key.",
            retryable=False,
        )
    if not os.path.exists(config.CREDENTIALS_PATH):
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            f"GSC_CREDENTIALS_PATH points to {config.CREDENTIALS_PATH!r} but "
            "the file does not exist.",
            retryable=False,
        )
    try:
        creds = service_account.Credentials.from_service_account_file(
            config.CREDENTIALS_PATH, scopes=config.SCOPES,
        )
    except Exception as exc:
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            "Failed to load service account credentials. Verify the JSON key "
            "file is valid and the path is correct.",
            retryable=False,
        ) from exc
    return _build_service(creds)


def get_gsc_service() -> Any:
    """Return an authorized Search Console service object (single seam).

    Uses GSC_AUTH_MODE to pick OAuth or service-account. No silent fallback
    (spec 10.3).
    """
    _fail_fast_missing_paths()

    if config.AUTH_MODE == "oauth":
        return get_gsc_service_oauth()
    if config.AUTH_MODE == "service_account":
        return get_gsc_service_service_account()
    # config.py already validates AUTH_MODE at import; defensive guard here.
    raise GscError(
        ErrorCode.INTERNAL_ERROR,
        f"Unknown GSC_AUTH_MODE '{config.AUTH_MODE}'.",
        retryable=False,
    )


def _write_token(creds: Credentials) -> None:
    """Persist an OAuth token to disk with restrictive permissions (spec 10.1)."""
    with open(config.TOKEN_FILE, "w") as token:
        token.write(creds.to_json())
    # Best-effort 0600 on POSIX; no-op on Windows (acl differs).
    try:
        os.chmod(config.TOKEN_FILE, 0o600)
    except OSError:
        pass


def run_oauth_login_flow() -> str:
    """Interactive OAuth login flow, called from the CLI (spec 4.1, 10.1).

    Opens a browser window for Google login and stores the resulting token.
    Returns a human-readable status string. This MUST NOT be callable as an
    MCP tool — only the CLI invokes it.
    """
    if not config.OAUTH_CLIENT_SECRETS_FILE or not os.path.exists(config.OAUTH_CLIENT_SECRETS_FILE):
        raise GscError(
            ErrorCode.AUTH_REQUIRED,
            "OAuth client secrets file not found. Set "
            "GSC_OAUTH_CLIENT_SECRETS_FILE to an absolute path before running "
            "`gsc-mcp auth login`.",
            retryable=False,
        )
    flow = InstalledAppFlow.from_client_secrets_file(config.OAUTH_CLIENT_SECRETS_FILE, config.SCOPES)
    creds = flow.run_local_server(port=0)
    _write_token(creds)
    return "Successfully authenticated with Google and stored a read-only token."


def auth_status() -> str:
    """Report current auth status WITHOUT exposing token/secret contents."""
    parts: list[str] = []
    parts.append(f"auth_mode: {config.AUTH_MODE}")
    if config.AUTH_MODE == "oauth":
        has_token = os.path.exists(config.TOKEN_FILE)
        parts.append(f"token_present: {has_token}")
        if config.OAUTH_CLIENT_SECRETS_FILE:
            parts.append(f"client_secrets: present ({os.path.exists(config.OAUTH_CLIENT_SECRETS_FILE)})")
        else:
            parts.append("client_secrets: not configured")
    else:
        parts.append(f"service_account_json: {bool(config.CREDENTIALS_PATH) and os.path.exists(config.CREDENTIALS_PATH)}")
    return "\n".join(parts)


def logout() -> str:
    """Delete the stored OAuth token (CLI only)."""
    if os.path.exists(config.TOKEN_FILE):
        os.remove(config.TOKEN_FILE)
        return "OAuth token removed."
    return "No OAuth token was present."


__all__ = [
    "get_gsc_service", "get_gsc_service_oauth", "get_gsc_service_service_account",
    "run_oauth_login_flow", "auth_status", "logout",
]

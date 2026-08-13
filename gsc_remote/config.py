# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/config.py).
"""Environment configuration for the remote MCP server."""

import os
from dataclasses import dataclass
from datetime import timedelta

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


@dataclass(frozen=True)
class Config:
    port: int
    base_url: str
    google_client_id: str
    google_client_secret: str
    jwt_secret: str
    allowed_emails: set[str]
    allowed_google_domains: set[str]
    allow_open_access: bool
    access_token_ttl: timedelta
    trust_proxy: bool
    log_level: str
    token_db_path: str


def _csv_set(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def load() -> Config:
    # The access allowlist is configured exclusively via environment variables.
    # No domain or email is ever hard coded — this repo is public and must
    # contain no deployment-specific values.
    return Config(
        port=int(os.getenv("PORT", "8080")),
        base_url=os.getenv("BASE_URL", "http://localhost:8080").rstrip("/"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        jwt_secret=os.getenv("JWT_SECRET", ""),
        allowed_emails=_csv_set(os.getenv("ALLOWED_EMAILS", "")),
        allowed_google_domains=_csv_set(
            os.getenv("ALLOWED_GOOGLE_DOMAINS", "")
        ),
        # Without an allowlist the server would accept any Google account, so
        # that state has to be chosen deliberately rather than reached by
        # forgetting an env var. See gsc_remote.allowlist.
        allow_open_access=os.getenv("ALLOW_OPEN_ACCESS", "false").lower()
        in ("1", "true", "yes"),
        access_token_ttl=timedelta(
            seconds=int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "86400"))
        ),
        trust_proxy=os.getenv("TRUST_PROXY", "false").lower()
        in ("1", "true", "yes"),
        log_level=os.getenv("LOG_LEVEL", "info"),
        token_db_path=os.getenv("TOKEN_DB_PATH", "/data/tokens.db"),
    )

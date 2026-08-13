# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/google.py).
"""Google OAuth federation: authorization URL, token exchange, userinfo."""

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from google.oauth2.credentials import Credentials

from gsc_remote.config import GSC_SCOPE, Config

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def redirect_uri(cfg: Config) -> str:
    return cfg.base_url + "/oauth/callback"


def authorization_url(cfg: Config, state: str) -> str:
    params = {
        "client_id": cfg.google_client_id,
        "redirect_uri": redirect_uri(cfg),
        "response_type": "code",
        "scope": f"openid email {GSC_SCOPE}",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"


async def exchange_code(cfg: Config, code: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": cfg.google_client_id,
                "client_secret": cfg.google_client_secret,
                "redirect_uri": redirect_uri(cfg),
                "grant_type": "authorization_code",
            },
        )
    resp.raise_for_status()
    return resp.json()


async def fetch_userinfo(google_access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            GOOGLE_USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {google_access_token}"},
        )
    resp.raise_for_status()
    return resp.json()


def build_credentials(
    cfg: Config, google_access: str, google_refresh: Optional[str], expiry_epoch
) -> Credentials:
    expiry = None
    if expiry_epoch:
        # google-auth expects a naive UTC datetime.
        expiry = datetime.fromtimestamp(expiry_epoch, tz=timezone.utc).replace(
            tzinfo=None
        )
    return Credentials(
        token=google_access,
        refresh_token=google_refresh,
        token_uri=GOOGLE_TOKEN_ENDPOINT,
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        scopes=[GSC_SCOPE],
        expiry=expiry,
    )

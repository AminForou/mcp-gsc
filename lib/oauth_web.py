"""Web-flow Google OAuth helpers — used by /api/oauth/start and /api/oauth/callback.

The existing `gsc_server.py` uses InstalledAppFlow.run_local_server(), which
requires a local browser and TTY. That doesn't work on Vercel. This module
builds an equivalent ``Flow`` configured from environment variables instead of
a client_secrets.json file.
"""

from __future__ import annotations

import os
from typing import Optional

import requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


SCOPES = [
    "https://www.googleapis.com/auth/webmasters",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _client_config() -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in Vercel "
            "environment variables. Create a Web-application OAuth client in "
            "Google Cloud Console and copy its credentials."
        )
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }
    }


def redirect_uri() -> str:
    uri = os.environ.get("OAUTH_REDIRECT_URI")
    if not uri:
        raise RuntimeError(
            "OAUTH_REDIRECT_URI is not set. It must match the redirect URI "
            "registered in Google Cloud Console, e.g. "
            "https://<your-vercel-domain>/api/oauth/callback"
        )
    return uri


def _flow() -> Flow:
    return Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=redirect_uri())


def build_authorize_url(state: str) -> str:
    """Build the Google consent URL. ``prompt=consent`` ensures we always get a refresh_token."""
    auth_url, _ = _flow().authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return auth_url


def exchange_code(code: str) -> Credentials:
    flow = _flow()
    flow.fetch_token(code=code)
    return flow.credentials


def userinfo_email(creds: Credentials) -> Optional[str]:
    """Resolve the Google account email tied to these credentials."""
    resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {creds.token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("email")

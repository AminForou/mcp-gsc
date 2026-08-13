from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from gsc_remote import google
from gsc_remote.config import Config


def _cfg():
    return Config(
        port=8080,
        base_url="https://gsc.example.com",
        google_client_id="cid",
        google_client_secret="csec",
        jwt_secret="jwt",
        allowed_emails=set(),
        allowed_google_domains={"example.com"},
        allow_open_access=False,
        access_token_ttl=timedelta(hours=24),
        trust_proxy=False,
        log_level="info",
        token_db_path=":memory:",
    )


def test_redirect_uri_is_derived_from_base_url():
    assert google.redirect_uri(_cfg()) == (
        "https://gsc.example.com/oauth/callback"
    )


def test_authorization_url_requests_offline_readonly_access():
    url = google.authorization_url(_cfg(), "st-1")
    assert url.startswith(google.GOOGLE_AUTH_ENDPOINT)
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["st-1"]
    assert q["client_id"] == ["cid"]
    assert q["scope"] == [
        "openid email https://www.googleapis.com/auth/webmasters.readonly"
    ]


@pytest.mark.anyio
async def test_exchange_code_posts_client_credentials():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(google.GOOGLE_TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"access_token": "ga", "refresh_token": "gr"}
            )
        )
        result = await google.exchange_code(_cfg(), "the-code")
    assert result["access_token"] == "ga"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["code"] == ["the-code"]
    assert body["client_secret"] == ["csec"]
    assert body["grant_type"] == ["authorization_code"]


@pytest.mark.anyio
async def test_exchange_code_raises_on_google_error():
    with respx.mock:
        respx.post(google.GOOGLE_TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await google.exchange_code(_cfg(), "bad")


@pytest.mark.anyio
async def test_fetch_userinfo_sends_bearer_token():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(google.GOOGLE_USERINFO_ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"sub": "1", "email": "user@example.com"}
            )
        )
        info = await google.fetch_userinfo("ga")
    assert info["email"] == "user@example.com"
    assert route.calls[0].request.headers["authorization"] == "Bearer ga"


def test_build_credentials_carries_the_readonly_scope():
    creds = google.build_credentials(_cfg(), "ga", "gr", None)
    assert creds.token == "ga"
    assert creds.refresh_token == "gr"
    assert creds.scopes == [
        "https://www.googleapis.com/auth/webmasters.readonly"
    ]
    assert creds.expiry is None


def test_build_credentials_converts_expiry_to_naive_utc():
    creds = google.build_credentials(_cfg(), "ga", "gr", 1_700_000_000)
    assert creds.expiry is not None
    assert creds.expiry.tzinfo is None

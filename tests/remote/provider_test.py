import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from gsc_remote.config import Config
from gsc_remote.provider import GoogleMCPProvider
from gsc_remote.store import TokenStore


def _cfg(tmp_path):
    return Config(
        port=8080,
        base_url="https://gsc.example.com",
        google_client_id="cid",
        google_client_secret="csec",
        jwt_secret="jwt",
        allowed_emails=set(),
        allowed_google_domains={"example.com"},
        allow_open_access=False,
        access_token_ttl=timedelta(seconds=60),
        trust_proxy=False,
        log_level="info",
        token_db_path=str(tmp_path / "t.db"),
    )


@pytest.fixture
def provider(tmp_path):
    cfg = _cfg(tmp_path)
    return GoogleMCPProvider(cfg, TokenStore(cfg.token_db_path))


def _client():
    return OAuthClientInformationFull(
        client_id="c1",
        client_secret="s1",
        redirect_uris=[AnyUrl("https://client.example.com/cb")],
    )


@pytest.mark.anyio
async def test_client_registration_roundtrip(provider):
    client = _client()
    await provider.register_client(client)
    loaded = await provider.get_client("c1")
    assert loaded.client_id == "c1"
    assert await provider.get_client("nope") is None


@pytest.mark.anyio
async def test_authorize_redirects_to_google_and_stores_state(provider):
    client = _client()
    await provider.register_client(client)
    url = await provider.authorize(
        client,
        AuthorizationParams(
            state="st-1",
            scopes=["openid"],
            code_challenge="ch",
            redirect_uri=AnyUrl("https://client.example.com/cb"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    assert url.startswith("https://accounts.google.com/")
    assert parse_qs(urlparse(url).query)["state"] == ["st-1"]
    assert provider.store.pop_state("st-1")["client_id"] == "c1"


def _seed_code(provider, code="code-1"):
    provider.store.save_auth_code(
        code=code,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        subject="sub-1",
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        expires_at=time.time() + 600,
    )


@pytest.mark.anyio
async def test_code_exchange_issues_a_token_and_burns_the_code(provider):
    client = _client()
    await provider.register_client(client)
    _seed_code(provider)
    auth_code = await provider.load_authorization_code(client, "code-1")
    assert auth_code is not None
    token = await provider.exchange_authorization_code(client, auth_code)
    assert token.token_type == "Bearer"
    assert token.expires_in == 60
    assert provider.store.get_auth_code("code-1") is None
    row = provider.store.get_by_access(token.access_token)
    assert row["google_refresh"] == "gr"
    assert row["subject"] == "sub-1"


@pytest.mark.anyio
async def test_code_belonging_to_another_client_is_rejected(provider):
    _seed_code(provider)
    other = OAuthClientInformationFull(
        client_id="c2",
        client_secret="s2",
        redirect_uris=[AnyUrl("https://other.example.com/cb")],
    )
    assert await provider.load_authorization_code(other, "code-1") is None


@pytest.mark.anyio
async def test_expired_code_is_rejected(provider):
    client = _client()
    provider.store.save_auth_code(
        code="old",
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        subject="sub-1",
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        expires_at=time.time() - 1,
    )
    assert await provider.load_authorization_code(client, "old") is None


@pytest.mark.anyio
async def test_refresh_rotates_both_tokens_and_keeps_google_grant(provider):
    client = _client()
    await provider.register_client(client)
    _seed_code(provider)
    auth_code = await provider.load_authorization_code(client, "code-1")
    first = await provider.exchange_authorization_code(client, auth_code)

    refresh = await provider.load_refresh_token(client, first.refresh_token)
    second = await provider.exchange_refresh_token(client, refresh, ["openid"])

    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert provider.store.get_by_access(first.access_token) is None
    assert provider.store.get_by_access(second.access_token)["google_refresh"] == "gr"


@pytest.mark.anyio
async def test_expired_access_token_does_not_load(provider):
    provider.store.save_token(
        access_token="stale",
        refresh_token="r",
        client_id="c1",
        scopes=["openid"],
        expires_at=time.time() - 1,
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        subject="sub-1",
    )
    assert await provider.load_access_token("stale") is None


@pytest.mark.anyio
async def test_revoke_deletes_the_token(provider):
    client = _client()
    await provider.register_client(client)
    _seed_code(provider)
    auth_code = await provider.load_authorization_code(client, "code-1")
    token = await provider.exchange_authorization_code(client, auth_code)
    access = await provider.load_access_token(token.access_token)
    await provider.revoke_token(access)
    assert await provider.load_access_token(token.access_token) is None


# --- allowlist re-check on refresh -----------------------------------------


def _seed_code_with_identity(provider, email, code="code-id"):
    provider.store.save_auth_code(
        code=code,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        subject="sub-1",
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        expires_at=time.time() + 600,
        email=email,
        hd=None,
    )
    return code


@pytest.mark.anyio
async def test_authorize_stores_a_binding_hash(provider):
    client = _client()
    await provider.register_client(client)
    await provider.authorize(
        client,
        AuthorizationParams(
            state="st-b",
            scopes=["openid"],
            code_challenge="ch",
            redirect_uri=AnyUrl("https://client.example.com/cb"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    assert provider.store.pop_state("st-b")["binding_hash"]


@pytest.mark.anyio
async def test_refresh_still_works_for_a_permitted_identity(provider):
    client = _client()
    await provider.register_client(client)
    code = _seed_code_with_identity(provider, "user@example.com")
    auth_code = await provider.load_authorization_code(client, code)
    first = await provider.exchange_authorization_code(client, auth_code)
    refresh = await provider.load_refresh_token(client, first.refresh_token)
    second = await provider.exchange_refresh_token(client, refresh, ["openid"])
    assert second.access_token != first.access_token


@pytest.mark.anyio
async def test_refresh_is_refused_once_the_identity_is_deprovisioned(provider):
    """A user removed from the allowed domain must lose access at the next
    refresh, not keep it for the life of a non-expiring refresh token."""
    client = _client()
    await provider.register_client(client)
    code = _seed_code_with_identity(provider, "leaver@example.com")
    auth_code = await provider.load_authorization_code(client, code)
    first = await provider.exchange_authorization_code(client, auth_code)
    refresh = await provider.load_refresh_token(client, first.refresh_token)

    # Simulate the operator dropping example.com from the allowlist.
    provider.cfg = _cfg_with_domains(provider.cfg, {"other.example"})

    with pytest.raises(ValueError):
        await provider.exchange_refresh_token(client, refresh, ["openid"])
    # And the stored grant is gone, so a retry cannot succeed either.
    assert provider.store.get_by_refresh(first.refresh_token) is None


def _cfg_with_domains(cfg, domains):
    import dataclasses

    return dataclasses.replace(cfg, allowed_google_domains=domains)

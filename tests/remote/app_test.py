import importlib
import os
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from gsc_remote import app as app_mod
from gsc_remote import statebinding
from gsc_remote.config import load as load_config
from gsc_remote.store import TokenStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SECRET", "jwt")
    # The MCP SDK's create_auth_routes() requires an HTTPS issuer URL, with the
    # sole exception of localhost/127.0.0.1 over HTTP. Use http://localhost so
    # the auth routes build under the test client.
    monkeypatch.setenv("BASE_URL", "http://localhost")
    monkeypatch.setenv("TOKEN_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLOWED_GOOGLE_DOMAINS", "example.com")
    importlib.reload(app_mod)
    return TestClient(
        app_mod.create_app(load_config()), base_url="http://localhost"
    )


def test_health_is_open(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "service": "gsc-mcp"}


def test_protected_resource_metadata_served(client):
    resp = client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_servers" in body
    assert "https://www.googleapis.com/auth/webmasters.readonly" in (
        body["scopes_supported"]
    )


def test_authorization_server_metadata_served(client):
    resp = client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["registration_endpoint"].endswith("/register")


def test_mcp_requires_auth(client):
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def _seed_state(db_path: str, state: str, binding="the-binding") -> str:
    """Seed a federation state row and return the binding cookie value."""
    store = TokenStore(db_path)
    store.save_state(
        state=state,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        expires_at=time.time() + 600,
        binding_hash=statebinding.hash_binding(binding) if binding else None,
    )
    return binding


def _cookie(value):
    """The binding cookie as a request header, sent the way a browser would."""
    return {"Cookie": f"{statebinding.COOKIE_NAME}={value}"}


def _mock_google(mock, email):
    mock.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ga",
                "refresh_token": "gr",
                "expires_in": 3600,
            },
        )
    )
    mock.get("https://openidconnect.googleapis.com/v1/userinfo").mock(
        return_value=httpx.Response(
            200, json={"sub": "1", "email": email, "email_verified": True}
        )
    )


def test_oauth_callback_allowed_domain_issues_a_code(client):
    db_path = os.environ["TOKEN_DB_PATH"]
    binding = _seed_state(db_path, "st-allow")
    with respx.mock(assert_all_called=True) as mock:
        _mock_google(mock, "user@example.com")
        resp = client.get(
            "/oauth/callback?code=x&state=st-allow",
            headers=_cookie(binding),
            follow_redirects=False,
        )
    assert resp.status_code == 302
    # The code must land at the client's registered redirect_uri and nowhere
    # else, so assert the parsed origin rather than a substring.
    location = urlparse(resp.headers["location"])
    assert location.scheme == "https"
    assert location.hostname == "client.example.com"
    assert location.path == "/cb"
    query = parse_qs(location.query)
    assert query["state"] == ["st-allow"]
    issued = query["code"][0]
    assert TokenStore(db_path).get_auth_code(issued) is not None


def test_oauth_callback_rejected_domain_returns_403(client):
    db_path = os.environ["TOKEN_DB_PATH"]
    binding = _seed_state(db_path, "st-deny")
    with respx.mock(assert_all_called=True) as mock:
        _mock_google(mock, "user@example.net")
        resp = client.get(
            "/oauth/callback?code=y&state=st-deny",
            headers=_cookie(binding),
            follow_redirects=False,
        )
    assert resp.status_code == 403


def test_oauth_callback_unknown_state_returns_400(client):
    resp = client.get(
        "/oauth/callback?code=z&state=never-issued", follow_redirects=False
    )
    assert resp.status_code == 400


def test_oauth_callback_google_error_returns_400(client):
    resp = client.get("/oauth/callback?error=access_denied", follow_redirects=False)
    assert resp.status_code == 400


# These assert against the module object the patch actually targeted, not a
# fresh `import gsc_server`. Upstream's test_gsc_server.py does
# `del sys.modules["gsc_server"]`, so a later plain import can hand back a
# DIFFERENT module object than the one gsc_remote captured — a test artifact
# only, since nothing does that at runtime.


def test_creating_the_app_applies_the_tool_filter(client):
    from gsc_remote import tools

    assert set(tools._gsc.mcp._tool_manager._tools) == set(
        tools.EXPECTED_REMOTE_TOOLS
    )


def test_creating_the_app_applies_the_credential_patch(client):
    from gsc_remote import credentials

    assert (
        credentials._gsc.get_gsc_service
        is credentials._patched_get_gsc_service
    )


def test_callback_without_the_binding_cookie_is_refused(client):
    """The authorization-code-injection regression: an attacker-initiated
    state completed in a victim's browser has no matching cookie."""
    db_path = os.environ["TOKEN_DB_PATH"]
    _seed_state(db_path, "st-attack")
    # No cookie header — this browser never visited /authorize.
    with respx.mock(assert_all_called=False) as mock:
        _mock_google(mock, "victim@example.com")
        resp = client.get(
            "/oauth/callback?code=v&state=st-attack", follow_redirects=False
        )
    assert resp.status_code == 400
    assert "did not start in this browser" in resp.text


def test_callback_with_a_wrong_binding_cookie_is_refused(client):
    db_path = os.environ["TOKEN_DB_PATH"]
    _seed_state(db_path, "st-wrong")
    with respx.mock(assert_all_called=False) as mock:
        _mock_google(mock, "victim@example.com")
        resp = client.get(
            "/oauth/callback?code=v&state=st-wrong",
            headers=_cookie("some-other-value"),
            follow_redirects=False,
        )
    assert resp.status_code == 400


def test_authorize_issues_the_binding_cookie(client):
    """End-to-end: the SDK's /authorize route must carry the Set-Cookie."""
    reg = client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example.com/cb"],
            "token_endpoint_auth_method": "client_secret_post",
        },
    )
    assert reg.status_code in (200, 201)
    client_id = reg.json()["client_id"]
    resp = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://client.example.com/cb",
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
            "state": "st-live",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (302, 307)
    # Compare the parsed host, not a substring: "accounts.google.com" appears
    # inside https://evil.example/?x=accounts.google.com too.
    location = urlparse(resp.headers["location"])
    assert location.scheme == "https"
    assert location.hostname == "accounts.google.com"
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(statebinding.COOKIE_NAME + "=")
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


# --- uvicorn proxy settings ------------------------------------------------


def _run_main(monkeypatch, tmp_path, trust_proxy):
    captured = {}
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SECRET", "jwt")
    monkeypatch.setenv("BASE_URL", "http://localhost")
    monkeypatch.setenv("TOKEN_DB_PATH", str(tmp_path / "m.db"))
    monkeypatch.setenv("ALLOWED_GOOGLE_DOMAINS", "example.com")
    monkeypatch.setenv("TRUST_PROXY", trust_proxy)
    monkeypatch.setattr(app_mod.uvicorn, "run", lambda *a, **kw: captured.update(kw))
    app_mod.main()
    return captured


def test_proxy_headers_are_trusted_only_when_configured(monkeypatch, tmp_path):
    """TRUST_PROXY=false must not leave uvicorn deriving request.client from a
    client-supplied X-Forwarded-For — that is the value _client_ip falls back
    to, so trusting it would hand the rate-limit key to the caller."""
    off = _run_main(monkeypatch, tmp_path, "false")
    assert off["proxy_headers"] is False
    assert off["forwarded_allow_ips"] == []

    on = _run_main(monkeypatch, tmp_path, "true")
    assert on["proxy_headers"] is True
    assert on["forwarded_allow_ips"] == "*"

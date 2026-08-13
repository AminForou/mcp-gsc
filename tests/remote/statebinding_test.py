"""Federation state must be bound to the browser that started the flow."""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from gsc_remote import statebinding


def test_binding_matches_only_the_issued_value():
    value = statebinding.new_binding()
    digest = statebinding.hash_binding(value)
    assert statebinding.binding_matches(value, digest) is True
    assert statebinding.binding_matches("wrong", digest) is False


def test_absent_cookie_or_hash_never_matches():
    digest = statebinding.hash_binding(statebinding.new_binding())
    assert statebinding.binding_matches(None, digest) is False
    assert statebinding.binding_matches("", digest) is False
    # A state row written without a binding must not become a free pass.
    assert statebinding.binding_matches("anything", None) is False


def _app(secure: bool, emit: bool = True):
    async def authorize(_request):
        if emit:
            statebinding.pending_binding.set("the-binding")
        return PlainTextResponse("redirecting")

    async def other(_request):
        statebinding.pending_binding.set("leaked")
        return PlainTextResponse("ok")

    return Starlette(
        routes=[
            Route("/authorize", authorize),
            Route("/other", other),
        ],
        middleware=[
            Middleware(statebinding.StateBindingMiddleware, secure=secure)
        ],
    )


def test_authorize_response_sets_a_hardened_cookie():
    resp = TestClient(_app(secure=True)).get("/authorize")
    cookie = resp.headers["set-cookie"]
    assert cookie.startswith(f"{statebinding.COOKIE_NAME}=the-binding")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    # Lax, not Strict: Google's redirect back to us is a cross-site top-level
    # navigation, which Strict would drop.
    assert "SameSite=Lax" in cookie
    assert "Path=/oauth/callback" in cookie


def test_cookie_omits_secure_over_plain_http():
    resp = TestClient(_app(secure=False)).get("/authorize")
    assert "Secure" not in resp.headers["set-cookie"]


def test_no_cookie_when_authorize_issued_none():
    resp = TestClient(_app(secure=True, emit=False)).get("/authorize")
    assert "set-cookie" not in resp.headers


def test_other_paths_never_get_the_cookie():
    resp = TestClient(_app(secure=True)).get("/other")
    assert "set-cookie" not in resp.headers

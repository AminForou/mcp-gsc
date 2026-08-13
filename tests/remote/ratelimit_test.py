from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from gsc_remote.ratelimit import RateLimitMiddleware, TokenBucket


def test_bucket_allows_burst_then_blocks():
    clock = [0.0]
    bucket = TokenBucket(rate=1, burst=3, now=lambda: clock[0])
    assert [bucket.allow("ip") for _ in range(3)] == [True, True, True]
    assert bucket.allow("ip") is False


def test_bucket_refills_over_time():
    clock = [0.0]
    bucket = TokenBucket(rate=1, burst=1, now=lambda: clock[0])
    assert bucket.allow("ip") is True
    assert bucket.allow("ip") is False
    clock[0] = 2.0
    assert bucket.allow("ip") is True


def test_buckets_are_per_key():
    clock = [0.0]
    bucket = TokenBucket(rate=1, burst=1, now=lambda: clock[0])
    assert bucket.allow("a") is True
    assert bucket.allow("b") is True


def _app(**kwargs):
    async def ok(_request):
        return PlainTextResponse("ok")

    defaults = dict(
        limited_prefixes=("/token",),
        rate=1,
        burst=2,
        max_body_bytes=100,
        trust_proxy=False,
    )
    defaults.update(kwargs)
    return Starlette(
        routes=[
            Route("/token", ok, methods=["POST"]),
            Route("/free", ok, methods=["POST"]),
        ],
        middleware=[Middleware(RateLimitMiddleware, **defaults)],
    )


def test_limited_prefix_returns_429_after_burst():
    client = TestClient(_app())
    assert client.post("/token", content=b"x").status_code == 200
    assert client.post("/token", content=b"x").status_code == 200
    assert client.post("/token", content=b"x").status_code == 429


def test_unlimited_path_is_untouched():
    client = TestClient(_app())
    for _ in range(5):
        assert client.post("/free", content=b"x").status_code == 200


def test_oversized_body_returns_413():
    client = TestClient(_app())
    resp = client.post("/token", content=b"x" * 200)
    assert resp.status_code == 413
    assert resp.json()["error"] == "request_too_large"


# --- X-Forwarded-For handling ---------------------------------------------
#
# Nginx appends the peer address to whatever the client sent, so the leftmost
# entry is attacker-controlled and the rightmost is ours.


def _xff_app():
    return _app(trust_proxy=True, rate=1, burst=2)


def test_spoofed_leftmost_xff_cannot_escape_the_bucket():
    client = TestClient(_xff_app())
    codes = [
        client.post(
            "/token",
            content=b"x",
            headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"},
        ).status_code
        for i in range(4)
    ]
    # All four share the real client IP 203.0.113.9 despite four different
    # spoofed leftmost values, so the burst of 2 still runs out.
    assert codes == [200, 200, 429, 429]


def test_distinct_real_clients_get_distinct_buckets():
    client = TestClient(_xff_app())
    first = client.post(
        "/token", content=b"x", headers={"X-Forwarded-For": "203.0.113.1"}
    )
    second = client.post(
        "/token", content=b"x", headers={"X-Forwarded-For": "203.0.113.2"}
    )
    assert (first.status_code, second.status_code) == (200, 200)


def test_xff_ignored_when_proxy_is_not_trusted():
    client = TestClient(_app(trust_proxy=False, rate=1, burst=1))
    assert client.post(
        "/token", content=b"x", headers={"X-Forwarded-For": "1.1.1.1"}
    ).status_code == 200
    assert client.post(
        "/token", content=b"x", headers={"X-Forwarded-For": "2.2.2.2"}
    ).status_code == 429

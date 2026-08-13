# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/ratelimit.py).
"""Per-IP token-bucket rate limiting and request body-size limits."""

import threading
import time

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send


class TokenBucket:
    def __init__(self, rate: float, burst: float, now=time.monotonic):
        self.rate = rate
        self.burst = burst
        self._now = now
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._now()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - last) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True


class RateLimitMiddleware:
    """Limits matched path prefixes per client IP and caps request body size."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limited_prefixes: tuple[str, ...],
        rate: float,
        burst: float,
        max_body_bytes: int,
        trust_proxy: bool,
    ):
        self.app = app
        self.limited_prefixes = limited_prefixes
        self.bucket = TokenBucket(rate, burst)
        self.max_body_bytes = max_body_bytes
        self.trust_proxy = trust_proxy

    def _client_ip(self, request: Request) -> str:
        if self.trust_proxy:
            xff = request.headers.get("x-forwarded-for")
            if xff:
                # Take the RIGHTMOST entry, not the leftmost. Nginx appends the
                # peer address to whatever X-Forwarded-For the client sent
                # (`$proxy_add_x_forwarded_for`), so the leftmost value is
                # attacker-controlled: sending a fresh random one per request
                # would give every request its own bucket and defeat limiting
                # entirely. The rightmost entry is the one our own proxy wrote.
                #
                # This assumes exactly one trusted proxy hop in front of the
                # app, which is the deployment (Nginx Proxy Manager -> here).
                # Adding a second proxy means skipping that many entries.
                hops = [part.strip() for part in xff.split(",") if part.strip()]
                if hops:
                    return hops[-1]
        return request.client.host if request.client else "unknown"

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        path = request.url.path
        if any(path.startswith(p) for p in self.limited_prefixes):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_body_bytes:
                response: Response = JSONResponse(
                    {"error": "request_too_large"}, status_code=413
                )
                await response(scope, receive, send)
                return
            if not self.bucket.allow(self._client_ip(request)):
                response = JSONResponse(
                    {"error": "rate_limited"}, status_code=429
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

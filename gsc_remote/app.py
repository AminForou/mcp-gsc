# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/app.py).
"""Remote HTTP app: OAuth Authorization Server + authenticated MCP endpoint."""

import contextlib
import logging
import secrets
import time
from urllib.parse import urlencode

import anyio
import httpx
import uvicorn
from mcp.server.auth.middleware.auth_context import (
    AuthContextMiddleware,
    get_access_token,
)
from mcp.server.auth.middleware.bearer_auth import (
    BearerAuthBackend,
    RequireAuthMiddleware,
)
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from starlette.routing import Mount, Route

from gsc_remote import allowlist, credentials, google, statebinding, tools
from gsc_remote.config import GSC_SCOPE, Config
from gsc_remote.config import load as load_config
from gsc_remote.provider import GoogleMCPProvider
from gsc_remote.ratelimit import RateLimitMiddleware
from gsc_remote.store import TokenStore

log = logging.getLogger("gsc_remote")

_CODE_TTL = 600
_PURGE_INTERVAL = 600


def create_app(cfg: Config) -> Starlette:
    credentials.apply_patch()
    tools.apply_filter()

    store = TokenStore(cfg.token_db_path)
    provider = GoogleMCPProvider(cfg, store)
    issuer = AnyHttpUrl(cfg.base_url)

    session_manager = StreamableHTTPSessionManager(
        app=tools.low_level_server(),
        event_store=None,
        json_response=False,
        stateless=True,
    )

    # --- credential-injecting ASGI wrapper for the MCP endpoint ---
    async def mcp_asgi(scope, receive, send):
        access = get_access_token()
        if access is not None:
            row = store.get_by_access(access.token)
            if row is not None:
                creds = google.build_credentials(
                    cfg,
                    row["google_access"],
                    row["google_refresh"],
                    row["google_expiry"],
                )
                with credentials.use_credentials(creds):
                    await session_manager.handle_request(scope, receive, send)
                    return
        await session_manager.handle_request(scope, receive, send)

    resource_metadata_url = build_resource_metadata_url(issuer)
    mcp_app = RequireAuthMiddleware(
        mcp_asgi,
        required_scopes=[],
        resource_metadata_url=resource_metadata_url,
    )

    # --- Google federation callback ---
    async def oauth_callback(request: Request):
        error = request.query_params.get("error")
        if error:
            return PlainTextResponse(f"Google error: {error}", status_code=400)
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        st = store.pop_state(state) if state else None
        if not code or st is None:
            return PlainTextResponse(
                "Invalid or expired state", status_code=400
            )
        # The browser finishing this flow must be the one that started it.
        if not statebinding.binding_matches(
            request.cookies.get(statebinding.COOKIE_NAME), st["binding_hash"]
        ):
            log.warning(
                "rejecting callback for state %s: missing or mismatched "
                "binding cookie",
                state,
            )
            return PlainTextResponse(
                "This sign-in did not start in this browser. Start again from "
                "your MCP client.",
                status_code=400,
            )
        try:
            tokens = await google.exchange_code(cfg, code)
            userinfo = await google.fetch_userinfo(tokens["access_token"])
        except httpx.HTTPError as exc:
            log.warning("google oauth exchange failed: %s", type(exc).__name__)
            return PlainTextResponse(
                "Upstream Google OAuth error", status_code=502
            )
        except Exception as exc:
            log.warning("google oauth exchange failed: %s", type(exc).__name__)
            return PlainTextResponse(
                "Upstream Google OAuth error", status_code=502
            )
        if not allowlist.identity_allowed(
            cfg,
            userinfo.get("email"),
            userinfo.get("hd"),
            userinfo.get("email_verified"),
        ):
            return PlainTextResponse(
                "Access denied: your Google account is not permitted on this "
                "server.",
                status_code=403,
            )
        our_code = secrets.token_urlsafe(32)
        store.save_auth_code(
            code=our_code,
            client_id=st["client_id"],
            redirect_uri=st["redirect_uri"],
            redirect_uri_provided_explicitly=st[
                "redirect_uri_provided_explicitly"
            ],
            code_challenge=st["code_challenge"],
            scopes=st["scopes"],
            resource=st["resource"],
            subject=userinfo.get("sub") or userinfo.get("email"),
            email=userinfo.get("email"),
            hd=userinfo.get("hd"),
            google_access=tokens["access_token"],
            google_refresh=tokens.get("refresh_token"),
            google_expiry=time.time() + int(tokens.get("expires_in", 3600)),
            expires_at=time.time() + _CODE_TTL,
        )
        sep = "&" if "?" in st["redirect_uri"] else "?"
        location = (
            st["redirect_uri"]
            + sep
            + urlencode({"code": our_code, "state": state})
        )
        return RedirectResponse(location, status_code=302)

    async def health(_request: Request):
        return JSONResponse({"status": "healthy", "service": "gsc-mcp"})

    routes = [
        Route("/health", health, methods=["GET"]),
        Route("/oauth/callback", oauth_callback, methods=["GET"]),
        *create_protected_resource_routes(
            resource_url=issuer,
            authorization_servers=[issuer],
            scopes_supported=[GSC_SCOPE],
        ),
        *create_auth_routes(
            provider=provider,
            issuer_url=issuer,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[GSC_SCOPE, "openid", "email"],
                default_scopes=[GSC_SCOPE],
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
        Mount("/mcp", app=mcp_app),
    ]

    token_verifier = ProviderTokenVerifier(provider)
    middleware = [
        Middleware(
            statebinding.StateBindingMiddleware,
            secure=cfg.base_url.startswith("https://"),
        ),
        Middleware(
            RateLimitMiddleware,
            limited_prefixes=(
                "/authorize",
                "/oauth/callback",
                "/token",
                "/register",
            ),
            rate=5,
            burst=15,
            max_body_bytes=1 << 20,
            trust_proxy=cfg.trust_proxy,
        ),
        Middleware(
            AuthenticationMiddleware, backend=BearerAuthBackend(token_verifier)
        ),
        Middleware(AuthContextMiddleware),
    ]

    async def _purge_loop():
        # Abandoned /authorize flows leave state rows behind and only a
        # completed callback removes them, so a startup-only purge lets the
        # table grow for the life of the process.
        while True:
            await anyio.sleep(_PURGE_INTERVAL)
            try:
                store.purge_expired()
            except Exception as exc:  # never let the sweep kill the server
                log.warning("purge failed: %s", type(exc).__name__)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        store.purge_expired()
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_purge_loop)
            async with session_manager.run():
                yield
            tasks.cancel_scope.cancel()

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()
    if not (
        cfg.google_client_id and cfg.google_client_secret and cfg.jwt_secret
    ):
        log.warning(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / JWT_SECRET not fully set; "
            "OAuth endpoints will fail until configured."
        )
    # Trust the reverse proxy's X-Forwarded-Proto/For so the app sees the
    # original https scheme and client IP (otherwise redirects downgrade to
    # http and rate limiting sees the proxy's IP). The container is only
    # reachable via the trusted proxy on the internal network.
    #
    # Both are tied to TRUST_PROXY. Left unconditional, TRUST_PROXY=false would
    # be the *more* dangerous setting: uvicorn would still rewrite
    # request.client from a client-supplied X-Forwarded-For, and that is
    # exactly the value _client_ip falls back to when it does not parse the
    # header itself — handing the rate-limit key to the caller.
    uvicorn.run(
        create_app(cfg),
        host="0.0.0.0",
        port=cfg.port,
        proxy_headers=cfg.trust_proxy,
        forwarded_allow_ips="*" if cfg.trust_proxy else [],
    )


if __name__ == "__main__":
    main()

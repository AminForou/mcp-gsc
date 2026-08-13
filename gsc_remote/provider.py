# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/provider.py).
"""OAuth 2.1 Authorization Server provider that federates to Google."""

import secrets
import time
from typing import Optional

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from gsc_remote import allowlist, google, statebinding
from gsc_remote.config import Config
from gsc_remote.store import TokenStore

_STATE_TTL = 600


class GoogleMCPProvider(OAuthAuthorizationServerProvider):
    def __init__(self, cfg: Config, store: TokenStore):
        self.cfg = cfg
        self.store = store

    async def get_client(
        self, client_id: str
    ) -> Optional[OAuthClientInformationFull]:
        return self.store.get_client(client_id)

    async def register_client(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        self.store.save_client(client_info)

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        state = params.state or secrets.token_urlsafe(32)
        # Bind this federation leg to the calling browser. The middleware turns
        # the value below into a Set-Cookie on this response; only its hash is
        # persisted. See gsc_remote.statebinding for the attack this stops.
        binding = statebinding.new_binding()
        statebinding.pending_binding.set(binding)
        self.store.save_state(
            state=state,
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=params.scopes or [],
            resource=params.resource,
            expires_at=time.time() + _STATE_TTL,
            binding_hash=statebinding.hash_binding(binding),
        )
        return google.authorization_url(self.cfg, state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        row = self.store.get_auth_code(authorization_code)
        if row is None or row["client_id"] != client.client_id:
            return None
        if row["expires_at"] < time.time():
            return None
        return AuthorizationCode(
            code=row["code"],
            scopes=row["scopes"],
            expires_at=row["expires_at"],
            client_id=row["client_id"],
            code_challenge=row["code_challenge"],
            redirect_uri=row["redirect_uri"],
            redirect_uri_provided_explicitly=row[
                "redirect_uri_provided_explicitly"
            ],
            resource=row["resource"],
            subject=row["subject"],
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        row = self.store.get_auth_code(authorization_code.code)
        if row is None:
            raise ValueError("unknown authorization code")
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        ttl = int(self.cfg.access_token_ttl.total_seconds())
        self.store.save_token(
            access_token=access,
            refresh_token=refresh,
            client_id=client.client_id,
            scopes=row["scopes"],
            expires_at=time.time() + ttl,
            google_access=row["google_access"],
            google_refresh=row["google_refresh"],
            google_expiry=row["google_expiry"],
            subject=row["subject"],
            email=row["email"],
            hd=row["hd"],
        )
        self.store.delete_auth_code(authorization_code.code)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ttl,
            scope=" ".join(row["scopes"]) or None,
            refresh_token=refresh,
        )

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        row = self.store.get_by_access(token)
        if row is None or row["expires_at"] < time.time():
            return None
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=int(row["expires_at"]),
            subject=row["subject"],
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        row = self.store.get_by_refresh(refresh_token)
        if row is None or row["client_id"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=row["scopes"],
            expires_at=None,
            subject=row["subject"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        row = self.store.get_by_refresh(refresh_token.token)
        if row is None:
            raise ValueError("unknown refresh token")
        # Re-check the allowlist on every refresh. It is otherwise enforced
        # only once, at sign-in, so a user removed from the allowed domain
        # would keep working access indefinitely — refresh tokens here do not
        # expire. Rows written before email was stored fall back to the
        # sign-in-time decision.
        if row["email"] is not None and not allowlist.identity_allowed(
            self.cfg, row["email"], row["hd"], True
        ):
            self.store.delete_by_token(refresh_token.token)
            raise ValueError("identity no longer permitted")
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        ttl = int(self.cfg.access_token_ttl.total_seconds())
        use_scopes = scopes or row["scopes"]
        self.store.rotate_token(
            old_refresh=refresh_token.token,
            access_token=access,
            refresh_token=refresh,
            client_id=row["client_id"],
            scopes=use_scopes,
            expires_at=time.time() + ttl,
            google_access=row["google_access"],
            google_refresh=row["google_refresh"],
            google_expiry=row["google_expiry"],
            subject=row["subject"],
            email=row["email"],
            hd=row["hd"],
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ttl,
            scope=" ".join(use_scopes) or None,
            refresh_token=refresh,
        )

    async def revoke_token(self, token) -> None:
        self.store.delete_by_token(token.token)

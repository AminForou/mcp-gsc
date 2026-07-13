import asyncio
import os
import unittest
import urllib.parse
from unittest.mock import patch

from starlette.testclient import TestClient

from chatgpt_server import build_server
from embedded_oauth import _pkce_challenge


class EmbeddedOAuthFlowTests(unittest.TestCase):
    public_url = "https://gsc-mcp.example.com"
    resource_url = f"{public_url}/"
    callback_url = "https://chatgpt.com/connector/oauth/test-callback"
    email = "ben@example.com"
    password = "correct horse battery staple"
    verifier = "A" * 43

    def setUp(self) -> None:
        self.environment = {
            "MCP_AUTH_MODE": "oauth",
            "MCP_PUBLIC_BASE_URL": self.public_url,
            "MCP_REQUIRED_SCOPES": "gsc.read",
            "MCP_REQUIRE_PROPERTY_ALLOWLIST": "false",
            "GSC_GOOGLE_AUTH_MODE": "upstream",
            "OAUTH_TOKEN_SECRET": "s" * 48,
            "OAUTH_ADMIN_PASSWORD": self.password,
            "OAUTH_ALLOWED_EMAILS": self.email,
            "OAUTH_ALLOWED_REDIRECT_HOSTS": "chatgpt.com",
        }
        self.env_patch = patch.dict(os.environ, self.environment, clear=True)
        self.env_patch.start()
        self.server = build_server()
        self.client_context = TestClient(self.server.streamable_http_app())
        self.client = self.client_context.__enter__()

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.env_patch.stop()

    def _register_client(self) -> str:
        response = self.client.post(
            "/oauth/register",
            json={
                "redirect_uris": [self.callback_url],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertTrue(payload["client_id"].startswith("dcr_"))
        return str(payload["client_id"])

    def _authorize(self, client_id: str) -> str:
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": self.callback_url,
            "scope": "gsc.read",
            "state": "state-123",
            "resource": self.resource_url,
            "code_challenge": _pkce_challenge(self.verifier),
            "code_challenge_method": "S256",
        }
        page = self.client.get("/oauth/authorize", params=params)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn("Authorize Google Search Console MCP", page.text)

        response = self.client.post(
            "/oauth/authorize",
            data={**params, "email": self.email, "password": self.password},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302, response.text)
        location = urllib.parse.urlparse(response.headers["location"])
        query = urllib.parse.parse_qs(location.query)
        self.assertEqual(query["state"], ["state-123"])
        self.assertEqual(query["iss"], [self.public_url])
        return query["code"][0]

    def _exchange_code(self, client_id: str, code: str, verifier: str | None = None):
        return self.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "redirect_uri": self.callback_url,
                "code": code,
                "code_verifier": verifier or self.verifier,
                "resource": self.resource_url,
            },
        )

    def test_complete_authorization_code_and_refresh_flow(self) -> None:
        metadata = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.json()["code_challenge_methods_supported"], ["S256"])
        self.assertEqual(
            metadata.json()["token_endpoint_auth_methods_supported"], ["none"]
        )

        resource_metadata = self.client.get("/.well-known/oauth-protected-resource")
        self.assertEqual(resource_metadata.status_code, 200)
        self.assertEqual(resource_metadata.json()["resource"], self.resource_url)

        client_id = self._register_client()
        code = self._authorize(client_id)
        token_response = self._exchange_code(client_id, code)
        self.assertEqual(token_response.status_code, 200, token_response.text)
        tokens = token_response.json()
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["scope"], "gsc.read")

        verified = asyncio.run(
            self.server._token_verifier.verify_token(tokens["access_token"])
        )
        self.assertIsNotNone(verified)
        self.assertEqual(verified.client_id, client_id)
        self.assertEqual(verified.resource, self.resource_url)
        self.assertEqual(verified.scopes, ["gsc.read"])

        replay = self._exchange_code(client_id, code)
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.json()["error"], "invalid_grant")

        refresh = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": self.resource_url,
            },
        )
        self.assertEqual(refresh.status_code, 200, refresh.text)
        self.assertNotEqual(refresh.json()["refresh_token"], tokens["refresh_token"])

        refresh_replay = self.client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": tokens["refresh_token"],
                "resource": self.resource_url,
            },
        )
        self.assertEqual(refresh_replay.status_code, 400)
        self.assertEqual(refresh_replay.json()["error"], "invalid_grant")

    def test_rejects_unapproved_redirect_during_registration(self) -> None:
        response = self.client.post(
            "/oauth/register",
            json={"redirect_uris": ["https://attacker.example/callback"]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_redirect_uri")

    def test_rejects_invalid_pkce_without_consuming_code(self) -> None:
        client_id = self._register_client()
        code = self._authorize(client_id)

        rejected = self._exchange_code(client_id, code, verifier="B" * 43)
        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(rejected.json()["error"], "invalid_grant")

        accepted = self._exchange_code(client_id, code)
        self.assertEqual(accepted.status_code, 200, accepted.text)

    def test_requires_resource_on_authorization_and_token_requests(self) -> None:
        client_id = self._register_client()
        response = self.client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": self.callback_url,
                "scope": "gsc.read",
                "code_challenge": _pkce_challenge(self.verifier),
                "code_challenge_method": "S256",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_target")


if __name__ == "__main__":
    unittest.main()

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from chatgpt_server import _extract_scopes, _guard_property, build_server


class ScopeExtractionTests(unittest.TestCase):
    def test_supports_common_scope_claim_formats(self) -> None:
        scopes = _extract_scopes(
            {
                "scope": "openid gsc.read",
                "scp": ["profile", "gsc.read"],
                "permissions": ["gsc.read", "tenant.read"],
            }
        )
        self.assertEqual(
            scopes,
            ["gsc.read", "openid", "profile", "tenant.read"],
        )


class PropertyGuardTests(unittest.TestCase):
    def test_rejects_property_outside_allowlist(self) -> None:
        async def tool(site_url: str, days: int = 28) -> str:
            return json.dumps({"site_url": site_url, "days": days})

        guarded = _guard_property(tool, {"sc-domain:example.com"})
        raw = asyncio.run(guarded("sc-domain:blocked.example"))
        payload = json.loads(raw)
        self.assertEqual(payload["error"], "property_not_allowed")

    def test_allows_exact_property(self) -> None:
        async def tool(site_url: str) -> str:
            return site_url

        guarded = _guard_property(tool, {"sc-domain:example.com"})
        result = asyncio.run(guarded("sc-domain:example.com"))
        self.assertEqual(result, "sc-domain:example.com")


class ServerBuildTests(unittest.TestCase):
    def test_registers_only_the_remote_read_only_surface(self) -> None:
        environment = {
            "MCP_AUTH_MODE": "none",
            "MCP_REQUIRE_PROPERTY_ALLOWLIST": "false",
            "GSC_GOOGLE_AUTH_MODE": "adc",
        }
        with patch.dict(os.environ, environment, clear=False):
            server = build_server()

        tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
        self.assertEqual(len(tools), 25)
        self.assertNotIn("add_site", tools)
        self.assertNotIn("delete_site", tools)
        self.assertNotIn("submit_sitemap", tools)
        self.assertIn("get_query_page_performance", tools)

        analytics = tools["get_search_analytics"]
        self.assertTrue(analytics.annotations.readOnlyHint)
        self.assertTrue(analytics.annotations.idempotentHint)
        self.assertTrue(analytics.annotations.openWorldHint)
        self.assertFalse(analytics.annotations.destructiveHint)

    def test_oauth_local_mode_does_not_require_jwks_or_external_issuer(self) -> None:
        environment = {
            "MCP_AUTH_MODE": "oauth_local",
            "MCP_PUBLIC_BASE_URL": "https://example.run.app",
            "MCP_OAUTH_AUDIENCE": "https://example.run.app",
            "MCP_REQUIRED_SCOPES": "gsc.read",
            "MCP_OAUTH_TOKEN_SECRET": "local-secret-value",
            "MCP_REQUIRE_PROPERTY_ALLOWLIST": "false",
            "GSC_GOOGLE_AUTH_MODE": "adc",
        }
        with patch.dict(os.environ, environment, clear=False):
            server = build_server()

        self.assertIsNotNone(server)

    def test_oauth_local_mode_requires_shared_secret(self) -> None:
        environment = {
            "MCP_AUTH_MODE": "oauth_local",
            "MCP_PUBLIC_BASE_URL": "https://example.run.app",
            "MCP_OAUTH_AUDIENCE": "https://example.run.app",
            "MCP_REQUIRED_SCOPES": "gsc.read",
            "MCP_REQUIRE_PROPERTY_ALLOWLIST": "false",
            "GSC_GOOGLE_AUTH_MODE": "adc",
        }
        with patch.dict(os.environ, environment, clear=False):
            with self.assertRaises(RuntimeError):
                build_server()


if __name__ == "__main__":
    unittest.main()

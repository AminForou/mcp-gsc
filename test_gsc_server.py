"""
Tests for gsc_server.py.

All Google API calls are mocked — no real credentials are needed to run these tests.
Run with: pytest test_gsc_server.py -v
"""
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# Helpers to reload the module with a clean environment each test
# ---------------------------------------------------------------------------

def _load_module(env_overrides: dict | None = None):
    """Import gsc_server with a fresh environment."""
    env = {
        "GSC_SKIP_OAUTH": "true",          # prevent live OAuth attempts by default
        "GSC_DATA_STATE": "all",
        "GSC_ALLOW_DESTRUCTIVE": "false",
        **(env_overrides or {}),
    }
    with patch.dict(os.environ, env, clear=False):
        if "gsc_server" in sys.modules:
            del sys.modules["gsc_server"]
        import gsc_server as mod
    return mod


# ---------------------------------------------------------------------------
# TestAuth
# ---------------------------------------------------------------------------

class TestAuth(unittest.TestCase):

    def test_token_loaded_from_config_dir(self):
        """TOKEN_FILE must resolve inside the user config dir, not SCRIPT_DIR."""
        mod = _load_module()
        # By default, TOKEN_FILE should NOT equal os.path.join(SCRIPT_DIR, "token.json").
        self.assertNotEqual(mod.TOKEN_FILE, os.path.join(mod.SCRIPT_DIR, "token.json"))

    def test_old_token_migrated_silently(self):
        """On first run after upgrade, a token at the old SCRIPT_DIR location is moved.

        SCRIPT_DIR is derived from __file__ at module load time, so this test places a
        real token.json in the actual SCRIPT_DIR and re-imports with a fresh GSC_CONFIG_DIR.
        The test cleans up after itself regardless of outcome.
        """
        # Discover the real SCRIPT_DIR by importing once
        if "gsc_server" in sys.modules:
            del sys.modules["gsc_server"]
        with patch.dict(os.environ, {"GSC_SKIP_OAUTH": "true", "GSC_DATA_STATE": "all",
                                     "GSC_ALLOW_DESTRUCTIVE": "false"}, clear=False):
            import gsc_server as _tmp
        actual_script_dir = _tmp.SCRIPT_DIR
        del sys.modules["gsc_server"]

        old_token_path = os.path.join(actual_script_dir, "token.json")
        old_token_content = '{"test": "migration_test"}'
        preexisting_backup = None

        with tempfile.TemporaryDirectory() as new_config_dir:
            try:
                # Back up any real existing token so we don't destroy it
                if os.path.exists(old_token_path):
                    preexisting_backup = old_token_path + ".test_bak"
                    import shutil as _shutil
                    _shutil.copy2(old_token_path, preexisting_backup)

                # Place test token in old location
                with open(old_token_path, "w") as f:
                    f.write(old_token_content)

                # Re-import with new config dir (no token there yet → migration should fire)
                env = {
                    "GSC_SKIP_OAUTH": "true",
                    "GSC_DATA_STATE": "all",
                    "GSC_ALLOW_DESTRUCTIVE": "false",
                    "GSC_CONFIG_DIR": new_config_dir,
                }
                with patch.dict(os.environ, env, clear=False):
                    import gsc_server as mod

                new_token_path = os.path.join(new_config_dir, "token.json")
                self.assertTrue(os.path.exists(new_token_path), "Token was not migrated to new location")
                self.assertFalse(os.path.exists(old_token_path), "Old token was not removed after migration")
                with open(new_token_path) as f:
                    self.assertEqual(f.read(), old_token_content)

            finally:
                del sys.modules["gsc_server"]
                # Clean up any leftover test token in SCRIPT_DIR
                if os.path.exists(old_token_path):
                    os.remove(old_token_path)
                # Restore original token if it existed
                if preexisting_backup and os.path.exists(preexisting_backup):
                    import shutil as _shutil
                    _shutil.move(preexisting_backup, old_token_path)

    def test_expired_token_refresh_succeeds(self):
        """If refresh succeeds, get_gsc_service_oauth returns without error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"GSC_SKIP_OAUTH": "false", "GSC_DATA_STATE": "all",
                   "GSC_ALLOW_DESTRUCTIVE": "false", "GSC_CONFIG_DIR": tmpdir}
            with patch.dict(os.environ, env, clear=False):
                if "gsc_server" in sys.modules:
                    del sys.modules["gsc_server"]
                import gsc_server as mod

            mock_creds = MagicMock()
            mock_creds.valid = False
            mock_creds.expired = True
            mock_creds.refresh_token = "refresh_token"
            mock_creds.to_json.return_value = '{"token": "refreshed"}'

            def fake_refresh(request):
                mock_creds.valid = True

            mock_creds.refresh.side_effect = fake_refresh

            with patch("gsc_server.Credentials.from_authorized_user_file", return_value=mock_creds), \
                 patch("gsc_server.build", return_value=MagicMock()), \
                 patch.object(mod, "TOKEN_FILE", os.path.join(tmpdir, "token.json")):
                open(os.path.join(tmpdir, "token.json"), "w").write("{}")
                service = mod.get_gsc_service_oauth()
                self.assertIsNotNone(service)

    def test_expired_token_no_refresh_raises_runtime_error(self):
        """When refresh fails and no secrets file, get_gsc_service_oauth raises RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"GSC_SKIP_OAUTH": "false", "GSC_DATA_STATE": "all",
                   "GSC_ALLOW_DESTRUCTIVE": "false", "GSC_CONFIG_DIR": tmpdir}
            with patch.dict(os.environ, env, clear=False):
                if "gsc_server" in sys.modules:
                    del sys.modules["gsc_server"]
                import gsc_server as mod

            mock_creds = MagicMock()
            mock_creds.valid = False
            mock_creds.expired = True
            mock_creds.refresh_token = None  # no refresh token available

            with patch("gsc_server.Credentials.from_authorized_user_file", return_value=mock_creds), \
                 patch.object(mod, "TOKEN_FILE", os.path.join(tmpdir, "token.json")), \
                 patch.object(mod, "OAUTH_CLIENT_SECRETS_FILE", os.path.join(tmpdir, "no_secrets.json")):
                open(os.path.join(tmpdir, "token.json"), "w").write("{}")
                with self.assertRaises((RuntimeError, FileNotFoundError)):
                    mod.get_gsc_service_oauth()

    def test_no_token_no_secrets_raises_file_not_found(self):
        """With no token file and no secrets file, FileNotFoundError is raised."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env = {"GSC_SKIP_OAUTH": "false", "GSC_DATA_STATE": "all",
                   "GSC_ALLOW_DESTRUCTIVE": "false", "GSC_CONFIG_DIR": tmpdir}
            with patch.dict(os.environ, env, clear=False):
                if "gsc_server" in sys.modules:
                    del sys.modules["gsc_server"]
                import gsc_server as mod

            with patch.object(mod, "TOKEN_FILE", os.path.join(tmpdir, "nonexistent_token.json")), \
                 patch.object(mod, "OAUTH_CLIENT_SECRETS_FILE", os.path.join(tmpdir, "nonexistent_secrets.json")):
                with self.assertRaises(FileNotFoundError):
                    mod.get_gsc_service_oauth()

    def test_skip_oauth_env_var(self):
        """GSC_SKIP_OAUTH=true makes get_gsc_service skip OAuth."""
        mod = _load_module({"GSC_SKIP_OAUTH": "true"})
        self.assertTrue(mod.SKIP_OAUTH)

    def test_gsc_credentials_path_set_but_missing_fails_fast(self):
        """When GSC_CREDENTIALS_PATH is set but the file does not exist, get_gsc_service
        must raise FileNotFoundError immediately with a message that names the specific
        path AND mentions uvx — instead of silently falling through to SCRIPT_DIR/cwd
        fallbacks that uvx users cannot reach. Regression guard for issue #25.
        """
        missing_path = "/tmp/definitely-does-not-exist-issue-25.json"
        mod = _load_module({
            "GSC_CREDENTIALS_PATH": missing_path,
            "GSC_SKIP_OAUTH": "true",
        })
        with self.assertRaises(FileNotFoundError) as ctx:
            mod.get_gsc_service()
        msg = str(ctx.exception)
        self.assertIn("GSC_CREDENTIALS_PATH", msg)
        self.assertIn(missing_path, msg)
        self.assertIn("uvx", msg.lower())

    def test_gsc_oauth_client_secrets_file_set_but_missing_fails_fast(self):
        """Same symmetry for OAuth: if GSC_OAUTH_CLIENT_SECRETS_FILE is set to a
        nonexistent file, get_gsc_service must fail fast with a clear message
        instead of silently falling through.
        """
        missing_path = "/tmp/definitely-does-not-exist-oauth-issue-25.json"
        mod = _load_module({
            "GSC_OAUTH_CLIENT_SECRETS_FILE": missing_path,
            "GSC_SKIP_OAUTH": "false",
        })
        with self.assertRaises(FileNotFoundError) as ctx:
            mod.get_gsc_service()
        msg = str(ctx.exception)
        self.assertIn("GSC_OAUTH_CLIENT_SECRETS_FILE", msg)
        self.assertIn(missing_path, msg)
        self.assertIn("uvx", msg.lower())

    def test_gsc_credentials_path_expands_tilde(self):
        """GSC_CREDENTIALS_PATH must expand ~ so users can write ~/creds.json."""
        mod = _load_module({"GSC_CREDENTIALS_PATH": "~/this-should-be-expanded.json"})
        self.assertIsNotNone(mod.GSC_CREDENTIALS_PATH)
        self.assertNotIn("~", mod.GSC_CREDENTIALS_PATH)
        self.assertTrue(mod.GSC_CREDENTIALS_PATH.startswith(os.path.expanduser("~")))


# ---------------------------------------------------------------------------
# Shared fixture helper
# ---------------------------------------------------------------------------

def _make_service():
    """Return a MagicMock that mimics the Google Search Console service object."""
    return MagicMock()


# ---------------------------------------------------------------------------
# TestListProperties
# ---------------------------------------------------------------------------

class TestListProperties(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_properties_list(self):
        mod = _load_module()
        service = _make_service()
        service.sites().list().execute.return_value = {
            "siteEntry": [
                {"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"},
                {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteFullUser"},
            ]
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.list_properties()
        data = json.loads(result)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["properties"][0]["site_url"], "https://example.com/")
        self.assertEqual(data["properties"][1]["permission_level"], "siteFullUser")

    async def test_returns_message_when_no_properties(self):
        mod = _load_module()
        service = _make_service()
        service.sites().list().execute.return_value = {}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.list_properties()
        self.assertIsInstance(result, str)
        self.assertIn("No Search Console properties", result)

    async def test_handles_api_error(self):
        mod = _load_module()
        with patch("gsc_server.get_gsc_service", side_effect=Exception("API error")):
            result = await mod.list_properties()
        self.assertIn("Error", result)

    async def test_surfaces_real_auth_error_not_hardcoded_message(self):
        """When auth fails with a FileNotFoundError, list_properties must surface the
        actual exception text (e.g. the OAuth failure reason), NOT a hardcoded
        service-account-only message. Regression guard for issue #25 comment by
        platky: an OAuth user saw "Service account credentials file not found" even
        though they had never configured service accounts.
        """
        mod = _load_module()
        real_error = FileNotFoundError(
            "OAuth token is missing or expired and cannot be refreshed."
        )
        with patch("gsc_server.get_gsc_service", side_effect=real_error):
            result = await mod.list_properties()
        self.assertIn("OAuth token is missing", result)
        self.assertNotIn("1. Create a service account in Google Cloud Console", result)


# ---------------------------------------------------------------------------
# TestGetSearchAnalytics
# ---------------------------------------------------------------------------

class TestGetSearchAnalytics(unittest.IsolatedAsyncioTestCase):

    def _make_rows(self):
        return {
            "rows": [
                {"keys": ["seo tool"], "clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5.0},
                {"keys": ["mcp server"], "clicks": 50, "impressions": 500, "ctr": 0.1, "position": 8.2},
            ]
        }

    async def test_returns_json_with_rows(self):
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.return_value = self._make_rows()
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_search_analytics("https://example.com/")
        data = json.loads(result)
        self.assertEqual(data["row_count"], 2)
        self.assertEqual(data["rows"][0]["query"], "seo tool")
        self.assertEqual(data["rows"][0]["clicks"], 100)
        self.assertIn("ctr", data["rows"][0])

    async def test_no_data_returns_string_message(self):
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.return_value = {}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_search_analytics("https://example.com/")
        self.assertIsInstance(result, str)
        self.assertNotIn("{", result[:5])  # not JSON

    async def test_row_limit_capped_at_500(self):
        """Requesting more than 500 rows should be capped."""
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.return_value = {"rows": []}
        with patch("gsc_server.get_gsc_service", return_value=service):
            await mod.get_search_analytics("https://example.com/", row_limit=9999)
        # Verify the request body capped at 500
        call_args = service.searchanalytics().query.call_args
        if call_args:
            body = call_args[1].get("body") or (call_args[0][0] if call_args[0] else None)
            if body and "rowLimit" in body:
                self.assertLessEqual(body["rowLimit"], 500)

    async def test_handles_404(self):
        mod = _load_module()
        with patch("gsc_server.get_gsc_service", side_effect=Exception("404")):
            result = await mod.get_search_analytics("https://example.com/")
        self.assertIn("not found", result.lower())


# ---------------------------------------------------------------------------
# TestGetSiteDetails
# ---------------------------------------------------------------------------

class TestGetSiteDetails(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_permission_and_verification(self):
        mod = _load_module()
        service = _make_service()
        service.sites().get().execute.return_value = {
            "permissionLevel": "siteOwner",
            "siteVerificationInfo": {"verificationState": "VERIFIED"},
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_site_details("https://example.com/")
        data = json.loads(result)
        self.assertEqual(data["permission_level"], "siteOwner")
        self.assertEqual(data["verification"]["state"], "VERIFIED")

    async def test_handles_404(self):
        mod = _load_module()
        with patch("gsc_server.get_gsc_service", side_effect=Exception("404")):
            result = await mod.get_site_details("https://example.com/")
        self.assertIn("Error", result)


# ---------------------------------------------------------------------------
# TestGetSitemaps
# ---------------------------------------------------------------------------

class TestGetSitemaps(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_sitemap_list(self):
        mod = _load_module()
        service = _make_service()
        service.sitemaps().list().execute.return_value = {
            "sitemap": [
                {"path": "https://example.com/sitemap.xml", "errors": "0", "warnings": "1",
                 "contents": [{"type": "web", "submitted": "1000"}]},
            ]
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_sitemaps("https://example.com/")
        data = json.loads(result)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["sitemaps"][0]["warnings"], 1)
        self.assertEqual(data["sitemaps"][0]["status"], "Has warnings")
        self.assertEqual(data["sitemaps"][0]["indexed_urls"], "1000")

    async def test_no_sitemaps_returns_message(self):
        mod = _load_module()
        service = _make_service()
        service.sitemaps().list().execute.return_value = {}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_sitemaps("https://example.com/")
        self.assertIsInstance(result, str)
        self.assertIn("No sitemaps", result)


# ---------------------------------------------------------------------------
# TestInspectUrl
# ---------------------------------------------------------------------------

class TestInspectUrl(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_verdict(self):
        mod = _load_module()
        service = _make_service()
        service.urlInspection().index().inspect().execute.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "coverageState": "Submitted and indexed",
                    "pageFetchState": "SUCCESSFUL",
                    "robotsTxtState": "ALLOWED",
                    "lastCrawlTime": "2026-04-01T10:00:00Z",
                }
            }
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.inspect_url_enhanced("https://example.com/", "https://example.com/page/")
        data = json.loads(result)
        self.assertEqual(data["verdict"], "PASS")
        self.assertEqual(data["page_url"], "https://example.com/page/")
        self.assertIn("last_crawled", data)


# ---------------------------------------------------------------------------
# TestBatchUrlInspection
# ---------------------------------------------------------------------------

class TestBatchUrlInspection(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_results(self):
        mod = _load_module()
        service = _make_service()
        service.urlInspection().index().inspect().execute.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "coverageState": "Submitted and indexed",
                    "lastCrawlTime": "2026-04-01T10:00:00Z",
                }
            }
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.batch_url_inspection(
                "https://example.com/",
                "https://example.com/a/\nhttps://example.com/b/"
            )
        data = json.loads(result)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["results"][0]["verdict"], "PASS")

    async def test_batch_limit_enforced_at_10_urls(self):
        mod = _load_module()
        with patch("gsc_server.get_gsc_service", return_value=_make_service()):
            urls = "\n".join([f"https://example.com/{i}/" for i in range(11)])
            result = await mod.batch_url_inspection("https://example.com/", urls)
        self.assertIn("Too many URLs", result)


# ---------------------------------------------------------------------------
# TestCheckIndexingIssues
# ---------------------------------------------------------------------------

class TestCheckIndexingIssues(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_summary(self):
        mod = _load_module()
        service = _make_service()
        service.urlInspection().index().inspect().execute.return_value = {
            "inspectionResult": {
                "indexStatusResult": {
                    "verdict": "PASS",
                    "coverageState": "Submitted and indexed",
                }
            }
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.check_indexing_issues(
                "https://example.com/", "https://example.com/page/"
            )
        data = json.loads(result)
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["total_checked"], 1)
        self.assertEqual(data["summary"]["indexed"], 1)


# ---------------------------------------------------------------------------
# TestGetPerformanceOverview
# ---------------------------------------------------------------------------

class TestGetPerformanceOverview(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_totals_and_trend(self):
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.side_effect = [
            {"rows": [{"keys": [], "clicks": 500, "impressions": 5000, "ctr": 0.1, "position": 12.0}]},
            {"rows": [
                {"keys": ["2026-04-01"], "clicks": 250, "impressions": 2500, "ctr": 0.1, "position": 12.0},
                {"keys": ["2026-04-02"], "clicks": 250, "impressions": 2500, "ctr": 0.1, "position": 12.0},
            ]},
        ]
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_performance_overview("https://example.com/")
        data = json.loads(result)
        self.assertEqual(data["totals"]["clicks"], 500)
        self.assertEqual(len(data["daily_trend"]), 2)


# ---------------------------------------------------------------------------
# TestGetAdvancedSearchAnalytics
# ---------------------------------------------------------------------------

class TestGetAdvancedSearchAnalytics(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_rows(self):
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.return_value = {
            "rows": [
                {"keys": ["seo"], "clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5.0},
            ]
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_advanced_search_analytics("https://example.com/")
        data = json.loads(result)
        self.assertEqual(data["rows"][0]["query"], "seo")
        self.assertIn("pagination", data)

    async def test_invalid_filters_json_returns_error_string(self):
        mod = _load_module()
        with patch("gsc_server.get_gsc_service", return_value=_make_service()):
            result = await mod.get_advanced_search_analytics(
                "https://example.com/", filters="not valid json"
            )
        self.assertIn("Invalid filters", result)

    async def test_pagination_info_included(self):
        mod = _load_module()
        service = _make_service()
        # Return exactly row_limit rows → has_more=True
        rows = [{"keys": [f"q{i}"], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5.0}
                for i in range(10)]
        service.searchanalytics().query().execute.return_value = {"rows": rows}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_advanced_search_analytics(
                "https://example.com/", row_limit=10
            )
        data = json.loads(result)
        self.assertTrue(data["pagination"]["has_more"])
        self.assertEqual(data["pagination"]["next_start_row"], 10)


# ---------------------------------------------------------------------------
# TestCompareSearchPeriods
# ---------------------------------------------------------------------------

class TestCompareSearchPeriods(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_comparison(self):
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.side_effect = [
            {"rows": [{"keys": ["seo"], "clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5.0}]},
            {"rows": [{"keys": ["seo"], "clicks": 120, "impressions": 1100, "ctr": 0.11, "position": 4.5}]},
        ]
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.compare_search_periods(
                "https://example.com/",
                "2026-03-01", "2026-03-28",
                "2026-04-01", "2026-04-07",
            )
        data = json.loads(result)
        self.assertIn("comparison", data)
        self.assertEqual(len(data["comparison"]), 1)
        self.assertEqual(data["comparison"][0]["key"], ["seo"])


# ---------------------------------------------------------------------------
# TestGetSearchByPageQuery
# ---------------------------------------------------------------------------

class TestGetSearchByPageQuery(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_with_totals(self):
        mod = _load_module()
        service = _make_service()
        service.searchanalytics().query().execute.return_value = {
            "rows": [
                {"keys": ["best seo tool"], "clicks": 50, "impressions": 500, "ctr": 0.1, "position": 7.5},
            ]
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_search_by_page_query(
                "https://example.com/", "https://example.com/blog/seo/"
            )
        data = json.loads(result)
        self.assertEqual(data["page_url"], "https://example.com/blog/seo/")
        self.assertEqual(data["totals"]["clicks"], 50)
        self.assertEqual(data["rows"][0]["query"], "best seo tool")


# ---------------------------------------------------------------------------
# TestListSitemapsEnhanced
# ---------------------------------------------------------------------------

class TestListSitemapsEnhanced(unittest.IsolatedAsyncioTestCase):

    async def test_returns_json_sitemap_list(self):
        mod = _load_module()
        service = _make_service()
        service.sitemaps().list().execute.return_value = {
            "sitemap": [
                {"path": "https://example.com/sitemap.xml", "errors": "0", "warnings": "0",
                 "isSitemapsIndex": False, "isPending": False},
            ]
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.list_sitemaps_enhanced("https://example.com/")
        data = json.loads(result)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["pending_count"], 0)

    async def test_warning_status_correctly_set(self):
        """Regression: status should be 'Has warnings' when warnings > 0."""
        mod = _load_module()
        service = _make_service()
        service.sitemaps().list().execute.return_value = {
            "sitemap": [
                {"path": "https://example.com/sitemap.xml", "errors": "0", "warnings": "3"},
            ]
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.list_sitemaps_enhanced("https://example.com/")
        # list_sitemaps_enhanced returns JSON without a status field (it's in get_sitemaps),
        # but warnings count must still be 3
        data = json.loads(result)
        self.assertEqual(data["sitemaps"][0]["warnings"], 3)


# ---------------------------------------------------------------------------
# TestGetSitemapDetails
# ---------------------------------------------------------------------------

class TestGetSitemapDetails(unittest.IsolatedAsyncioTestCase):

    async def test_get_details_returns_json(self):
        mod = _load_module()
        service = _make_service()
        service.sitemaps().get().execute.return_value = {
            "isSitemapsIndex": False,
            "isPending": False,
            "errors": "0",
            "warnings": "0",
            "contents": [{"type": "web", "submitted": 500, "indexed": 480}],
        }
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.get_sitemap_details("https://example.com/", "https://example.com/sitemap.xml")
        data = json.loads(result)
        self.assertEqual(data["type"], "Sitemap")
        self.assertEqual(data["status"], "processed")
        self.assertEqual(data["content_breakdown"][0]["submitted"], 500)


# ---------------------------------------------------------------------------
# TestSafetyGuards
# ---------------------------------------------------------------------------

class TestSafetyGuards(unittest.IsolatedAsyncioTestCase):

    async def test_add_site_blocked_by_default(self):
        mod = _load_module({"GSC_ALLOW_DESTRUCTIVE": "false"})
        result = await mod.add_site("https://newsite.com/")
        self.assertIn("Safety", result)

    async def test_delete_site_blocked_by_default(self):
        mod = _load_module({"GSC_ALLOW_DESTRUCTIVE": "false"})
        result = await mod.delete_site("https://newsite.com/")
        self.assertIn("Safety", result)

    async def test_delete_sitemap_blocked_by_default(self):
        mod = _load_module({"GSC_ALLOW_DESTRUCTIVE": "false"})
        result = await mod.delete_sitemap("https://example.com/", "https://example.com/sitemap.xml")
        self.assertIn("Safety", result)

    async def test_add_site_allowed_when_flag_set(self):
        mod = _load_module({"GSC_ALLOW_DESTRUCTIVE": "true"})
        service = _make_service()
        service.sites().add().execute.return_value = {}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.add_site("https://newsite.com/")
        self.assertNotIn("Safety", result)

    async def test_delete_site_allowed_when_flag_set(self):
        mod = _load_module({"GSC_ALLOW_DESTRUCTIVE": "true"})
        service = _make_service()
        service.sites().delete().execute.return_value = {}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.delete_site("https://example.com/")
        self.assertNotIn("Safety", result)

    async def test_delete_sitemap_allowed_when_flag_set(self):
        mod = _load_module({"GSC_ALLOW_DESTRUCTIVE": "true"})
        service = _make_service()
        service.sitemaps().delete().execute.return_value = {}
        with patch("gsc_server.get_gsc_service", return_value=service):
            result = await mod.delete_sitemap("https://example.com/", "https://example.com/sitemap.xml")
        self.assertNotIn("Safety", result)


# ---------------------------------------------------------------------------
# TestReauthenticate
# ---------------------------------------------------------------------------

class TestReauthenticate(unittest.IsolatedAsyncioTestCase):

    async def test_deletes_token_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = os.path.join(tmpdir, "token.json")
            open(token_path, "w").write('{"old": "token"}')
            secrets_path = os.path.join(tmpdir, "secrets.json")
            open(secrets_path, "w").write("{}")

            mod = _load_module()

            mock_creds = MagicMock()
            mock_creds.to_json.return_value = '{"token": "new"}'

            with patch.object(mod, "TOKEN_FILE", token_path), \
                 patch.object(mod, "OAUTH_CLIENT_SECRETS_FILE", secrets_path), \
                 patch("gsc_server.InstalledAppFlow") as mock_flow_cls:
                mock_flow = MagicMock()
                mock_flow.run_local_server.return_value = mock_creds
                mock_flow_cls.from_client_secrets_file.return_value = mock_flow
                result = await mod.reauthenticate()

            self.assertIn("Successfully authenticated", result)
            self.assertIn("Previous session deleted", result)
            self.assertTrue(os.path.exists(token_path))

    async def test_returns_error_when_no_secrets_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mod = _load_module()
            with patch.object(mod, "OAUTH_CLIENT_SECRETS_FILE", os.path.join(tmpdir, "no_secrets.json")):
                result = await mod.reauthenticate()
        self.assertIn("Error", result)


# ---------------------------------------------------------------------------
# TestStdoutClean
# ---------------------------------------------------------------------------

class TestStdoutClean(unittest.TestCase):

    def test_auth_fallback_does_not_write_to_stdout(self):
        """get_gsc_service must not print() to stdout on OAuth failure (prevents MCP corruption)."""
        mod = _load_module({"GSC_SKIP_OAUTH": "false"})

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        try:
            with patch("gsc_server.get_gsc_service_oauth", side_effect=RuntimeError("no token")), \
                 patch("gsc_server.service_account.Credentials.from_service_account_file",
                        side_effect=Exception("no file")):
                try:
                    mod.get_gsc_service()
                except Exception:
                    pass
        finally:
            sys.stdout = old_stdout

        stdout_output = captured.getvalue()
        self.assertEqual(stdout_output, "", f"Unexpected stdout: {stdout_output!r}")


# ---------------------------------------------------------------------------
# TestVercelBranch — covers the KV-backed multi-account flow
# ---------------------------------------------------------------------------

def _load_vercel_module(env_overrides: dict | None = None):
    """Reload gsc_server with MCP_TRANSPORT=vercel so RUNNING_ON_VERCEL is True."""
    env = {
        "MCP_TRANSPORT": "vercel",
        "GSC_DATA_STATE": "all",
        "GSC_ALLOW_DESTRUCTIVE": "false",
        **(env_overrides or {}),
    }
    with patch.dict(os.environ, env, clear=False):
        if "gsc_server" in sys.modules:
            del sys.modules["gsc_server"]
        # lib.token_store reads KV env vars at call time, so we don't need to
        # set them here unless a test exercises the network path.
        import gsc_server as mod
    return mod


class TestVercelBranch(unittest.TestCase):

    def test_running_on_vercel_skips_filesystem_init(self):
        mod = _load_vercel_module()
        self.assertTrue(mod.RUNNING_ON_VERCEL)
        # Filesystem-derived globals must NOT be set on Vercel — they default to
        # empty/None to avoid creating directories on read-only deploys.
        self.assertEqual(mod.TOKEN_FILE, "")
        self.assertEqual(mod.OAUTH_CLIENT_SECRETS_FILE, "")

    def test_get_gsc_service_no_accounts_raises_with_oauth_hint(self):
        mod = _load_vercel_module()
        fake_store = MagicMock()
        fake_store.get_default.return_value = None
        fake_store.list_accounts.return_value = []
        with patch.dict(sys.modules, {"lib.token_store": fake_store}):
            with self.assertRaises(FileNotFoundError) as ctx:
                mod.get_gsc_service()
        self.assertIn("oauth", str(ctx.exception).lower())

    def test_get_gsc_service_uses_stored_token(self):
        mod = _load_vercel_module()
        token_info = {
            "token": "access",
            "refresh_token": "refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "id",
            "client_secret": "secret",
            "scopes": mod.SCOPES,
        }
        fake_store = MagicMock()
        fake_store.get_default.return_value = "alice@example.com"
        fake_store.get_token.return_value = token_info

        mock_creds = MagicMock()
        mock_creds.valid = True

        with patch.dict(sys.modules, {"lib.token_store": fake_store}), \
             patch("gsc_server.Credentials.from_authorized_user_info", return_value=mock_creds), \
             patch("gsc_server.build", return_value=MagicMock()) as mock_build:
            service = mod.get_gsc_service()

        self.assertIsNotNone(service)
        fake_store.get_token.assert_called_once_with("alice@example.com")
        mock_build.assert_called_once()

    def test_get_gsc_service_explicit_account_overrides_default(self):
        mod = _load_vercel_module()
        fake_store = MagicMock()
        fake_store.get_token.return_value = {"token": "t", "refresh_token": "r",
                                             "token_uri": "x", "client_id": "i",
                                             "client_secret": "s", "scopes": mod.SCOPES}
        mock_creds = MagicMock(valid=True)
        with patch.dict(sys.modules, {"lib.token_store": fake_store}), \
             patch("gsc_server.Credentials.from_authorized_user_info", return_value=mock_creds), \
             patch("gsc_server.build", return_value=MagicMock()):
            mod.get_gsc_service("bob@example.com")
        fake_store.get_token.assert_called_once_with("bob@example.com")
        fake_store.get_default.assert_not_called()


class TestVercelTools(unittest.IsolatedAsyncioTestCase):

    async def test_list_linked_accounts_returns_pool(self):
        mod = _load_vercel_module()
        fake_store = MagicMock()
        fake_store.list_accounts.return_value = ["a@x.com", "b@x.com"]
        fake_store.get_default.return_value = "a@x.com"
        with patch.dict(sys.modules, {"lib.token_store": fake_store}):
            result = await mod.list_linked_accounts()
        payload = json.loads(result)
        self.assertEqual(payload["accounts"], ["a@x.com", "b@x.com"])
        self.assertEqual(payload["default"], "a@x.com")
        self.assertEqual(payload["count"], 2)

    async def test_reauthenticate_returns_oauth_start_url(self):
        mod = _load_vercel_module()
        with patch.dict(os.environ,
                        {"OAUTH_REDIRECT_URI": "https://x.vercel.app/api/oauth/callback"}):
            result = await mod.reauthenticate()
        self.assertIn("https://x.vercel.app/api/oauth/start", result)


# ---------------------------------------------------------------------------
# TestAuthGuard — bearer-token middleware for the MCP endpoint
# ---------------------------------------------------------------------------

class TestAuthGuard(unittest.IsolatedAsyncioTestCase):

    async def _call(self, app, headers):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/mcp",
            "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        }
        sent = []

        async def send(message):
            sent.append(message)

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        await app(scope, receive, send)
        status = next(m["status"] for m in sent if m["type"] == "http.response.start")
        return status, sent

    async def test_rejects_missing_bearer(self):
        from lib.auth_guard import bearer_required
        with patch.dict(os.environ, {"MCP_BEARER_TOKEN": "secret"}):
            inner = MagicMock()
            app = bearer_required(inner)
            status, _ = await self._call(app, {})
            self.assertEqual(status, 401)
            inner.assert_not_called()

    async def test_rejects_wrong_bearer(self):
        from lib.auth_guard import bearer_required
        with patch.dict(os.environ, {"MCP_BEARER_TOKEN": "secret"}):
            inner = MagicMock()
            app = bearer_required(inner)
            status, _ = await self._call(app, {"authorization": "Bearer wrong"})
            self.assertEqual(status, 401)
            inner.assert_not_called()

    async def test_accepts_correct_bearer(self):
        from lib.auth_guard import bearer_required

        called = {"hit": False}

        async def inner(scope, receive, send):
            called["hit"] = True
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"ok"})

        with patch.dict(os.environ, {"MCP_BEARER_TOKEN": "secret"}):
            app = bearer_required(inner)
            status, _ = await self._call(app, {"authorization": "Bearer secret"})
            self.assertEqual(status, 200)
            self.assertTrue(called["hit"])


if __name__ == "__main__":
    unittest.main()

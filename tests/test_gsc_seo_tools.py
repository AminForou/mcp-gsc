from __future__ import annotations

import json
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

import gsc_seo_tools as tools


class UrlNormalisationTests(TestCase):
    def test_variant_group_ignores_scheme_www_case_and_trailing_slash(self) -> None:
        left = "http://www.Example.com/Online-Bookings/"
        right = "https://example.com/online-bookings"
        self.assertEqual(tools._variant_group_key(left), tools._variant_group_key(right))

    def test_canonical_compare_preserves_trailing_slash_difference(self) -> None:
        left = "https://example.com/path"
        right = "https://example.com/path/"
        self.assertNotEqual(
            tools._canonical_compare_value(left), tools._canonical_compare_value(right)
        )

    def test_domain_property_allows_subdomains(self) -> None:
        self.assertTrue(
            tools._property_allows_url(
                "sc-domain:example.com", "https://www.example.com/sitemap.xml"
            )
        )
        self.assertFalse(
            tools._property_allows_url(
                "sc-domain:example.com", "https://example.net/sitemap.xml"
            )
        )


class SitemapParserTests(TestCase):
    def test_parse_urlset(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
          <url><loc>https://example.com/a/</loc></url>
          <url><loc>https://example.com/b/</loc></url>
        </urlset>"""
        document_type, locations = tools._parse_sitemap_document(payload)
        self.assertEqual(document_type, "urlset")
        self.assertEqual(
            locations, ["https://example.com/a/", "https://example.com/b/"]
        )

    def test_parse_sitemap_index(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
          <sitemap><loc>https://example.com/pages.xml</loc></sitemap>
        </sitemapindex>"""
        document_type, locations = tools._parse_sitemap_document(payload)
        self.assertEqual(document_type, "sitemapindex")
        self.assertEqual(locations, ["https://example.com/pages.xml"])


class SeoToolTests(IsolatedAsyncioTestCase):
    async def test_find_cannibalisation_groups_query_pages(self) -> None:
        rows = [
            {
                "query": "makeup artist gold coast",
                "page": "https://example.com/",
                "clicks": 10,
                "impressions": 100,
                "ctr": 0.1,
                "position": 3.0,
            },
            {
                "query": "makeup artist gold coast",
                "page": "https://example.com/services/",
                "clicks": 3,
                "impressions": 40,
                "ctr": 0.075,
                "position": 6.0,
            },
        ]
        with patch.object(tools, "_query_search_analytics", return_value=rows):
            result = json.loads(
                await tools.find_query_cannibalisation(
                    "sc-domain:example.com", "2026-01-01", "2026-01-31"
                )
            )
        self.assertEqual(result["finding_count"], 1)
        self.assertEqual(result["findings"][0]["competing_page_count"], 2)

    async def test_canonical_conflicts_classifies_equivalent_variant(self) -> None:
        inspection = {
            "page_url": "https://example.com/path",
            "user_canonical": "https://example.com/path/",
            "google_canonical": "https://www.example.com/path",
            "verdict": "PASS",
            "coverage_state": "Submitted and indexed",
            "last_crawled": "2026-01-01T00:00:00Z",
        }
        with patch.object(tools, "_inspect_many", return_value=([inspection], [])):
            result = json.loads(
                await tools.find_google_canonical_conflicts(
                    "sc-domain:example.com", urls="https://example.com/path"
                )
            )
        self.assertEqual(result["conflict_count"], 1)
        self.assertEqual(
            result["findings"][0]["status"],
            "google_selected_equivalent_url_variant",
        )

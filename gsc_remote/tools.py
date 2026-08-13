"""Restrict the upstream tool set to the read-only surface we expose remotely.

The remote server holds only ``webmasters.readonly``, so upstream's write tools
would fail with a 403 if a model called them. Rather than edit ``gsc_server``,
we remove them from FastMCP's registry at startup. The local/stdio-only
diagnostics go too: they describe credential files that do not exist here.
"""

import logging

import gsc_server as _gsc

log = logging.getLogger("gsc_remote")

REMOVED_TOOLS = frozenset(
    {
        # Write operations — not permitted under webmasters.readonly.
        "add_site",
        "delete_site",
        "submit_sitemap",
        "delete_sitemap",
        "manage_sitemaps",
        # Local-file-auth diagnostics — meaningless on a remote OAuth server.
        "reauthenticate",
        "get_capabilities",
        # Upstream promotional tool.
        "get_creator_info",
    }
)

EXPECTED_REMOTE_TOOLS = frozenset(
    {
        "list_properties",
        "get_site_details",
        "get_search_analytics",
        "get_advanced_search_analytics",
        "get_performance_overview",
        "compare_search_periods",
        "get_search_by_page_query",
        "get_sitemaps",
        "list_sitemaps_enhanced",
        "get_sitemap_details",
        "inspect_url_enhanced",
        "batch_url_inspection",
        "check_indexing_issues",
    }
)

# Snapshot taken before any filtering, so a test can still assert what upstream
# defines even after apply_filter() has run in the same process.
_UPSTREAM_TOOLS_AT_IMPORT = frozenset(_gsc.mcp._tool_manager._tools)


def low_level_server():
    """The low-level ``Server`` inside the upstream FastMCP instance.

    ``StreamableHTTPSessionManager`` needs this object, and FastMCP exposes it
    only as a private attribute. Isolated here so exactly one place depends on
    it, guarded by a test.
    """
    return _gsc.mcp._mcp_server


def apply_filter() -> None:
    """Remove non-read-only tools from the registry. Idempotent."""
    manager = _gsc.mcp._tool_manager
    for name in sorted(REMOVED_TOOLS):
        if name in manager._tools:
            manager.remove_tool(name)
    remaining = frozenset(manager._tools)
    if remaining != EXPECTED_REMOTE_TOOLS:
        unexpected = sorted(remaining - EXPECTED_REMOTE_TOOLS)
        absent = sorted(EXPECTED_REMOTE_TOOLS - remaining)
        raise RuntimeError(
            "upstream tool set drifted — unexpected: "
            f"{unexpected}, missing: {absent}. Review each new tool for write "
            "access before adding it to EXPECTED_REMOTE_TOOLS."
        )
    log.info("exposing %d read-only GSC tools", len(remaining))

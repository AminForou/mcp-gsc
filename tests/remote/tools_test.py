import pytest
from mcp.server.lowlevel.server import Server

import gsc_server
from gsc_remote import tools


def test_low_level_server_is_reachable():
    """app.py hands this private FastMCP attribute to the streamable-HTTP
    session manager. If the SDK renames it, fail here, not in production."""
    assert isinstance(tools.low_level_server(), Server)


def test_upstream_still_registers_every_tool_we_remove():
    # Reads the pre-filter snapshot, so this holds regardless of whether
    # another test in this file has already called apply_filter().
    missing = tools.REMOVED_TOOLS - tools._UPSTREAM_TOOLS_AT_IMPORT
    assert not missing, (
        f"upstream no longer defines {sorted(missing)} — update REMOVED_TOOLS"
    )


def test_filter_leaves_exactly_the_read_only_tools():
    tools.apply_filter()
    remaining = set(gsc_server.mcp._tool_manager._tools)
    assert remaining == set(tools.EXPECTED_REMOTE_TOOLS)


def test_no_write_tool_survives():
    tools.apply_filter()
    remaining = set(gsc_server.mcp._tool_manager._tools)
    for name in ("add_site", "delete_site", "submit_sitemap",
                 "delete_sitemap", "manage_sitemaps"):
        assert name not in remaining


def test_filter_is_idempotent():
    tools.apply_filter()
    first = set(gsc_server.mcp._tool_manager._tools)
    tools.apply_filter()
    assert set(gsc_server.mcp._tool_manager._tools) == first

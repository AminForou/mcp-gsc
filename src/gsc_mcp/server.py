"""FastMCP server instance and entry point (spec 4.10: stdio only).

Important: under ``python -m gsc_mcp.server`` the file is executed as
``__main__`` — a module object *distinct* from ``gsc_mcp.server``. The tool
modules do ``from ..server import mcp``, which (under ``-m``) re-imports
``gsc_mcp.server`` as a separate object with its *own* FastMCP instance, so
decorators attached there while ``main()`` ran the instance-less ``__main__``
copy. Result: ``tools/list`` came back empty.

The fix: never rely on the global. ``main()`` imports the tools against the
serving instance, and we also run the real ``gsc_mcp.server`` module (not the
``__main__`` copy) by importing it explicitly in the ``__main__`` block.
"""
from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from . import config

mcp = FastMCP("gsc-seo-analyst-mcp")

_TOOLS_REGISTERED = False


def register_tools() -> None:
    """Import the tool modules so their @mcp.tool() decorators attach to ``mcp``.

    Idempotent: safe to call multiple times.
    """
    global _TOOLS_REGISTERED
    if _TOOLS_REGISTERED:
        return
    from .tools import properties as _properties  # noqa: F401
    from .tools import performance as _performance  # noqa: F401
    from .tools import opportunities as _opportunities  # noqa: F401
    from .tools import inspection as _inspection  # noqa: F401
    from .tools import sitemaps as _sitemaps  # noqa: F401
    _TOOLS_REGISTERED = True


# Register eagerly at import so the tools exist whether we're loaded as
# ``gsc_mcp.server`` or as ``__main__``. This is the robust fix: by the time
# any handler runs, tools are attached to whatever module object the serving
# loop is bound to.
register_tools()


def main() -> None:
    """Entry point: stdio transport only (spec 4.10)."""
    if config.TRANSPORT != "stdio":
        print(
            f"Only 'stdio' transport is supported in v1.0 (got MCP_TRANSPORT="
            f"{config.TRANSPORT!r}). Streamable HTTP / SSE have been removed.",
            file=sys.stderr,
        )
        sys.exit(1)
    config.configure_logging()
    register_tools()
    mcp.run(transport="stdio")


__all__ = ["mcp", "main", "register_tools"]


if __name__ == "__main__":
    # When launched via `python -m gsc_mcp.server`, this file is __main__.
    # Re-run the REAL module's main so tools attach to the served instance.
    import gsc_mcp.server as _real

    _real.main()

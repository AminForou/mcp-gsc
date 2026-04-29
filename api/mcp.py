"""Vercel function: MCP Streamable HTTP endpoint.

Vercel's Python runtime auto-detects an ``app`` symbol that is an ASGI
application. We expose the FastMCP-built Streamable HTTP app, wrapped in a
bearer-token guard so only the configured Claude org connector can call it.
"""

import os
import sys

# When Vercel imports this module, ensure the repo root is on sys.path so
# `gsc_server` and `lib` resolve regardless of the function's working directory.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Force the Vercel branch in gsc_server before it's imported.
os.environ.setdefault("MCP_TRANSPORT", "vercel")

from gsc_server import mcp  # noqa: E402
from lib.auth_guard import bearer_required  # noqa: E402


# FastMCP exposes ``streamable_http_app()`` (mcp >=1.8). Fall back to ``sse_app()``
# for older SDK pins; Claude org custom connectors accept either.
if hasattr(mcp, "streamable_http_app"):
    _inner = mcp.streamable_http_app()
elif hasattr(mcp, "sse_app"):
    _inner = mcp.sse_app()
else:
    raise RuntimeError(
        "Installed mcp SDK exposes neither streamable_http_app() nor sse_app(). "
        "Bump the `mcp[cli]` dependency to >=1.10."
    )

app = bearer_required(_inner)

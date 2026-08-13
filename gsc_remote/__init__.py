"""Remote OAuth 2.1 HTTP transport for the upstream mcp-gsc server.

Everything in this package is additive to the fork. Upstream's ``gsc_server``
module is never edited; per-request Google credentials reach its unchanged
tools through the monkeypatch in ``gsc_remote.credentials``.
"""

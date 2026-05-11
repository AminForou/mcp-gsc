FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

# Copy dependency files first for layer caching — deps only reinstall when these change
COPY pyproject.toml README.md ./
RUN uv sync --no-cache --no-install-project

# Copy application code
COPY gsc_server.py .

# Cloud Run injects PORT automatically (default 8080).
# When GSC_MCP_OAUTH_CLIENT_ID is set the server binds to $PORT on 0.0.0.0
# in streamable-HTTP + OAuth proxy mode.
# For plain SSE/local Docker runs, set MCP_TRANSPORT=sse and MCP_PORT instead.
ENV PORT=8080

CMD ["uv", "run", "--no-sync", "python", "gsc_server.py"]

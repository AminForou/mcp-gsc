FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app

# Copy dependency files first for layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-cache --no-install-project --frozen

# Copy the package source.
COPY src ./src
COPY config ./config

# stdio transport only (spec 4.10). Remote/SSE was removed in v1.0.
ENV MCP_TRANSPORT=stdio
CMD ["uv", "run", "--no-sync", "python", "-m", "gsc_mcp.server"]

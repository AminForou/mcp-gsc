FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

# Copy dependency files first for layer caching — deps only reinstall when these change
COPY pyproject.toml README.md ./
RUN uv sync --no-cache --no-install-project

# Copy application code
COPY gsc_server.py .

# Default to stdio transport; override with MCP_TRANSPORT=sse for remote/network use
CMD ["uv", "run", "--no-sync", "python", "gsc_server.py"]

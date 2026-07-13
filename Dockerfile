FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app

# Install dependencies before copying source to maximise Docker layer reuse.
COPY pyproject.toml README.md ./
RUN uv sync --no-cache --no-install-project

# The legacy stdio/SSE server remains available as gsc_server.py. Cloud Run uses
# the dedicated ChatGPT-compatible Streamable HTTP entrypoint.
COPY gsc_server.py chatgpt_server.py embedded_oauth.py ./

ENV PORT=8080 \
    MCP_AUTH_MODE=oauth \
    MCP_HTTP_PATH=/mcp \
    MCP_STATELESS_HTTP=true \
    MCP_JSON_RESPONSE=true \
    GSC_GOOGLE_AUTH_MODE=adc \
    GSC_SKIP_OAUTH=true

EXPOSE 8080

CMD ["uv", "run", "--no-sync", "python", "chatgpt_server.py"]

# NOTES — adding the Streamable HTTP transport

Branch: `feat/streamable-http` (off `b3f2ab8`, upstream `main`).
Goal of this step: run the existing GSC MCP server as a **remote MCP server over
Streamable HTTP**, keeping stdio and the legacy SSE transport working unchanged.
No multi-user, no billing, no hosted deploy — just the transport swap, validated
end to end against a real Google Search Console account.

Dependencies were **not** touched: `mcp[cli]>=1.3.0,<2.0.0` stays pinned,
`uv.lock` still resolves `mcp==1.27.2`, which already ships Streamable HTTP in
FastMCP (`mcp.run(transport="streamable-http")`, default path `/mcp`).

---

## 1. What changed

```
 gsc_server.py      | 72 +++++++++++++++++++++++++++++++++--
 test_gsc_server.py | 110 ++++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 179 insertions(+), 3 deletions(-)
```

Two commits:

| commit | what |
|---|---|
| `93baeb8` feat: add Streamable HTTP transport to main() | the transport branch + security helper |
| `cfd5c4f` test: cover MCP_TRANSPORT selection in main() | `TestMain` (13 tests) |

### `gsc_server.py` — `main()`

Before, `main()` had two branches: `stdio`, and `{"sse", "http"}` (both ran
`mcp.run(transport="sse")` after disabling DNS-rebinding protection).

After:

| `MCP_TRANSPORT` | behaviour |
|---|---|
| `stdio` (default) | unchanged — `mcp.run(transport="stdio")` |
| `streamable-http` **or `http`** | **new** — `mcp.run(transport="streamable-http")`, served at `http://MCP_HOST:MCP_PORT/mcp` |
| `sse` | unchanged — same code as before, still disables DNS-rebinding protection for the documented Docker/remote path |
| anything else | `ValueError` (message now lists `streamable-http`) |

- `MCP_HOST` / `MCP_PORT` are reused as-is (defaults `127.0.0.1` / `3001`). No new
  host/port variables.
- `main()` docstring and the unknown-transport error string now mention
  `streamable-http`.
- The OAuth / service-account logic was not touched. Only how the client connects.

### `gsc_server.py` — new helper `_configure_streamable_http_security(host)`

The plan explicitly asked **not** to blindly copy the SSE branch's
"disable DNS-rebinding protection". Reasoning and behaviour:

- FastMCP 1.27.2 ships DNS-rebinding protection **ON**, with a Host/Origin
  allowlist limited to loopback
  (`127.0.0.1:*`, `localhost:*`, `[::1]:*` / the matching `http://…` origins).
  A bad `Host:` header ⇒ HTTP **421**; a bad `Origin:` ⇒ **403**.
- For the default `MCP_HOST=127.0.0.1` bind that is exactly what we want, so the
  streamable-http branch **leaves the protection alone** — it stays enabled.
- When the operator deliberately binds a **non-loopback** interface via
  `MCP_HOST`, disabling the check wholesale (SSE style) is the blunt option.
  Instead the helper keeps the protection **on** and *widens* the allowlist:
  - a concrete address/host (e.g. `MCP_HOST=10.0.0.5`) → adds `10.0.0.5:*` to
    `allowed_hosts` and `http://10.0.0.5:*` / `https://10.0.0.5:*` to
    `allowed_origins`.
  - `MCP_HOST=0.0.0.0` / `::` ("all interfaces") → the real `Host:` header is
    some other name we cannot infer, so it logs a warning telling the operator
    to set `MCP_ALLOWED_HOSTS`.
- Two **optional** env vars were added for reverse-proxy / public-domain setups,
  consulted **only** by the streamable-http branch:
  - `MCP_ALLOWED_HOSTS` — comma-separated Host values (`gsc.example.com`,
    `gsc.example.com:*`, …)
  - `MCP_ALLOWED_ORIGINS` — comma-separated Origin values
  These are security-allowlist vars, not host/port config. The legacy SSE branch
  ignores them and behaves exactly as before.

### `test_gsc_server.py` — `TestMain`

13 tests, `mcp.run` mocked so nothing binds a socket. Covers: `stdio` (default and
explicit), `sse`, `streamable-http`, the `http` alias, mixed-case values, an
invalid value (raises `ValueError`, `mcp.run` never called), an invalid
`MCP_PORT`, host/port propagation, and that streamable-http keeps DNS-rebinding
protection on while SSE turns it off (plus `MCP_ALLOWED_HOSTS` handling).

---

## 2. How to run each mode

All three modes share the same auth (OAuth first, service-account fallback,
`GSC_SKIP_OAUTH=true` to force service account). Auth is orthogonal to transport.

```bash
uv sync            # uses uv.lock (mcp 1.27.2), Python from .python-version (3.11)
```

### stdio (default, local)

```bash
uv run python gsc_server.py
# MCP_TRANSPORT unset or =stdio
```

Claude Desktop / Claude Code (`.mcp.json` / `claude_desktop_config.json`):

```jsonc
{
  "mcpServers": {
    "mcp-search-console": {
      "command": "uvx",
      "args": ["mcp-search-console"],
      "env": {
        "GSC_OAUTH_CLIENT_SECRETS_FILE": "C:\\abs\\path\\client_secret_xxx.json"
      }
    }
  }
}
```

### streamable-http (remote, new)

```bash
MCP_TRANSPORT=streamable-http MCP_HOST=127.0.0.1 MCP_PORT=3001 \
  uv run python gsc_server.py
# endpoint: http://127.0.0.1:3001/mcp
```

Claude Code:

```bash
claude mcp add --transport http gsc-http http://127.0.0.1:3001/mcp
# remove with: claude mcp remove gsc-http -s local
```

`.mcp.json` form (Claude Code) — Claude Desktop does **not** support HTTP servers
directly, use `mcp-remote` as a bridge:

```jsonc
// Claude Code / any client that speaks Streamable HTTP
{
  "mcpServers": {
    "gsc-http": { "type": "http", "url": "http://127.0.0.1:3001/mcp" }
  }
}

// Claude Desktop (stdio-only) — bridge with mcp-remote
{
  "mcpServers": {
    "gsc-http": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:3001/mcp"]
    }
  }
}
```

Binding to a non-loopback interface:

```bash
# concrete host — allowlist widened automatically, protection stays on
MCP_TRANSPORT=streamable-http MCP_HOST=10.0.0.5 MCP_PORT=3001 uv run python gsc_server.py

# all interfaces behind a proxy / domain — name the public host(s) explicitly
MCP_TRANSPORT=streamable-http MCP_HOST=0.0.0.0 MCP_PORT=3001 \
  MCP_ALLOWED_HOSTS="gsc.example.com,gsc.example.com:*" \
  MCP_ALLOWED_ORIGINS="https://gsc.example.com" \
  uv run python gsc_server.py
```

### sse (legacy, unchanged)

```bash
MCP_TRANSPORT=sse MCP_PORT=3001 uv run python gsc_server.py
# or the README Docker recipe — still valid
docker run -e MCP_TRANSPORT=sse -e MCP_PORT=3001 \
  -v /path/client_secrets.json:/app/client_secrets.json -p 3001:3001 mcp-gsc
```

---

## 3. Test results

| | command | result |
|---|---|---|
| **baseline** (before any change, `b3f2ab8`) | `pytest test_gsc_server.py -v` | **43 passed** |
| **after** | `pytest test_gsc_server.py -v` | **56 passed** (43 + 13 new in `TestMain`) |

End-to-end, against Google Search Console (`https://itinereo.com/`, service
account auth), MCP Inspector CLI driving both transports:

| call | streamable-http (`/mcp`) | stdio | match |
|---|---|---|---|
| `tools/list` | 21 tools | 21 tools | identical (names + full schemas) |
| `list_properties` | 6 properties | 6 properties | identical (GSC API returns them unordered) |
| `get_search_analytics` (28 d, `query`) | 20 rows | 20 rows | **byte-identical** |

- DNS-rebinding protection verified live on streamable-http: `Host: 127.0.0.1:3001`
  → 200, `Host: evil.example.com` → **421**.
- `claude mcp add --transport http gsc-http http://127.0.0.1:3001/mcp` →
  `claude mcp list` shows **✔ Connected**; a headless `claude -p` session called
  `list_properties` through it and got the 6 properties back.

### Environment notes (this machine — Windows 11)

- **Python:** `.python-version` says 3.11; `uv` installs a managed CPython
  **3.11.15** and the server runs on it. `requires-python = ">=3.11"` is satisfied.
- **Transient Windows Application Control (WDAC) block:** on the very first run,
  executing `.venv\Scripts\python.exe` failed with `os error 4551`
  ("Application Control policy has blocked this file"). It cleared on its own
  (Defender ISG reputation) and every run since works via `uv sync` / `uv run`.
  If it recurs, rebuild the venv from a PSF-signed system Python
  (`uv sync --python "C:\...\Python312\python.exe"`).
- **pytest is not a project dependency.** `uv run --with pytest pytest …` works
  but occasionally hits the same WDAC block on the ephemeral interpreter. Reliable
  fallbacks: `uv pip install pytest && .venv\Scripts\python.exe -m pytest …`, or
  the zero-dependency `python -m unittest test_gsc_server -v`.
- **Stale env var:** a persistent *User* environment variable
  `GSC_OAUTH_CLIENT_SECRETS_FILE=C:\Users\ricar\Documents\client_secret_123456-abc.apps.googleusercontent.com.json`
  points at a non-existent placeholder file. `get_gsc_service()` fails **fast**
  when that path is set-but-missing (before the service-account fallback), so the
  server errors out until it is fixed. Set it to a real path, or delete it:
  `setx GSC_OAUTH_CLIENT_SECRETS_FILE ""` (or remove it via *Editar variáveis de
  ambiente do sistema*), then open a new shell.
- **OAuth for this test:** the Desktop-app OAuth client hit
  `Erro 403: access_denied` at Google's consent screen (app configuration
  incomplete in the new Google Auth Platform console). The E2E run used the
  **service-account** path instead
  (`GSC_SKIP_OAUTH=true` + `GSC_CREDENTIALS_PATH`), with the service account
  `ga-mcp-reader@ga-mcp-reader-507111.iam.gserviceaccount.com` added as a user on
  the GSC property. The OAuth path is still in place and unchanged in the code.

---

## 4. Next steps for a multi-user / hosted version (descriptive only)

Nothing below is implemented here.

1. **OAuth must move to a web flow.** `get_gsc_service_oauth()` /
   `reauthenticate` call `InstalledAppFlow.run_local_server(port=0)`, which opens
   a browser **on the machine running the server** and waits for a loopback
   redirect. On a hosted server there is no browser and no one to click. A hosted
   version needs a proper 3-legged OAuth **web** application: a registered
   redirect URI (`https://host/oauth/callback`), the consent screen shown in the
   *user's* browser, `state`/PKCE handling, and the callback exchanging the code
   server-side.

2. **One token per user, not one global `token.json`.** Today the token is a
   single file at `user_config_dir("mcp-gsc")/token.json` — process-wide, first
   login wins. Hosted, each authenticated caller needs their own stored
   credentials (encrypted at rest, keyed by the MCP session's authenticated
   identity), loaded per request. `get_gsc_service*()` would take the caller
   identity instead of reading module-level globals.

3. **Identify the caller.** Streamable HTTP supports an `Authorization` header and
   FastMCP has an auth/token-verifier hook (`settings.auth`, `_token_verifier`,
   seen in `streamable_http_app()`). The hosted server would verify a bearer
   token on every request and map it to the per-user Google credentials from (2).

4. **`stateless_http=True` to scale horizontally.** FastMCP defaults to
   `stateless_http=False` (in-memory session state, so every request in a session
   must hit the same process). Setting `mcp.settings.stateless_http = True` (and
   likely `json_response = True`) lets any replica serve any request — needed
   behind a load balancer. Trade-off: no server-initiated streaming/notifications
   within a session.

5. **DNS-rebinding / CORS for a real domain.** The `MCP_ALLOWED_HOSTS` /
   `MCP_ALLOWED_ORIGINS` hooks added here are the seam for this; a hosted deploy
   sets them to the public hostname and keeps the protection on.

6. **App verification & scopes.** `https://www.googleapis.com/auth/webmasters` is
   a *sensitive* scope. A multi-user app serving external users needs Google's
   OAuth verification (privacy policy, homepage, security assessment for
   restricted scopes) — out of scope for this personal step, on the path for a
   hosted product.

7. **Per-user quota & rate limiting.** One shared service account or OAuth client
   pools quota; hosted needs per-user accounting and backoff so one tenant can't
   exhaust the GSC API quota for everyone.

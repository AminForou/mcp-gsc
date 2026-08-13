# Deployment guide — remote GSC MCP server

This fork adds an OAuth 2.1-protected HTTP transport to upstream's stdio server.
Each user signs in with their **own** Google account; there is no service
account and no credential file on the host.

Replace `<your-host>` throughout with your own public hostname. Nothing in this
repo names a real host — deployment values arrive as environment variables.

---

## 1. Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select or
   create a project.
2. **APIs & Services → Library** → enable the **Google Search Console API**.
3. **APIs & Services → OAuth consent screen** → confirm
   `https://www.googleapis.com/auth/webmasters.readonly` is available. It is a
   non-sensitive scope, so an internal-type consent screen needs no
   verification.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Web application**
   - Authorized redirect URI: `https://<your-host>/oauth/callback` — exactly
     that, no trailing slash.
5. Keep the **Client ID** and **Client secret** for step 2.

Use a client dedicated to this server rather than sharing one with another MCP
server, so consent screens and token revocation stay independent.

---

## 2. Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `BASE_URL` | `http://localhost:8080` | Public HTTPS URL, no trailing slash. Must match the redirect URI's origin exactly. |
| `GOOGLE_CLIENT_ID` | — | From step 1. |
| `GOOGLE_CLIENT_SECRET` | — | From step 1. |
| `JWT_SECRET` | — | `openssl rand -base64 32`. |
| `ALLOWED_GOOGLE_DOMAINS` | empty | Comma-separated Workspace domains permitted to sign in (matched against Google's `hd` claim). |
| `ALLOWED_EMAILS` | empty | Comma-separated individual addresses outside those domains. |
| `ALLOW_OPEN_ACCESS` | `false` | Set `true` only to deliberately admit **any** Google account. |
| `ACCESS_TOKEN_TTL_SECONDS` | `86400` | Access-token lifetime. |
| `TRUST_PROXY` | `false` | `true` behind a reverse proxy. |
| `TOKEN_DB_PATH` | `/data/tokens.db` | SQLite session store. Mount a volume here. |
| `PORT` | `8080` | |
| `LOG_LEVEL` | `info` | |

**The allowlist fails closed.** With neither `ALLOWED_GOOGLE_DOMAINS` nor
`ALLOWED_EMAILS` set, every sign-in is refused and an error is logged. That is
deliberate: an unset allowlist is far more often a forgotten variable than a
decision to admit the whole world. To run open, say so with
`ALLOW_OPEN_ACCESS=true`.

**Treat the `/data` volume as secret material.** Google access and refresh
tokens are stored unencrypted — encrypting them would put the key in the same
environment as the database, so the protection would be nominal. Do not copy the
volume off the host, and keep it out of backups that travel.

---

## 3. Image

The image is published on a `v*` tag by `.github/workflows/publish-image.yml`:

```
ghcr.io/klartika/gsc-mcp-server:vX.Y.Z
```

Built from `Dockerfile.remote` for **`linux/arm64`**. Upstream's stdio
`Dockerfile` is untouched and builds the local server instead.

The deployment lives in a separate infrastructure repository, which pins a
specific tag rather than building. To update, bump the pinned tag there.

To run it directly:

```bash
docker run -d --name mcp-google-search-console -p 8080:8080 \
  -e BASE_URL=https://<your-host> \
  -e GOOGLE_CLIENT_ID=... -e GOOGLE_CLIENT_SECRET=... \
  -e JWT_SECRET=... \
  -e ALLOWED_GOOGLE_DOMAINS=example.com \
  -e TRUST_PROXY=true \
  -v mcp_gsc_data:/data \
  ghcr.io/klartika/gsc-mcp-server:vX.Y.Z
```

---

## 4. Reverse proxy

Forward `<your-host>` to the container on port `8080`, with **websockets
enabled** and SSL forced.

MCP responses stream as `text/event-stream`, so buffering must be off. In Nginx
Proxy Manager, under **Advanced → Custom Nginx Configuration**:

```nginx
proxy_buffering off;
proxy_read_timeout 3600s;
```

Two things that break the handshake if missed:

- **`X-Forwarded-Proto` must reach the container.** The app runs uvicorn with
  `proxy_headers=True`; without the header, the `/mcp` → `/mcp/` redirect
  downgrades to `http://` and Claude's handshake fails.
- **Exactly one proxy hop.** Rate limiting reads the rightmost
  `X-Forwarded-For` entry, because Nginx appends the peer address and the
  leftmost value is client-supplied. A second proxy in front means skipping that
  many entries.

A Cloudflare-proxied record (orange cloud) works — this is deployed that way.
If streaming ever misbehaves, look at Cloudflare's proxy-level request timeout
on non-Enterprise plans, which applies to connections that go idle; MCP's SSE
traffic normally keeps that from triggering. DNS-only is the fallback, not the
starting point.

---

## 5. Verify

```bash
curl -sf https://<your-host>/health
# {"status":"healthy","service":"gsc-mcp"}

curl -sf https://<your-host>/.well-known/oauth-protected-resource | jq .
# scopes_supported includes .../auth/webmasters.readonly

curl -sL -o /dev/null -w '%{http_code}\n' -X POST https://<your-host>/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# 401
```

`POST /mcp` returns `307` to `/mcp/` before the `401` — that is ordinary
`Mount()` behaviour, which is why the check above follows redirects. A `200` at
any point means authentication is not being enforced.

---

## 6. Connect from Claude

**Settings → Connectors → Add custom connector** → `https://<your-host>/mcp`.

Sign in with a Google account matching the allowlist. The session persists in
`/data/tokens.db`, so reconnecting within `ACCESS_TOKEN_TTL_SECONDS` needs no
re-authentication.

Confirm after connecting:

1. The tool list shows **13** read-only tools and none of `add_site`,
   `delete_site`, `submit_sitemap`, `delete_sitemap`, `manage_sitemaps`.
2. `list_properties` returns the signed-in user's own GSC properties.
3. A non-allowlisted account is refused with a 403.

Sign-in must begin in the MCP client. Starting at `/authorize` in one browser
and finishing in another is refused by design — the federation leg is bound to
the browser that began it.

---

## 7. Syncing with upstream

```bash
git fetch upstream
git rebase upstream/main
uv run pytest -q
git push origin remote-oauth-mcp
```

Two tests guard the seams into upstream and will fail loudly if a rebase moves
them: `tests/remote/credentials_test.py` (the `get_gsc_service` chokepoint) and
`tests/remote/tools_test.py` (the private `mcp._mcp_server` attribute, plus the
exact set of exposed tools). If upstream adds a tool, the tool-set assertion
fails on purpose — classify it as read or write before exposing it.

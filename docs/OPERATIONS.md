# Operations

Running the deployed remote server: what to do routinely, and what to do when
something breaks. For first-time setup see [`DEPLOY.md`](../DEPLOY.md); for
changing the code see [`AGENTS.md`](../AGENTS.md).

Replace `<your-host>` with your own hostname. This repo is public and names no
deployment values — the infrastructure repository holds those.

---

## How the pieces fit

Three things, in three places, deliberately:

```
this repo ──(v* tag)──▶ GHCR image ──(pinned by tag)──▶ infra repo
                                                            │
                                                     (git/redeploy API)
                                                            ▼
   secrets manager ──(synced by CI, never typed in)──▶ Portainer stack
                                                            │
                                                            ▼
                                                    reverse proxy ──▶ users
```

Nothing builds on the deployment host. A release is: tag here → image publishes
→ bump the pinned tag in the infra repo → its workflow redeploys. Secrets never
appear in the container platform's UI; a CI job pushes them in at redeploy time.

The consequence worth internalising: **this repo cannot deploy anything.**
Merging to `main` changes nothing in production. Only a tag produces an image,
and only the infra repo decides which image runs.

---

## Routine operations

### Release a new version

```bash
git checkout main && git pull
uv run pytest -q                 # must be green before tagging
git tag vX.Y.Z && git push origin vX.Y.Z
```

Watch the publish workflow, then bump the pinned tag in the infra repo's compose
file and push. That push triggers the redeploy.

Two separate steps on purpose: the image existing and the image running are
different decisions, and the gap is where you notice a bad build.

### Roll back

Bump the pinned tag in the infra repo back to the previous version and push.
Images are immutable and every release is still in the registry, so rollback is
a one-line revert, not a rebuild.

The token database is **not** rolled back. Schema changes are additive
(`CREATE TABLE IF NOT EXISTS`, new nullable columns), so an older image tolerates
a newer database — but a rollback across a migration that dropped or renamed a
column would not be safe. None have happened; check before assuming.

### Rotate a secret

Change it in the secrets manager, then trigger the deploy workflow manually
(`workflow_dispatch`). Nothing in the infra repo changes, so the path-filtered
push trigger will not fire on its own — this is exactly why manual dispatch
exists.

Rotating `JWT_SECRET` or the Google client secret does not invalidate existing
sessions: tokens live in SQLite, not in signed cookies. To actually cut everyone
off, delete the volume.

### Change who can sign in

Edit `ALLOWED_GOOGLE_DOMAINS` (or `ALLOWED_EMAILS`) in the secrets manager and
dispatch the workflow.

Removing someone takes effect at their next **token refresh**, not immediately —
the allowlist is re-checked on refresh, but an already-issued access token stays
valid until it expires (`ACCESS_TOKEN_TTL_SECONDS`, 24 h by default). To revoke
now, delete their row from the token database, or lower the TTL if that window
is unacceptable in general.

### Rebase on upstream

```bash
git fetch upstream && git rebase upstream/main
uv run pytest -q
```

Two tests exist specifically to fail loudly here:

- `tests/remote/credentials_test.py` — the `get_gsc_service` chokepoint every
  tool calls, and the function this fork monkeypatches.
- `tests/remote/tools_test.py` — the private `mcp._mcp_server` attribute, plus
  the **exact** set of exposed tools.

If upstream adds a tool, the tool-set assertion fails on purpose. Classify the
new tool as read or write before adding it to `EXPECTED_REMOTE_TOOLS`; a write
tool would 403 at runtime under `webmasters.readonly` anyway, but it should
never reach the model in the first place.

`README.md` will also conflict, because this fork adds an orientation banner at
the top. Keep the banner, take upstream's changes below it.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Stack fails to pull the image | Registry credential missing, wrong org, or a non-classic token | Registry credential must use a **classic** PAT with `read:packages`, and the organisation namespace, not a personal one |
| `redirect_uri_mismatch` at sign-in | The URI in the Google OAuth client is not character-identical to `https://<your-host>/oauth/callback` | Fix it in Google Cloud. No trailing slash, `https`, exact host |
| 403 "your Google account is not permitted" | The `hd` claim does not match `ALLOWED_GOOGLE_DOMAINS` | Check the domain value; personal Gmail accounts have no `hd` at all |
| Every sign-in refused, log says "no allowlist configured" | Neither allowlist variable reached the container | The secret sync did not run, or the value is empty. This is fail-closed behaviour working as intended |
| "This sign-in did not start in this browser" | The federation binding cookie is absent or stale | Start sign-in from the MCP client, in one browser, and finish it there. Not a bug |
| Tool calls hang, never return | The reverse proxy is buffering the `text/event-stream` response | `proxy_buffering off;` and a long `proxy_read_timeout` |
| Handshake fails, redirect goes to `http://` | `X-Forwarded-Proto` is not reaching the container | Ensure the proxy forwards it; the app trusts it via uvicorn's `proxy_headers` |
| Rate limiting appears not to work | More than one proxy hop in front | The limiter reads the **rightmost** `X-Forwarded-For` entry, assuming exactly one trusted hop |
| Container healthy, tools return auth errors | The user's Google grant was revoked | They sign in again; nothing to fix server-side |

### Reading the logs

Every OAuth failure logs the exception **type**, never its content, so nothing
sensitive lands in the log. That also means the log tells you *where* it failed,
not *what* the value was — reproduce with the failing account rather than
grepping for the value.

### Checking the stack is still git-linked

After **any** manual API call against the container platform:

```bash
curl -sf "$PLATFORM_URL/api/stacks/$ID" -H "X-API-Key: $TOKEN" \
  | jq '{GitConfig, IsDetachedFromGit}'
```

`GitConfig: null` or `IsDetachedFromGit: true` means the stack was silently
detached from git and future redeploys will not pick up changes. The infra
repo's own guide documents the API call that causes this and the incident it
caused; use the git-aware redeploy endpoint, never the plain stack update.

---

## Health and verification

```bash
curl -sf https://<your-host>/health
# {"status":"healthy","service":"gsc-mcp"}

curl -sf https://<your-host>/.well-known/oauth-protected-resource | jq .
# scopes_supported: [".../auth/webmasters.readonly"]

curl -sL -o /dev/null -w '%{http_code}\n' -X POST https://<your-host>/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# 401
```

`POST /mcp` returns `307` to `/mcp/` before the `401` — ordinary `Mount()`
behaviour, hence `-L`. **A `200` anywhere in that sequence means authentication
is not being enforced**; treat it as an incident.

After connecting a client, confirm the tool list has **13** tools and none of
`add_site`, `delete_site`, `submit_sitemap`, `delete_sitemap`,
`manage_sitemaps`. A write tool appearing means the startup filter did not run.

---

## The token database

`/data/tokens.db` (SQLite, WAL) holds registered OAuth clients, issued tokens,
and each user's Google access and refresh tokens.

**Treat the volume as secret material.** Those Google tokens are stored
unencrypted, and deliberately so: the key would live in the same environment as
the database, making the protection nominal. The real control is that the volume
does not travel — keep it out of backups that leave the host.

Deleting the volume signs everyone out and loses nothing else. It is a
legitimate recovery step.

Expired federation states and authorization codes are swept every 10 minutes and
at startup. Issued tokens are not swept — they are removed on revocation, on
refresh rotation, or when an identity fails the allowlist re-check.

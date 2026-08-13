# Remote GSC MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a remotely accessible, OAuth-protected Google Search Console MCP server at `https://<gsc-host>/mcp`, where each user signs in with their own Google account.

**Architecture:** Fork `AminForou/mcp-gsc` (Python, FastMCP) to `Klartika/gsc-mcp-server` and add an OAuth 2.1 HTTP transport in a new `gsc_remote/` package, mirroring the equivalent layer in the sibling repo `Klartika/google-analytics-mcp`. Upstream's `gsc_server.py` is never edited; per-user credentials reach its unchanged tools through a runtime monkeypatch of `get_gsc_service()` bound to a `ContextVar`. Deployment follows the `infra-ops` GitOps convention: a GHCR image published on tag, pinned by a compose file in `infra-ops`, with secrets synced from Infisical.

**Tech Stack:** Python 3.11+, `mcp` SDK (FastMCP + `mcp.server.auth`), Starlette, uvicorn, httpx, SQLite, `google-api-python-client`, `google-auth`. Docker (linux/arm64) → GHCR → Portainer → Nginx Proxy Manager.

**Spec:** `docs/superpowers/specs/2026-08-13-gsc-remote-mcp-design.md`

## Global Constraints

Every task's requirements implicitly include these.

- **Never edit `gsc_server.py`.** All fork behaviour lives in new files under `gsc_remote/`. The only seams into upstream are runtime monkeypatches. `pyproject.toml` is the sole upstream file that changes, additively.
- **Public repository — no identifiable information.** No real domains, emails, hostnames, secrets or tokens in code, tests or docs. Use `example.com`, `example.org`, `<your-host>`. `<gsc-host>` in this plan is a placeholder; the operator substitutes the real hostname only in `infra-ops` and the Google Cloud OAuth client.
- **Never commit to `main`.** Work on branch `remote-oauth-mcp`, open a PR, merge the PR — even for docs.
- **TDD.** Failing test first, then implementation. Keep the suite green.
- Python floor: `>=3.11` (upstream's, unchanged). MCP SDK floor: `mcp[cli]>=1.28.1,<2.0.0` (raised from upstream's `>=1.3.0`; `mcp.server.auth` needs it). Verified against 1.29.0. The 1.28.1 floor is a security floor (GHSA on WebSocket Host/Origin validation), not a feature one.
- Container platform: **`linux/arm64`** — the Portainer host is ARM.
- GSC scope: `https://www.googleapis.com/auth/webmasters.readonly` only, plus `openid` and `email`.
- **Ported files carry an attribution header.** Files adapted from `Klartika/google-analytics-mcp` (Apache-2.0, Klartika's own additions) start with a comment: `# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/<file>).`
- The GA4 reference checkout lives at `/home/nosync/Coding/Klartika/google-analytics-mcp` on this machine. Its remote layer is `analytics_mcp/remote/`, its tests `tests/remote/`.

---

### Task 1: Fork, scaffold, and keep upstream green

**Files:**
- Create: `gsc_remote/__init__.py`, `AGENTS.md`, `tests/remote/__init__.py`, `tests/__init__.py`
- Modify: `pyproject.toml`
- Move in: `docs/superpowers/specs/2026-08-13-gsc-remote-mcp-design.md`, `docs/superpowers/plans/2026-08-13-gsc-remote-mcp.md`

**Interfaces:**
- Consumes: nothing.
- Produces: an installed editable package exposing the `gsc_remote` namespace and a `gsc-mcp-http` console script entry point (implemented in Task 10); a green baseline test run.

- [ ] **Step 1: Fork and clone**

The working directory `/home/nosync/Coding/Klartika/gsc-mcp-server` currently holds only `docs/`. Preserve it, fork, clone, restore.

```bash
cd /home/nosync/Coding/Klartika
mv gsc-mcp-server/docs /tmp/gsc-docs
rmdir gsc-mcp-server
gh repo fork AminForou/mcp-gsc --org Klartika --fork-name gsc-mcp-server --clone=false
git clone https://github.com/Klartika/gsc-mcp-server.git
cd gsc-mcp-server
git remote add upstream https://github.com/AminForou/mcp-gsc.git
git fetch upstream
git checkout -b remote-oauth-mcp
mv /tmp/gsc-docs docs
```

- [ ] **Step 2: Verify the upstream baseline is green before touching anything**

```bash
cd /home/nosync/Coding/Klartika/gsc-mcp-server
uv venv
uv pip install -e ".[dev]" pytest pytest-asyncio respx
uv run pytest test_gsc_server.py -q
```

Expected: all upstream tests pass. If they do not, stop and report — do not build on a red baseline.

- [ ] **Step 3: Create the package skeleton**

```bash
mkdir -p gsc_remote tests/remote
touch tests/__init__.py tests/remote/__init__.py
```

`gsc_remote/__init__.py`:

```python
"""Remote OAuth 2.1 HTTP transport for the upstream mcp-gsc server.

Everything in this package is additive to the fork. Upstream's ``gsc_server``
module is never edited; per-request Google credentials reach its unchanged
tools through the monkeypatch in ``gsc_remote.credentials``.
"""
```

- [ ] **Step 4: Apply the additive `pyproject.toml` edits**

Four changes, and nothing else:

1. In `[project].dependencies`, change `"mcp[cli]>=1.3.0,<2.0.0"` to `"mcp[cli]>=1.28.1,<2.0.0"` and append:

```toml
    "starlette>=0.40",
    "uvicorn>=0.30",
    "httpx>=0.28.1",
```

2. In `[project.scripts]`, append:

```toml
gsc-mcp-http = "gsc_remote.app:main"
```

3. Replace the `[tool.setuptools]` block with:

```toml
[tool.setuptools]
py-modules = ["gsc_server"]
packages = ["gsc_remote"]
```

4. Append at the end of the file:

```toml
[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "respx>=0.21"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 5: Verify the package installs and upstream still passes**

```bash
uv pip install -e ".[dev]"
uv run python -c "import gsc_remote, gsc_server; print('ok')"
uv run pytest test_gsc_server.py -q
```

Expected: `ok`, then all upstream tests still pass.

- [ ] **Step 6: Write `AGENTS.md`**

```markdown
# AGENTS.md — maintenance guide

Guidance for humans and AI coding agents working on **this fork** of
`AminForou/mcp-gsc`. Read this before making changes.

## What this fork adds

Upstream is a **local (stdio)** MCP server for Google Search Console. This fork
adds an optional **remote, OAuth 2.1-protected HTTP transport**: a self-hostable
server where each user signs in with their **own Google account**
(`webmasters.readonly`) — no service accounts, no credential files on disk. It
is built on the MCP Python SDK's OAuth framework (`mcp.server.auth`), federates
to Google, persists sessions in SQLite, and ships as a container image.

All of this lives in **new files** under `gsc_remote/`. The upstream server and
its tools are unchanged.

## Hard rules (do not break these)

1. **Public repository — no identifiable information.** Never commit real
   domains, emails, hostnames, company names, secrets or tokens. Use only
   RFC-reserved placeholders (`example.com`, `<your-host>`). Deployment values
   are supplied **only** via environment variables set by the deployment.
2. **Stay rebaseable on upstream.** Do **not** edit `gsc_server.py`. Put all
   fork behaviour in `gsc_remote/`. The seams into upstream are runtime
   monkeypatches, not source edits. Periodically:
   `git fetch upstream && git rebase upstream/main`.
3. **Never commit to `main`.** Always work on a branch, open a PR, merge the PR
   — even for docs.
4. **TDD.** Write a failing test first, then the implementation. Keep the suite
   green.

## Repository layout

Upstream (treat as read-only): `gsc_server.py`, `test_gsc_server.py`,
`README.md`, `skills/`, `CHANGELOG.md`, `Dockerfile`.

This fork's additions (`gsc_remote/`):

- `config.py` — env → `Config`. Allowlist/secret values come only from env.
- `store.py` — `TokenStore`: SQLite persistence (clients, tokens↔Google tokens,
  auth codes, federation states), WAL mode, survives restarts.
- `credentials.py` — request-scoped Google credentials `ContextVar` + the
  monkeypatch of `gsc_server.get_gsc_service` (the credential seam).
- `google.py` — Google federation: auth URL (`access_type=offline`,
  `prompt=consent`), code exchange, userinfo, `Credentials` builder.
- `allowlist.py` — email / hosted-domain (`hd`) allowlist; open mode + warning
  when unset.
- `ratelimit.py` — per-IP token bucket + body-size limit middleware.
- `provider.py` — `GoogleMCPProvider(OAuthAuthorizationServerProvider)`.
- `tools.py` — startup filter removing write and local-only tools.
- `app.py` — Starlette wiring and `main()`. Console script `gsc-mcp-http`.

Tests: `tests/remote/*_test.py`. Image: `Dockerfile.remote`. Deployment lives in
the `Klartika/infra-ops` repo under `gsc-mcp/`.

## Two things that will break on an upstream rebase

- `gsc_server.get_gsc_service` — the single chokepoint every tool calls, and the
  function `gsc_remote/credentials.py` patches. `tests/remote/credentials_test.py`
  fails loudly if it moves.
- `gsc_server.mcp._mcp_server` — the private low-level `Server` inside FastMCP
  that `app.py` hands to `StreamableHTTPSessionManager`.
  `tests/remote/tools_test.py` asserts it exists.

If upstream adds a tool, `tests/remote/tools_test.py` fails on the exact-name-set
assertion. That is deliberate: decide explicitly whether the new tool is
read-only before exposing it.
```

- [ ] **Step 7: Commit**

```bash
git add gsc_remote/__init__.py tests/__init__.py tests/remote/__init__.py \
        pyproject.toml AGENTS.md docs/
git commit -m "chore: scaffold remote OAuth transport package

Adds the gsc_remote package skeleton, additive pyproject changes (mcp>=1.24,
starlette/uvicorn/httpx, dev extras, console script), fork maintenance guide,
and the design spec and implementation plan."
```

---

### Task 2: Configuration

**Files:**
- Create: `gsc_remote/config.py`
- Test: `tests/remote/config_test.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GSC_SCOPE: str`; frozen dataclass `Config(port: int, base_url: str, google_client_id: str, google_client_secret: str, jwt_secret: str, allowed_emails: set[str], allowed_google_domains: set[str], access_token_ttl: timedelta, trust_proxy: bool, log_level: str, token_db_path: str)`; `load() -> Config`.

Note: the GA4 original also carries an `allowed_hosts` field that nothing reads. It is deliberately dropped here.

- [ ] **Step 1: Write the failing test**

`tests/remote/config_test.py`:

```python
import importlib

from gsc_remote import config as config_mod


def _load(monkeypatch, **env):
    for key in [
        "PORT",
        "BASE_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "JWT_SECRET",
        "ALLOWED_EMAILS",
        "ALLOWED_GOOGLE_DOMAINS",
        "ACCESS_TOKEN_TTL_SECONDS",
        "TRUST_PROXY",
        "LOG_LEVEL",
        "TOKEN_DB_PATH",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    importlib.reload(config_mod)
    return config_mod.load()


def test_scope_is_readonly():
    assert config_mod.GSC_SCOPE == (
        "https://www.googleapis.com/auth/webmasters.readonly"
    )


def test_domains_unset_means_open(monkeypatch):
    # No domain or email is baked into the code; the allowlist is configured
    # purely via env vars. Unset => open mode.
    cfg = _load(monkeypatch)
    assert cfg.allowed_google_domains == set()
    assert cfg.allowed_emails == set()
    assert cfg.port == 8080
    assert cfg.token_db_path == "/data/tokens.db"
    assert cfg.trust_proxy is False
    assert cfg.access_token_ttl.total_seconds() == 86400


def test_env_configures_the_allowlist(monkeypatch):
    cfg = _load(
        monkeypatch,
        ALLOWED_GOOGLE_DOMAINS="example.com, Foo.Org",
        ALLOWED_EMAILS="A@B.com",
        TRUST_PROXY="true",
        ACCESS_TOKEN_TTL_SECONDS="3600",
        BASE_URL="https://gsc.example.com/",
    )
    assert cfg.allowed_google_domains == {"example.com", "foo.org"}
    assert cfg.allowed_emails == {"a@b.com"}
    assert cfg.trust_proxy is True
    assert cfg.access_token_ttl.total_seconds() == 3600
    assert cfg.base_url == "https://gsc.example.com"  # trailing slash stripped


def test_empty_domains_env_means_open(monkeypatch):
    cfg = _load(monkeypatch, ALLOWED_GOOGLE_DOMAINS="")
    assert cfg.allowed_google_domains == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/config_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.config'`

- [ ] **Step 3: Write the implementation**

`gsc_remote/config.py`:

```python
# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/config.py).
"""Environment configuration for the remote MCP server."""

import os
from dataclasses import dataclass
from datetime import timedelta

GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


@dataclass(frozen=True)
class Config:
    port: int
    base_url: str
    google_client_id: str
    google_client_secret: str
    jwt_secret: str
    allowed_emails: set[str]
    allowed_google_domains: set[str]
    access_token_ttl: timedelta
    trust_proxy: bool
    log_level: str
    token_db_path: str


def _csv_set(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def load() -> Config:
    # The access allowlist is configured exclusively via environment variables.
    # No domain or email is ever hard coded — this repo is public and must
    # contain no deployment-specific values.
    return Config(
        port=int(os.getenv("PORT", "8080")),
        base_url=os.getenv("BASE_URL", "http://localhost:8080").rstrip("/"),
        google_client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        jwt_secret=os.getenv("JWT_SECRET", ""),
        allowed_emails=_csv_set(os.getenv("ALLOWED_EMAILS", "")),
        allowed_google_domains=_csv_set(
            os.getenv("ALLOWED_GOOGLE_DOMAINS", "")
        ),
        access_token_ttl=timedelta(
            seconds=int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "86400"))
        ),
        trust_proxy=os.getenv("TRUST_PROXY", "false").lower()
        in ("1", "true", "yes"),
        log_level=os.getenv("LOG_LEVEL", "info"),
        token_db_path=os.getenv("TOKEN_DB_PATH", "/data/tokens.db"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/config_test.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/config.py tests/remote/config_test.py
git commit -m "feat(remote): env-driven configuration"
```

---

### Task 3: Access allowlist

**Files:**
- Create: `gsc_remote/allowlist.py`
- Test: `tests/remote/allowlist_test.py`

**Interfaces:**
- Consumes: `gsc_remote.config.Config`.
- Produces: `is_open(cfg: Config) -> bool`; `identity_allowed(cfg: Config, email, hd, verified) -> bool`.

- [ ] **Step 1: Write the failing test**

`tests/remote/allowlist_test.py`:

```python
from datetime import timedelta

from gsc_remote.allowlist import identity_allowed, is_open
from gsc_remote.config import Config


def _cfg(emails=None, domains=None):
    return Config(
        port=8080,
        base_url="https://x",
        google_client_id="",
        google_client_secret="",
        jwt_secret="",
        allowed_emails=emails or set(),
        allowed_google_domains=domains or set(),
        access_token_ttl=timedelta(hours=24),
        trust_proxy=False,
        log_level="info",
        token_db_path=":memory:",
    )


def test_domain_match_allows():
    cfg = _cfg(domains={"example.com", "example.org"})
    assert identity_allowed(cfg, "user@example.com", None, True) is True
    assert identity_allowed(cfg, "x@example.org", "example.org", True) is True


def test_non_allowlisted_domain_rejected():
    cfg = _cfg(domains={"example.com"})
    assert identity_allowed(cfg, "x@example.net", None, True) is False


def test_unverified_email_rejected():
    cfg = _cfg(domains={"example.com"})
    assert identity_allowed(cfg, "user@example.com", None, False) is False


def test_missing_email_rejected():
    cfg = _cfg(domains={"example.com"})
    assert identity_allowed(cfg, None, None, True) is False


def test_explicit_email_allows_outside_domain():
    cfg = _cfg(emails={"contractor@example.net"}, domains={"example.com"})
    assert identity_allowed(cfg, "contractor@example.net", None, True) is True


def test_open_mode_allows_anyone():
    cfg = _cfg()
    assert is_open(cfg) is True
    assert identity_allowed(cfg, "anyone@example.net", None, True) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/allowlist_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.allowlist'`

- [ ] **Step 3: Write the implementation**

`gsc_remote/allowlist.py`:

```python
# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/allowlist.py).
"""Access allowlist enforced after Google verifies a user's identity."""

import logging

from gsc_remote.config import Config

log = logging.getLogger("gsc_remote")


def is_open(cfg: Config) -> bool:
    return not cfg.allowed_emails and not cfg.allowed_google_domains


def identity_allowed(cfg: Config, email, hd, verified) -> bool:
    if is_open(cfg):
        log.warning(
            "access allowlist is OPEN — set ALLOWED_GOOGLE_DOMAINS or "
            "ALLOWED_EMAILS to restrict who can use this server"
        )
        return True
    if not email or not verified:
        return False
    email = email.lower()
    if email in cfg.allowed_emails:
        return True
    domain = (hd or email.split("@")[-1]).lower()
    return domain in cfg.allowed_google_domains
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/allowlist_test.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/allowlist.py tests/remote/allowlist_test.py
git commit -m "feat(remote): email and hosted-domain allowlist"
```

---

### Task 4: Rate limiting and body-size cap

**Files:**
- Create: `gsc_remote/ratelimit.py`
- Test: `tests/remote/ratelimit_test.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TokenBucket(rate: float, burst: float, now=time.monotonic)` with `.allow(key: str) -> bool`; `RateLimitMiddleware(app, *, limited_prefixes: tuple[str, ...], rate: float, burst: float, max_body_bytes: int, trust_proxy: bool)`.

- [ ] **Step 1: Write the failing test**

`tests/remote/ratelimit_test.py`:

```python
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from gsc_remote.ratelimit import RateLimitMiddleware, TokenBucket


def test_bucket_allows_burst_then_blocks():
    clock = [0.0]
    bucket = TokenBucket(rate=1, burst=3, now=lambda: clock[0])
    assert [bucket.allow("ip") for _ in range(3)] == [True, True, True]
    assert bucket.allow("ip") is False


def test_bucket_refills_over_time():
    clock = [0.0]
    bucket = TokenBucket(rate=1, burst=1, now=lambda: clock[0])
    assert bucket.allow("ip") is True
    assert bucket.allow("ip") is False
    clock[0] = 2.0
    assert bucket.allow("ip") is True


def test_buckets_are_per_key():
    clock = [0.0]
    bucket = TokenBucket(rate=1, burst=1, now=lambda: clock[0])
    assert bucket.allow("a") is True
    assert bucket.allow("b") is True


def _app(**kwargs):
    async def ok(_request):
        return PlainTextResponse("ok")

    defaults = dict(
        limited_prefixes=("/token",),
        rate=1,
        burst=2,
        max_body_bytes=100,
        trust_proxy=False,
    )
    defaults.update(kwargs)
    return Starlette(
        routes=[
            Route("/token", ok, methods=["POST"]),
            Route("/free", ok, methods=["POST"]),
        ],
        middleware=[Middleware(RateLimitMiddleware, **defaults)],
    )


def test_limited_prefix_returns_429_after_burst():
    client = TestClient(_app())
    assert client.post("/token", content=b"x").status_code == 200
    assert client.post("/token", content=b"x").status_code == 200
    assert client.post("/token", content=b"x").status_code == 429


def test_unlimited_path_is_untouched():
    client = TestClient(_app())
    for _ in range(5):
        assert client.post("/free", content=b"x").status_code == 200


def test_oversized_body_returns_413():
    client = TestClient(_app())
    resp = client.post("/token", content=b"x" * 200)
    assert resp.status_code == 413
    assert resp.json()["error"] == "request_too_large"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/ratelimit_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.ratelimit'`

- [ ] **Step 3: Write the implementation**

Copy the reference file, then fix the module docstring's attribution:

```bash
cp /home/nosync/Coding/Klartika/google-analytics-mcp/analytics_mcp/remote/ratelimit.py \
   gsc_remote/ratelimit.py
```

Then prepend this line as the file's first line:

```python
# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/ratelimit.py).
```

No other change is needed — the file imports nothing from its original package.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/ratelimit_test.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/ratelimit.py tests/remote/ratelimit_test.py
git commit -m "feat(remote): per-IP rate limiting and body-size cap"
```

---

### Task 5: SQLite token store

**Files:**
- Create: `gsc_remote/store.py`
- Test: `tests/remote/store_test.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `TokenStore(path: str)` with `save_client`, `get_client`, `save_state`, `pop_state`, `save_auth_code`, `get_auth_code`, `delete_auth_code`, `save_token`, `get_by_access`, `get_by_refresh`, `rotate_token`, `delete_by_token`, `purge_expired`. Keyword-only signatures — see the reference file.

- [ ] **Step 1: Write the failing test**

`tests/remote/store_test.py`:

```python
import time

import pytest

from gsc_remote.store import TokenStore


@pytest.fixture
def store(tmp_path):
    return TokenStore(str(tmp_path / "t.db"))


def _save_state(store, state, expires_in=600):
    store.save_state(
        state=state,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        expires_at=time.time() + expires_in,
    )


def _save_code(store, code, expires_in=600):
    store.save_auth_code(
        code=code,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        subject="sub-1",
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        expires_at=time.time() + expires_in,
    )


def _save_token(store, access="at", refresh="rt"):
    store.save_token(
        access_token=access,
        refresh_token=refresh,
        client_id="c1",
        scopes=["openid"],
        expires_at=time.time() + 3600,
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        subject="sub-1",
    )


def test_state_roundtrip_and_single_use(store):
    _save_state(store, "s1")
    popped = store.pop_state("s1")
    assert popped["client_id"] == "c1"
    assert popped["scopes"] == ["openid"]
    assert popped["redirect_uri_provided_explicitly"] is True
    assert store.pop_state("s1") is None  # single use


def test_expired_state_is_not_returned(store):
    _save_state(store, "s2", expires_in=-1)
    assert store.pop_state("s2") is None


def test_auth_code_roundtrip_and_delete(store):
    _save_code(store, "code-1")
    row = store.get_auth_code("code-1")
    assert row["subject"] == "sub-1"
    assert row["google_refresh"] == "gr"
    assert row["scopes"] == ["openid"]
    store.delete_auth_code("code-1")
    assert store.get_auth_code("code-1") is None


def test_token_lookup_by_access_and_refresh(store):
    _save_token(store)
    assert store.get_by_access("at")["subject"] == "sub-1"
    assert store.get_by_refresh("rt")["client_id"] == "c1"
    assert store.get_by_access("nope") is None


def test_rotate_token_replaces_the_old_pair(store):
    _save_token(store)
    store.rotate_token(
        old_refresh="rt",
        access_token="at2",
        refresh_token="rt2",
        client_id="c1",
        scopes=["openid"],
        expires_at=time.time() + 3600,
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        subject="sub-1",
    )
    assert store.get_by_refresh("rt") is None
    assert store.get_by_access("at") is None
    assert store.get_by_access("at2")["refresh_token"] == "rt2"


def test_delete_by_token_matches_either_token(store):
    _save_token(store)
    store.delete_by_token("rt")
    assert store.get_by_access("at") is None


def test_purge_expired_clears_states_and_codes(store):
    _save_state(store, "old", expires_in=-1)
    _save_code(store, "old-code", expires_in=-1)
    store.purge_expired()
    assert store.get_auth_code("old-code") is None


def test_data_survives_reopening_the_database(tmp_path):
    path = str(tmp_path / "persist.db")
    first = TokenStore(path)
    _save_token(first)
    second = TokenStore(path)
    assert second.get_by_access("at")["subject"] == "sub-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/store_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.store'`

- [ ] **Step 3: Write the implementation**

```bash
cp /home/nosync/Coding/Klartika/google-analytics-mcp/analytics_mcp/remote/store.py \
   gsc_remote/store.py
```

Prepend as the first line:

```python
# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/store.py).
```

The file imports only `json`, `os`, `sqlite3`, `threading`, `time` and
`mcp.shared.auth.OAuthClientInformationFull` — nothing package-specific — so no
further edits are needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/store_test.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/store.py tests/remote/store_test.py
git commit -m "feat(remote): SQLite persistence for clients, codes, and tokens"
```

---

### Task 6: Google OAuth federation

**Files:**
- Create: `gsc_remote/google.py`
- Test: `tests/remote/google_test.py`

**Interfaces:**
- Consumes: `gsc_remote.config.Config`, `gsc_remote.config.GSC_SCOPE`.
- Produces: `redirect_uri(cfg) -> str`; `authorization_url(cfg, state) -> str`; `async exchange_code(cfg, code) -> dict`; `async fetch_userinfo(google_access_token) -> dict`; `build_credentials(cfg, google_access, google_refresh, expiry_epoch) -> google.oauth2.credentials.Credentials`. Module constants `GOOGLE_AUTH_ENDPOINT`, `GOOGLE_TOKEN_ENDPOINT`, `GOOGLE_USERINFO_ENDPOINT`.

- [ ] **Step 1: Write the failing test**

`tests/remote/google_test.py`:

```python
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from gsc_remote import google
from gsc_remote.config import Config


def _cfg():
    return Config(
        port=8080,
        base_url="https://gsc.example.com",
        google_client_id="cid",
        google_client_secret="csec",
        jwt_secret="jwt",
        allowed_emails=set(),
        allowed_google_domains={"example.com"},
        access_token_ttl=timedelta(hours=24),
        trust_proxy=False,
        log_level="info",
        token_db_path=":memory:",
    )


def test_redirect_uri_is_derived_from_base_url():
    assert google.redirect_uri(_cfg()) == (
        "https://gsc.example.com/oauth/callback"
    )


def test_authorization_url_requests_offline_readonly_access():
    url = google.authorization_url(_cfg(), "st-1")
    assert url.startswith(google.GOOGLE_AUTH_ENDPOINT)
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["offline"]
    assert q["prompt"] == ["consent"]
    assert q["state"] == ["st-1"]
    assert q["client_id"] == ["cid"]
    assert q["scope"] == [
        "openid email https://www.googleapis.com/auth/webmasters.readonly"
    ]


@pytest.mark.anyio
async def test_exchange_code_posts_client_credentials():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(google.GOOGLE_TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"access_token": "ga", "refresh_token": "gr"}
            )
        )
        result = await google.exchange_code(_cfg(), "the-code")
    assert result["access_token"] == "ga"
    body = parse_qs(route.calls[0].request.content.decode())
    assert body["code"] == ["the-code"]
    assert body["client_secret"] == ["csec"]
    assert body["grant_type"] == ["authorization_code"]


@pytest.mark.anyio
async def test_exchange_code_raises_on_google_error():
    with respx.mock:
        respx.post(google.GOOGLE_TOKEN_ENDPOINT).mock(
            return_value=httpx.Response(400, json={"error": "invalid_grant"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await google.exchange_code(_cfg(), "bad")


@pytest.mark.anyio
async def test_fetch_userinfo_sends_bearer_token():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.get(google.GOOGLE_USERINFO_ENDPOINT).mock(
            return_value=httpx.Response(
                200, json={"sub": "1", "email": "user@example.com"}
            )
        )
        info = await google.fetch_userinfo("ga")
    assert info["email"] == "user@example.com"
    assert route.calls[0].request.headers["authorization"] == "Bearer ga"


def test_build_credentials_carries_the_readonly_scope():
    creds = google.build_credentials(_cfg(), "ga", "gr", None)
    assert creds.token == "ga"
    assert creds.refresh_token == "gr"
    assert creds.scopes == [
        "https://www.googleapis.com/auth/webmasters.readonly"
    ]
    assert creds.expiry is None


def test_build_credentials_converts_expiry_to_naive_utc():
    creds = google.build_credentials(_cfg(), "ga", "gr", 1_700_000_000)
    assert creds.expiry is not None
    assert creds.expiry.tzinfo is None
```

Add an `anyio` backend fixture — put this in a new `tests/remote/conftest.py`:

```python
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/google_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.google'`

- [ ] **Step 3: Write the implementation**

```bash
cp /home/nosync/Coding/Klartika/google-analytics-mcp/analytics_mcp/remote/google.py \
   gsc_remote/google.py
```

Then apply exactly three edits:

1. Prepend as the first line:
   `# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/google.py).`
2. Replace the import
   `from analytics_mcp.remote.config import ANALYTICS_SCOPE, Config`
   with
   `from gsc_remote.config import GSC_SCOPE, Config`
3. Replace both remaining occurrences of `ANALYTICS_SCOPE` with `GSC_SCOPE`
   (one in `authorization_url`'s `scope` parameter, one in
   `build_credentials`'s `scopes` list).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/google_test.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/google.py tests/remote/google_test.py tests/remote/conftest.py
git commit -m "feat(remote): Google OAuth federation with webmasters.readonly"
```

---

### Task 7: The credential seam

This is the fork's load-bearing, GSC-specific piece — it has no direct GA4 equivalent to copy.

**Files:**
- Create: `gsc_remote/credentials.py`
- Test: `tests/remote/credentials_test.py`

**Interfaces:**
- Consumes: `gsc_server.get_gsc_service` (upstream, unmodified).
- Produces: `current_credentials: ContextVar`; `apply_patch() -> None`; `use_credentials(creds)` context manager.

- [ ] **Step 1: Write the failing test**

`tests/remote/credentials_test.py`:

```python
import asyncio

import gsc_server
from gsc_remote import credentials


def test_upstream_chokepoint_still_exists():
    """The whole design rests on this one upstream function. If a rebase
    renames or removes it, fail here rather than at runtime."""
    assert callable(gsc_server.get_gsc_service)


def test_patch_falls_back_to_upstream_when_unset(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        credentials, "_original_get_gsc_service", lambda: sentinel
    )
    credentials.apply_patch()
    assert gsc_server.get_gsc_service() is sentinel


def test_contextvar_builds_a_per_request_service(monkeypatch):
    built = []

    def fake_build(serviceName, version, credentials=None, **kwargs):
        built.append((serviceName, version, credentials, kwargs))
        return f"service-for-{credentials}"

    monkeypatch.setattr(credentials, "build", fake_build)
    credentials.apply_patch()
    with credentials.use_credentials("user-creds"):
        assert gsc_server.get_gsc_service() == "service-for-user-creds"
    assert built[0][0] == "searchconsole"
    assert built[0][1] == "v1"
    assert built[0][3]["cache_discovery"] is False
    assert credentials.current_credentials.get() is None


def test_patch_is_idempotent(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        credentials, "_original_get_gsc_service", lambda: sentinel
    )
    credentials.apply_patch()
    credentials.apply_patch()
    assert gsc_server.get_gsc_service() is sentinel


def test_contextvar_is_task_isolated(monkeypatch):
    monkeypatch.setattr(
        credentials,
        "build",
        lambda serviceName, version, credentials=None, **kw: credentials,
    )
    credentials.apply_patch()

    async def worker(value):
        with credentials.use_credentials(value):
            await asyncio.sleep(0)
            return gsc_server.get_gsc_service()

    async def main():
        return await asyncio.gather(worker("a"), worker("b"))

    assert asyncio.run(main()) == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/credentials_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.credentials'`

- [ ] **Step 3: Write the implementation**

`gsc_remote/credentials.py`:

```python
"""Request-scoped Google credentials, injected into the upstream server.

Upstream ``gsc_server`` resolves credentials through one module-level function,
``get_gsc_service()``, which every tool calls. We rebind that name so the
unchanged tool code builds a Search Console service from the per-request user's
credentials when present, and falls back to upstream's own file/ADC resolution
otherwise. ``contextvars`` makes this safe under concurrency: each request or
task sees only its own credentials.
"""

import contextlib
import contextvars
from typing import Optional

from googleapiclient.discovery import build

import gsc_server as _gsc

current_credentials: contextvars.ContextVar[Optional[object]] = (
    contextvars.ContextVar("gsc_user_credentials", default=None)
)

# Captured once at import so the patch is idempotent and can defer to the
# original even after apply_patch() has run.
_original_get_gsc_service = _gsc.get_gsc_service


def _patched_get_gsc_service():
    creds = current_credentials.get()
    if creds is not None:
        return build(
            "searchconsole", "v1", credentials=creds, cache_discovery=False
        )
    return _original_get_gsc_service()


def apply_patch() -> None:
    """Install the credential override on the upstream module."""
    _gsc.get_gsc_service = _patched_get_gsc_service


@contextlib.contextmanager
def use_credentials(creds):
    """Bind ``creds`` as the current request's Google credentials."""
    token = current_credentials.set(creds)
    try:
        yield
    finally:
        current_credentials.reset(token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/credentials_test.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/credentials.py tests/remote/credentials_test.py
git commit -m "feat(remote): request-scoped credential seam into gsc_server"
```

---

### Task 8: Read-only tool filter

**Files:**
- Create: `gsc_remote/tools.py`
- Test: `tests/remote/tools_test.py`

**Interfaces:**
- Consumes: `gsc_server.mcp` (upstream `FastMCP` instance).
- Produces: `REMOVED_TOOLS: frozenset[str]`; `EXPECTED_REMOTE_TOOLS: frozenset[str]`; `apply_filter() -> None`; `low_level_server()` returning `gsc_server.mcp._mcp_server`.

- [ ] **Step 1: Write the failing test**

`tests/remote/tools_test.py`:

```python
import pytest
from mcp.server.lowlevel.server import Server

import gsc_server
from gsc_remote import tools


def test_low_level_server_is_reachable():
    """app.py hands this private FastMCP attribute to the streamable-HTTP
    session manager. If the SDK renames it, fail here, not in production."""
    assert isinstance(tools.low_level_server(), Server)


def test_upstream_still_registers_every_tool_we_remove():
    # Reads the pre-filter snapshot, so this holds regardless of whether
    # another test in this file has already called apply_filter().
    missing = tools.REMOVED_TOOLS - tools._UPSTREAM_TOOLS_AT_IMPORT
    assert not missing, (
        f"upstream no longer defines {sorted(missing)} — update REMOVED_TOOLS"
    )


def test_filter_leaves_exactly_the_read_only_tools():
    tools.apply_filter()
    remaining = set(gsc_server.mcp._tool_manager._tools)
    assert remaining == set(tools.EXPECTED_REMOTE_TOOLS)


def test_no_write_tool_survives():
    tools.apply_filter()
    remaining = set(gsc_server.mcp._tool_manager._tools)
    for name in ("add_site", "delete_site", "submit_sitemap",
                 "delete_sitemap", "manage_sitemaps"):
        assert name not in remaining


def test_filter_is_idempotent():
    tools.apply_filter()
    first = set(gsc_server.mcp._tool_manager._tools)
    tools.apply_filter()
    assert set(gsc_server.mcp._tool_manager._tools) == first
```

Note: `apply_filter()` mutates the process-wide `gsc_server.mcp` registry, so
these tests are written to be order-independent — `apply_filter()` is
idempotent, and the snapshot assertion reads `tools._UPSTREAM_TOOLS_AT_IMPORT`
rather than the live registry.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/tools_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.tools'`

- [ ] **Step 3: Write the implementation**

`gsc_remote/tools.py`:

```python
"""Restrict the upstream tool set to the read-only surface we expose remotely.

The remote server holds only ``webmasters.readonly``, so upstream's write tools
would fail with a 403 if a model called them. Rather than edit ``gsc_server``,
we remove them from FastMCP's registry at startup. The local/stdio-only
diagnostics go too: they describe credential files that do not exist here.
"""

import logging

import gsc_server as _gsc

log = logging.getLogger("gsc_remote")

REMOVED_TOOLS = frozenset(
    {
        # Write operations — not permitted under webmasters.readonly.
        "add_site",
        "delete_site",
        "submit_sitemap",
        "delete_sitemap",
        "manage_sitemaps",
        # Local-file-auth diagnostics — meaningless on a remote OAuth server.
        "reauthenticate",
        "get_capabilities",
        # Upstream promotional tool.
        "get_creator_info",
    }
)

EXPECTED_REMOTE_TOOLS = frozenset(
    {
        "list_properties",
        "get_site_details",
        "get_search_analytics",
        "get_advanced_search_analytics",
        "get_performance_overview",
        "compare_search_periods",
        "get_search_by_page_query",
        "get_sitemaps",
        "list_sitemaps_enhanced",
        "get_sitemap_details",
        "inspect_url_enhanced",
        "batch_url_inspection",
        "check_indexing_issues",
    }
)

# Snapshot taken before any filtering, so a test can still assert what upstream
# defines even after apply_filter() has run in the same process.
_UPSTREAM_TOOLS_AT_IMPORT = frozenset(_gsc.mcp._tool_manager._tools)


def low_level_server():
    """The low-level ``Server`` inside the upstream FastMCP instance.

    ``StreamableHTTPSessionManager`` needs this object, and FastMCP exposes it
    only as a private attribute. Isolated here so exactly one place depends on
    it, guarded by a test.
    """
    return _gsc.mcp._mcp_server


def apply_filter() -> None:
    """Remove non-read-only tools from the registry. Idempotent."""
    manager = _gsc.mcp._tool_manager
    for name in sorted(REMOVED_TOOLS):
        if name in manager._tools:
            manager.remove_tool(name)
    remaining = frozenset(manager._tools)
    if remaining != EXPECTED_REMOTE_TOOLS:
        unexpected = sorted(remaining - EXPECTED_REMOTE_TOOLS)
        absent = sorted(EXPECTED_REMOTE_TOOLS - remaining)
        raise RuntimeError(
            "upstream tool set drifted — unexpected: "
            f"{unexpected}, missing: {absent}. Review each new tool for write "
            "access before adding it to EXPECTED_REMOTE_TOOLS."
        )
    log.info("exposing %d read-only GSC tools", len(remaining))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/tools_test.py -q`
Expected: 5 passed

If `apply_filter()` raises the drift `RuntimeError`, upstream's tool set has
changed since this plan was written. Reconcile the two frozensets — classifying
each new tool as read or write — before continuing.

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/tools.py tests/remote/tools_test.py
git commit -m "feat(remote): expose only the read-only GSC tool surface"
```

---

### Task 9: OAuth authorization-server provider

**Files:**
- Create: `gsc_remote/provider.py`
- Test: `tests/remote/provider_test.py`

**Interfaces:**
- Consumes: `gsc_remote.config.Config`, `gsc_remote.store.TokenStore`, `gsc_remote.google`.
- Produces: `GoogleMCPProvider(cfg: Config, store: TokenStore)` implementing `OAuthAuthorizationServerProvider` — `get_client`, `register_client`, `authorize`, `load_authorization_code`, `exchange_authorization_code`, `load_access_token`, `load_refresh_token`, `exchange_refresh_token`, `revoke_token`.

- [ ] **Step 1: Write the failing test**

`tests/remote/provider_test.py`:

```python
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from gsc_remote.config import Config
from gsc_remote.provider import GoogleMCPProvider
from gsc_remote.store import TokenStore


def _cfg(tmp_path):
    return Config(
        port=8080,
        base_url="https://gsc.example.com",
        google_client_id="cid",
        google_client_secret="csec",
        jwt_secret="jwt",
        allowed_emails=set(),
        allowed_google_domains={"example.com"},
        access_token_ttl=timedelta(seconds=60),
        trust_proxy=False,
        log_level="info",
        token_db_path=str(tmp_path / "t.db"),
    )


@pytest.fixture
def provider(tmp_path):
    cfg = _cfg(tmp_path)
    return GoogleMCPProvider(cfg, TokenStore(cfg.token_db_path))


def _client():
    return OAuthClientInformationFull(
        client_id="c1",
        client_secret="s1",
        redirect_uris=[AnyUrl("https://client.example.com/cb")],
    )


@pytest.mark.anyio
async def test_client_registration_roundtrip(provider):
    client = _client()
    await provider.register_client(client)
    loaded = await provider.get_client("c1")
    assert loaded.client_id == "c1"
    assert await provider.get_client("nope") is None


@pytest.mark.anyio
async def test_authorize_redirects_to_google_and_stores_state(provider):
    client = _client()
    await provider.register_client(client)
    url = await provider.authorize(
        client,
        AuthorizationParams(
            state="st-1",
            scopes=["openid"],
            code_challenge="ch",
            redirect_uri=AnyUrl("https://client.example.com/cb"),
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )
    assert url.startswith("https://accounts.google.com/")
    assert parse_qs(urlparse(url).query)["state"] == ["st-1"]
    assert provider.store.pop_state("st-1")["client_id"] == "c1"


def _seed_code(provider, code="code-1"):
    provider.store.save_auth_code(
        code=code,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        subject="sub-1",
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        expires_at=time.time() + 600,
    )


@pytest.mark.anyio
async def test_code_exchange_issues_a_token_and_burns_the_code(provider):
    client = _client()
    await provider.register_client(client)
    _seed_code(provider)
    auth_code = await provider.load_authorization_code(client, "code-1")
    assert auth_code is not None
    token = await provider.exchange_authorization_code(client, auth_code)
    assert token.token_type == "Bearer"
    assert token.expires_in == 60
    assert provider.store.get_auth_code("code-1") is None
    row = provider.store.get_by_access(token.access_token)
    assert row["google_refresh"] == "gr"
    assert row["subject"] == "sub-1"


@pytest.mark.anyio
async def test_code_belonging_to_another_client_is_rejected(provider):
    _seed_code(provider)
    other = OAuthClientInformationFull(
        client_id="c2",
        client_secret="s2",
        redirect_uris=[AnyUrl("https://other.example.com/cb")],
    )
    assert await provider.load_authorization_code(other, "code-1") is None


@pytest.mark.anyio
async def test_expired_code_is_rejected(provider):
    client = _client()
    provider.store.save_auth_code(
        code="old",
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        subject="sub-1",
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        expires_at=time.time() - 1,
    )
    assert await provider.load_authorization_code(client, "old") is None


@pytest.mark.anyio
async def test_refresh_rotates_both_tokens_and_keeps_google_grant(provider):
    client = _client()
    await provider.register_client(client)
    _seed_code(provider)
    auth_code = await provider.load_authorization_code(client, "code-1")
    first = await provider.exchange_authorization_code(client, auth_code)

    refresh = await provider.load_refresh_token(client, first.refresh_token)
    second = await provider.exchange_refresh_token(client, refresh, ["openid"])

    assert second.access_token != first.access_token
    assert second.refresh_token != first.refresh_token
    assert provider.store.get_by_access(first.access_token) is None
    assert provider.store.get_by_access(second.access_token)["google_refresh"] == "gr"


@pytest.mark.anyio
async def test_expired_access_token_does_not_load(provider):
    provider.store.save_token(
        access_token="stale",
        refresh_token="r",
        client_id="c1",
        scopes=["openid"],
        expires_at=time.time() - 1,
        google_access="ga",
        google_refresh="gr",
        google_expiry=time.time() + 3600,
        subject="sub-1",
    )
    assert await provider.load_access_token("stale") is None


@pytest.mark.anyio
async def test_revoke_deletes_the_token(provider):
    client = _client()
    await provider.register_client(client)
    _seed_code(provider)
    auth_code = await provider.load_authorization_code(client, "code-1")
    token = await provider.exchange_authorization_code(client, auth_code)
    access = await provider.load_access_token(token.access_token)
    await provider.revoke_token(access)
    assert await provider.load_access_token(token.access_token) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/provider_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.provider'`

- [ ] **Step 3: Write the implementation**

```bash
cp /home/nosync/Coding/Klartika/google-analytics-mcp/analytics_mcp/remote/provider.py \
   gsc_remote/provider.py
```

Then apply exactly two edits:

1. Prepend as the first line:
   `# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/provider.py).`
2. Replace the three import lines

```python
from analytics_mcp.remote import google
from analytics_mcp.remote.config import Config
from analytics_mcp.remote.store import TokenStore
```

with

```python
from gsc_remote import google
from gsc_remote.config import Config
from gsc_remote.store import TokenStore
```

Nothing else in the file references the GA4 package.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/remote/provider_test.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/provider.py tests/remote/provider_test.py
git commit -m "feat(remote): OAuth 2.1 authorization server federating to Google"
```

---

### Task 10: Starlette application

**Files:**
- Create: `gsc_remote/app.py`
- Test: `tests/remote/app_test.py`

**Interfaces:**
- Consumes: every earlier `gsc_remote` module.
- Produces: `create_app(cfg: Config) -> Starlette`; `main() -> None` (the `gsc-mcp-http` console script). Routes: `GET /health`, `GET /oauth/callback`, `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, the SDK auth routes, and `Mount("/mcp")` behind `RequireAuthMiddleware`.

- [ ] **Step 1: Write the failing test**

`tests/remote/app_test.py`:

```python
import importlib
import os
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from gsc_remote import app as app_mod
from gsc_remote.config import load as load_config
from gsc_remote.store import TokenStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SECRET", "jwt")
    # The MCP SDK's create_auth_routes() requires an HTTPS issuer URL, with the
    # sole exception of localhost/127.0.0.1 over HTTP. Use http://localhost so
    # the auth routes build under the test client.
    monkeypatch.setenv("BASE_URL", "http://localhost")
    monkeypatch.setenv("TOKEN_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLOWED_GOOGLE_DOMAINS", "example.com")
    importlib.reload(app_mod)
    return TestClient(
        app_mod.create_app(load_config()), base_url="http://localhost"
    )


def test_health_is_open(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "service": "gsc-mcp"}


def test_protected_resource_metadata_served(client):
    resp = client.get("/.well-known/oauth-protected-resource")
    assert resp.status_code == 200
    body = resp.json()
    assert "authorization_servers" in body
    assert "https://www.googleapis.com/auth/webmasters.readonly" in (
        body["scopes_supported"]
    )


def test_authorization_server_metadata_served(client):
    resp = client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["registration_endpoint"].endswith("/register")


def test_mcp_requires_auth(client):
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def _seed_state(db_path: str, state: str) -> None:
    store = TokenStore(db_path)
    store.save_state(
        state=state,
        client_id="c1",
        redirect_uri="https://client.example.com/cb",
        redirect_uri_provided_explicitly=True,
        code_challenge="ch",
        scopes=["openid"],
        resource=None,
        expires_at=time.time() + 600,
    )


def _mock_google(mock, email):
    mock.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ga",
                "refresh_token": "gr",
                "expires_in": 3600,
            },
        )
    )
    mock.get("https://openidconnect.googleapis.com/v1/userinfo").mock(
        return_value=httpx.Response(
            200, json={"sub": "1", "email": email, "email_verified": True}
        )
    )


def test_oauth_callback_allowed_domain_issues_a_code(client):
    db_path = os.environ["TOKEN_DB_PATH"]
    _seed_state(db_path, "st-allow")
    with respx.mock(assert_all_called=True) as mock:
        _mock_google(mock, "user@example.com")
        resp = client.get(
            "/oauth/callback?code=x&state=st-allow", follow_redirects=False
        )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "state=st-allow" in location
    issued = parse_qs(urlparse(location).query)["code"][0]
    assert TokenStore(db_path).get_auth_code(issued) is not None


def test_oauth_callback_rejected_domain_returns_403(client):
    db_path = os.environ["TOKEN_DB_PATH"]
    _seed_state(db_path, "st-deny")
    with respx.mock(assert_all_called=True) as mock:
        _mock_google(mock, "user@example.net")
        resp = client.get(
            "/oauth/callback?code=y&state=st-deny", follow_redirects=False
        )
    assert resp.status_code == 403


def test_oauth_callback_unknown_state_returns_400(client):
    resp = client.get(
        "/oauth/callback?code=z&state=never-issued", follow_redirects=False
    )
    assert resp.status_code == 400


def test_oauth_callback_google_error_returns_400(client):
    resp = client.get("/oauth/callback?error=access_denied", follow_redirects=False)
    assert resp.status_code == 400


def test_creating_the_app_applies_the_tool_filter(client):
    import gsc_server

    from gsc_remote import tools

    assert set(gsc_server.mcp._tool_manager._tools) == set(
        tools.EXPECTED_REMOTE_TOOLS
    )


def test_creating_the_app_applies_the_credential_patch(client):
    import gsc_server

    from gsc_remote import credentials

    assert gsc_server.get_gsc_service is credentials._patched_get_gsc_service
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/remote/app_test.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'gsc_remote.app'`

- [ ] **Step 3: Write the implementation**

```bash
cp /home/nosync/Coding/Klartika/google-analytics-mcp/analytics_mcp/remote/app.py \
   gsc_remote/app.py
```

Then apply exactly seven edits:

1. Prepend as the first line:
   `# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/app.py).`

2. Replace the import block

```python
import analytics_mcp.coordinator as coordinator
from analytics_mcp.remote import allowlist, credentials, google
from analytics_mcp.remote.config import ANALYTICS_SCOPE, Config
from analytics_mcp.remote.config import load as load_config
from analytics_mcp.remote.provider import GoogleMCPProvider
from analytics_mcp.remote.ratelimit import RateLimitMiddleware
from analytics_mcp.remote.store import TokenStore

log = logging.getLogger("analytics_mcp.remote")
```

with

```python
from gsc_remote import allowlist, credentials, google, tools
from gsc_remote.config import GSC_SCOPE, Config
from gsc_remote.config import load as load_config
from gsc_remote.provider import GoogleMCPProvider
from gsc_remote.ratelimit import RateLimitMiddleware
from gsc_remote.store import TokenStore

log = logging.getLogger("gsc_remote")
```

3. In `create_app`, replace the single line `credentials.apply_patch()` with

```python
    credentials.apply_patch()
    tools.apply_filter()
```

4. Replace `app=coordinator.app,` in the `StreamableHTTPSessionManager(...)`
   call with `app=tools.low_level_server(),`.

5. In `health`, replace the response body with

```python
        return JSONResponse({"status": "healthy", "service": "gsc-mcp"})
```

6. Replace both remaining occurrences of `ANALYTICS_SCOPE` with `GSC_SCOPE` —
   one in `create_protected_resource_routes(scopes_supported=[...])`, one in
   `ClientRegistrationOptions(valid_scopes=[...], default_scopes=[...])` (that
   call contains two references on two lines; both change).

7. Leave `main()` unchanged apart from the logger name — its
   `proxy_headers=True` / `forwarded_allow_ips="*"` settings are what make the
   server see the original `https` scheme behind Nginx Proxy Manager.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: all tests pass — the new `tests/remote/` suite plus upstream's
`test_gsc_server.py`.

Note on ordering, corrected from the original draft of this plan: upstream's
`test_gsc_server.py` does `del sys.modules["gsc_server"]`, so after it runs a
plain `import gsc_server` can return a DIFFERENT module object than the one
`gsc_remote.credentials` and `gsc_remote.tools` captured at import. The two
app-level patch assertions must therefore check `credentials._gsc` and
`tools._gsc` — the object the patch actually targeted — not a fresh import.
Written that way, `uv run pytest -q` passes in any order. Do not "fix" this by
mandating a test order; nothing deletes `sys.modules` at runtime, so a fresh
import is simply the wrong thing to assert against.

- [ ] **Step 5: Commit**

```bash
git add gsc_remote/app.py tests/remote/app_test.py
git commit -m "feat(remote): Starlette app wiring auth, federation, and /mcp"
```

---

### Task 11: Container image

**Files:**
- Create: `Dockerfile.remote`
- Modify: nothing. Upstream's `.dockerignore` and `Dockerfile` are left as they are.

**Interfaces:**
- Consumes: the `gsc-mcp-http` console script from Task 1's `pyproject.toml`.
- Produces: an image whose default command starts the HTTP server on `:8080` and persists its token DB at `/data/tokens.db`.

- [ ] **Step 1: Write `Dockerfile.remote`**

Upstream's `Dockerfile` is left alone; this one is additive.

```dockerfile
# syntax=docker/dockerfile:1
# Image for the remote OAuth HTTP transport (gsc_remote), not upstream's stdio
# server — that one is built from the unmodified `Dockerfile`.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

WORKDIR /app

# Only the package and its dependencies. Tests are deliberately not copied.
COPY pyproject.toml README.md gsc_server.py ./
COPY gsc_remote ./gsc_remote

RUN pip install .

# Run as a non-root user. Pre-create the token-DB directory owned by that user:
# a freshly created Docker named volume inherits this ownership, so the non-root
# process can write the SQLite DB (TOKEN_DB_PATH defaults to /data/tokens.db).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

USER appuser

VOLUME ["/data"]
EXPOSE 8080

CMD ["gsc-mcp-http"]
```

- [ ] **Step 2: Build for arm64 and verify the server starts**

The Portainer host is ARM. Build for that platform explicitly.

```bash
docker buildx build --platform linux/arm64 -f Dockerfile.remote -t gsc-mcp:test --load .
docker run --rm -d --name gsc-smoke -p 18080:8080 \
  -e BASE_URL=http://localhost:18080 \
  -e GOOGLE_CLIENT_ID=cid -e GOOGLE_CLIENT_SECRET=csec -e JWT_SECRET=jwt \
  -e ALLOWED_GOOGLE_DOMAINS=example.com \
  -e TOKEN_DB_PATH=/data/tokens.db \
  -v gsc_smoke_data:/data gsc-mcp:test
sleep 3
curl -sf http://localhost:18080/health
curl -sf http://localhost:18080/.well-known/oauth-protected-resource
curl -si -X POST http://localhost:18080/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -1
docker rm -f gsc-smoke && docker volume rm gsc_smoke_data
```

Expected: `{"status":"healthy","service":"gsc-mcp"}`; JSON metadata containing
`authorization_servers`; and — because `Mount("/mcp", ...)` issues a trailing-
slash redirect — `307` on the first line, then `401 Unauthorized` after the
redirect. Add `-L` to see the 401 directly. A 200 at any point is a real bug.

If the host running this build is not ARM, `--platform linux/arm64` runs under
emulation (needs `docker run --privileged --rm tonistiigi/binfmt --install arm64`
once). The build must still succeed — that is the platform that ships.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile.remote
git commit -m "build: arm64 image for the remote HTTP transport"
```

---

### Task 12: Publish the image to GHCR

**Files:**
- Create: `.github/workflows/publish-image.yml`

**Interfaces:**
- Consumes: `Dockerfile.remote` from Task 11.
- Produces: `ghcr.io/klartika/gsc-mcp-server:vX.Y.Z` and `:sha-<short>` for every `v*` tag — the image Task 14's compose file pins.

- [ ] **Step 1: Write the workflow**

`.github/workflows/publish-image.yml`:

```yaml
# Publishes the remote-transport image on a v* tag. The deployment (in the
# separate infra-ops repo) pins a specific tag from here — it never builds.
name: Publish image

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v5

      - uses: docker/setup-qemu-action@v3
        with:
          platforms: arm64

      - uses: docker/setup-buildx-action@v3

      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/klartika/gsc-mcp-server
          tags: |
            type=ref,event=tag
            type=sha,prefix=sha-

      # linux/arm64 only: the Portainer host is ARM, and nothing else consumes
      # this image. Add linux/amd64 here if that changes.
      - uses: docker/build-push-action@v6
        with:
          context: .
          file: Dockerfile.remote
          platforms: linux/arm64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
```

- [ ] **Step 2: Open the PR and merge**

Everything up to here belongs in one PR — the workflow only fires on tags
pushed to the default branch's history.

```bash
git add .github/workflows/publish-image.yml
git commit -m "ci: publish arm64 image to GHCR on tag"
git push -u origin remote-oauth-mcp
gh pr create --repo Klartika/gsc-mcp-server \
  --title "Remote OAuth 2.1 HTTP transport" \
  --body "Adds gsc_remote/: OAuth 2.1 authorization server federating to Google, SQLite session store, request-scoped credential seam into the unchanged gsc_server tools, read-only tool filter, arm64 image, and GHCR publish workflow. See docs/superpowers/specs/2026-08-13-gsc-remote-mcp-design.md."
```

Merge the PR once CI is green.

- [ ] **Step 3: Tag the first release and verify the image exists**

```bash
git checkout main && git pull
git tag v0.1.0 && git push origin v0.1.0
gh run watch --repo Klartika/gsc-mcp-server
docker manifest inspect ghcr.io/klartika/gsc-mcp-server:v0.1.0 | head -20
```

Expected: the workflow succeeds and the manifest reports `architecture: arm64`.

If the package is private, make it visible to the deployment host — either set
the GHCR package to public, or add a `docker login ghcr.io` credential on the
Portainer host. Public is simpler and the repo is already public.

---

### Task 13: Google Cloud setup (human step)

**Files:** none — this is console work.

**Interfaces:**
- Consumes: the hostname `<gsc-host>`.
- Produces: `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, stored in Infisical for Task 14.

- [ ] **Step 1: Hand the operator this checklist and wait**

> In the Google Cloud project that already backs the GTM and GA4 MCP servers:
>
> 1. **APIs & Services → Library** → enable **Google Search Console API**.
> 2. **APIs & Services → OAuth consent screen** → confirm the scope
>    `https://www.googleapis.com/auth/webmasters.readonly` is available. It is a
>    non-sensitive scope for internal-type consent screens, so no verification is
>    needed for a Workspace-internal app.
> 3. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
>    - Application type: **Web application**
>    - Name: something identifying this server, e.g. `GSC MCP (remote)`
>    - **Authorized redirect URIs:** `https://<gsc-host>/oauth/callback`
>      — exactly this, no trailing slash.
> 4. Copy the **Client ID** and **Client secret**.
>
> Create a *new* client rather than reusing GA4's, so consent and revocation stay
> per-server.

- [ ] **Step 2: Store the credentials in Infisical**

In Infisical project `infra-ops`, environment `prod`, create folder `/gsc-mcp/`
and add:

| Secret | Value |
| --- | --- |
| `GOOGLE_CLIENT_ID` | from step 1 |
| `GOOGLE_CLIENT_SECRET` | from step 1 |
| `JWT_SECRET` | `openssl rand -base64 32` |
| `ALLOWED_GOOGLE_DOMAINS` | the Workspace domain that may sign in |
| `ALLOWED_EMAILS` | optional; comma-separated, or leave empty |

- [ ] **Step 3: Confirm before continuing**

Do not start Task 14 until the operator confirms the OAuth client exists and the
Infisical folder is populated. The stack cannot come up healthy without it.

---

### Task 14: infra-ops stack

**Files (in `/home/nosync/Coding/Klartika/infra-ops`, a separate repo):**
- Create: `gsc-mcp/docker-compose.yml`, `gsc-mcp/README.md`, `.github/workflows/deploy-gsc-mcp.yml`
- Modify: `README.md` (stacks table), `AGENTS.md` (stack table)

**Interfaces:**
- Consumes: `ghcr.io/klartika/gsc-mcp-server:v0.1.0` from Task 12; the Infisical `/gsc-mcp/` folder from Task 13.
- Produces: a running container named `mcp-google-search-console` on the `docker_bridge` network, port 8080.

- [ ] **Step 1: Branch in infra-ops**

```bash
cd /home/nosync/Coding/Klartika/infra-ops
git checkout -b add-gsc-mcp-stack
mkdir gsc-mcp
```

- [ ] **Step 2: Write `gsc-mcp/docker-compose.yml`**

Substitute the real hostname for `<gsc-host>` — unlike the app repo, hostnames
belong here (see `grafana-loki/docker-compose.yml`).

```yaml
# =========================================================================
# mcp-google-search-console — remote MCP server for Google Search Console.
#
# Each user signs in with their own Google account (webmasters.readonly);
# there is no service account and no credential file. Sessions persist in a
# SQLite DB on the mcp_gsc_data volume, so users stay authenticated across
# restarts.
#
# The image is built and published by the Klartika/gsc-mcp-server repo on a
# v* tag; nothing is built here. To update, bump the pinned tag below.
#
# Secrets are NOT Portainer stack env vars — they are synced in from
# Infisical (/gsc-mcp folder) by the deploy-gsc-mcp GitHub Actions workflow,
# which calls Portainer's git/redeploy API. They default to empty so the
# stack can be created before the first sync runs; the container simply
# fails its healthcheck until real values arrive.
#
# Exposed via Nginx Proxy Manager at https://<gsc-host> — see README.md in
# this directory for the required SSE settings.
# =========================================================================

networks:
  docker_bridge:
    external: true

volumes:
  mcp_gsc_data: {}

services:
  mcp-google-search-console:
    image: ghcr.io/klartika/gsc-mcp-server:v0.1.0
    container_name: mcp-google-search-console
    restart: unless-stopped

    environment:
      BASE_URL: https://<gsc-host>
      TOKEN_DB_PATH: /data/tokens.db
      TRUST_PROXY: "true"
      LOG_LEVEL: info
      GOOGLE_CLIENT_ID: ${GOOGLE_CLIENT_ID:-}
      GOOGLE_CLIENT_SECRET: ${GOOGLE_CLIENT_SECRET:-}
      JWT_SECRET: ${JWT_SECRET:-}
      ALLOWED_GOOGLE_DOMAINS: ${ALLOWED_GOOGLE_DOMAINS:-}
      ALLOWED_EMAILS: ${ALLOWED_EMAILS:-}

    volumes:
      - mcp_gsc_data:/data

    networks:
      - docker_bridge

    healthcheck:
      # The python:slim base image has no wget or curl; use Python's stdlib
      # urllib (urlopen raises on non-200, so a failed check exits non-zero).
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

- [ ] **Step 3: Write `gsc-mcp/README.md`**

```markdown
# gsc-mcp

Remote MCP server for Google Search Console. Each user signs in with their own
Google account; the server holds `webmasters.readonly` and exposes 13 read-only
tools (search analytics, sitemaps, URL inspection).

Image source: [`Klartika/gsc-mcp-server`](https://github.com/Klartika/gsc-mcp-server)
— a fork of `AminForou/mcp-gsc` that adds the OAuth 2.1 HTTP transport. Design:
`docs/superpowers/specs/2026-08-13-gsc-remote-mcp-design.md` in that repo.

## Secrets (Infisical `/gsc-mcp`, env `prod`)

| Secret | How to get it |
| --- | --- |
| `GOOGLE_CLIENT_ID` | Google Cloud → Credentials → OAuth client (Web application) |
| `GOOGLE_CLIENT_SECRET` | same client |
| `JWT_SECRET` | `openssl rand -base64 32` |
| `ALLOWED_GOOGLE_DOMAINS` | Workspace domain(s) permitted to sign in, comma-separated |
| `ALLOWED_EMAILS` | optional; individual addresses outside those domains |

Leaving both allowlist values empty puts the server in **open mode** — anyone
with a Google account can connect. It logs a warning; do not run that way.

## Google Cloud

One OAuth client dedicated to this server (not shared with GA4), in the same
project. Enable the **Google Search Console API**, and set the authorized
redirect URI to `https://<gsc-host>/oauth/callback` exactly.

## Nginx Proxy Manager

Proxy host → `mcp-google-search-console` port `8080`, **Websockets Support ON**,
SSL with Force SSL.

MCP responses stream as `text/event-stream`, so NPM must not buffer them. In
**Advanced → Custom Nginx Configuration**:

```nginx
proxy_buffering off;
proxy_read_timeout 3600s;
```

Also ensure `X-Forwarded-Proto` reaches the container (the app runs uvicorn with
`proxy_headers=True`). Without it the `/mcp` → `/mcp/` 307 redirect downgrades
to `http://` and the Claude handshake breaks.

If the zone is on Cloudflare, keep this record **DNS-only (grey cloud)** —
Cloudflare's proxy buffers SSE and imposes request timeouts.

## Updating

Bump the pinned image tag in `docker-compose.yml` and push. The
`deploy-gsc-mcp` workflow redeploys with `RepullImageAndRedeploy: true`.

## Connecting from Claude

Settings → Connectors → Add custom connector → `https://<gsc-host>/mcp`. Sign in
with a Google account matching the allowlist. The session persists in
`/data/tokens.db` for `ACCESS_TOKEN_TTL_SECONDS` (default 24 h).
```

- [ ] **Step 4: Bootstrap the stack in Portainer, then record its ID**

`git/redeploy` needs an existing git-linked stack, so the first creation is
manual. Push the branch and merge it first so the compose file is on `main`:

```bash
git add gsc-mcp/
git commit -m "feat(gsc-mcp): remote Google Search Console MCP stack"
```

Then in Portainer: **Stacks → Add stack → Repository**
- Repository URL: the `infra-ops` repo
- Compose path: `gsc-mcp/docker-compose.yml`
- **Environment variables: none** — the `${VAR:-}` defaults make the stack
  deployable without them, and typing secrets here is exactly what this repo
  exists to avoid.
- Enable **Re-pull image** and **Force redeployment**; leave Portainer's own
  **Automatic updates** polling **off**.

The container will start and fail its healthcheck. That is expected until the
first workflow run lands the secrets. Note the stack's numeric ID from its URL.

- [ ] **Step 5: Write `.github/workflows/deploy-gsc-mcp.yml`**

Substitute the stack ID from step 4 for `<STACK_ID>`. Copy the env block's other
values from `deploy-grafana-loki.yml` — they are the same Portainer, endpoint,
and Infisical workspace.

```yaml
# Syncs this stack's secrets from Infisical and redeploys from git, whenever
# gsc-mcp/ changes. See the repo README for why this is a workflow with a
# `paths:` trigger rather than Portainer's own webhook (GitHub webhooks are
# repo-scoped, so a native webhook would redeploy this stack on any commit to
# infra-ops, and a webhook cannot set env vars at all).
#
# Calls `PUT /stacks/{id}/git/redeploy` — NOT `PUT /stacks/{id}`, which
# silently detaches a git-linked stack from git (2026-08-11 incident; see
# deploy-grafana-loki.yml).
name: Deploy gsc-mcp

on:
  push:
    branches: [main]
    paths:
      - 'gsc-mcp/**'

env:
  PORTAINER_URL: https://portainer.liro.cc
  PORTAINER_STACK_ID: <STACK_ID>
  PORTAINER_ENDPOINT_ID: 2
  INFISICAL_URL: https://keys.klartika.com
  INFISICAL_WORKSPACE_ID: 91cf4405-0cb9-4236-970d-1c1f3f5ccc3c
  INFISICAL_ENVIRONMENT: prod

jobs:
  redeploy:
    runs-on: ubuntu-latest
    steps:
      - name: Sync secrets from Infisical and redeploy via git
        run: |
          set -euo pipefail

          INFISICAL_TOKEN=$(curl -sf -X POST "$INFISICAL_URL/api/v1/auth/universal-auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"clientId\":\"${{ secrets.INFISICAL_CLIENT_ID }}\",\"clientSecret\":\"${{ secrets.INFISICAL_CLIENT_SECRET }}\"}" \
            | jq -r .accessToken)

          # $1 = secret name, $2 = Infisical folder path (default root -- shared
          # secrets like GITHUB_PAT live there; stack-specific ones live under
          # /<stack-name>).
          fetch_secret() {
            curl -sf "$INFISICAL_URL/api/v3/secrets/raw/$1?workspaceId=$INFISICAL_WORKSPACE_ID&environment=$INFISICAL_ENVIRONMENT&secretPath=${2:-/}" \
              -H "Authorization: Bearer $INFISICAL_TOKEN" | jq -r .secret.secretValue
          }

          GOOGLE_CLIENT_ID=$(fetch_secret GOOGLE_CLIENT_ID /gsc-mcp)
          GOOGLE_CLIENT_SECRET=$(fetch_secret GOOGLE_CLIENT_SECRET /gsc-mcp)
          JWT_SECRET=$(fetch_secret JWT_SECRET /gsc-mcp)
          ALLOWED_GOOGLE_DOMAINS=$(fetch_secret ALLOWED_GOOGLE_DOMAINS /gsc-mcp)
          ALLOWED_EMAILS=$(fetch_secret ALLOWED_EMAILS /gsc-mcp || echo "")
          GITHUB_PAT=$(fetch_secret GITHUB_PAT)
          GITHUB_USERNAME=$(fetch_secret GITHUB_USERNAME)
          PORTAINER_API_TOKEN=$(fetch_secret PORTAINER_API_TOKEN)

          PAYLOAD=$(jq -n \
            --arg ci "$GOOGLE_CLIENT_ID" \
            --arg cs "$GOOGLE_CLIENT_SECRET" \
            --arg js "$JWT_SECRET" \
            --arg ad "$ALLOWED_GOOGLE_DOMAINS" \
            --arg ae "$ALLOWED_EMAILS" \
            --arg u "$GITHUB_USERNAME" \
            --arg p "$GITHUB_PAT" \
            '{Env: [
                {name: "GOOGLE_CLIENT_ID", value: $ci},
                {name: "GOOGLE_CLIENT_SECRET", value: $cs},
                {name: "JWT_SECRET", value: $js},
                {name: "ALLOWED_GOOGLE_DOMAINS", value: $ad},
                {name: "ALLOWED_EMAILS", value: $ae}
              ],
              RepositoryAuthentication: true,
              RepositoryUsername: $u,
              RepositoryPassword: $p,
              RepullImageAndRedeploy: true}')

          curl -sf -X PUT "$PORTAINER_URL/api/stacks/$PORTAINER_STACK_ID/git/redeploy?endpointId=$PORTAINER_ENDPOINT_ID" \
            -H "X-API-Key: $PORTAINER_API_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$PAYLOAD" \
            -o /dev/null
```

- [ ] **Step 6: Update the two repo-level tables**

In `infra-ops/README.md`, add to the Stacks table:

```markdown
| `gsc-mcp/` | `mcp-google-search-console` | Remote OAuth MCP server for Google Search Console. Secrets synced from Infisical. See `gsc-mcp/README.md`. |
```

And to the Infisical folder-layout block:

```
/gsc-mcp/        — GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET, ALLOWED_GOOGLE_DOMAINS, ALLOWED_EMAILS
```

In `infra-ops/AGENTS.md`, add to the stack table:

```markdown
| [`gsc-mcp`](gsc-mcp/README.md) | per-user Google OAuth (not a service account), the NPM SSE settings MCP streaming needs, and where the image comes from (built in a separate repo, pinned here). |
```

- [ ] **Step 7: Push, merge, and verify the sync ran**

```bash
git add .github/workflows/deploy-gsc-mcp.yml README.md AGENTS.md gsc-mcp/
git commit -m "ci(gsc-mcp): sync secrets from Infisical and redeploy"
git push -u origin add-gsc-mcp-stack
gh pr create --repo Klartika/infra-ops --title "Add gsc-mcp stack" \
  --body "Remote Google Search Console MCP server, deployed the infra-ops way: image pinned from GHCR, secrets synced from Infisical, redeploy via git/redeploy."
```

Merge, then watch the workflow and verify the stack is still git-linked — the
check that would have caught the 2026-08-11 incident:

```bash
gh run watch --repo Klartika/infra-ops
curl -sf "https://portainer.liro.cc/api/stacks/<STACK_ID>" \
  -H "X-API-Key: $PORTAINER_API_TOKEN" | jq '{GitConfig, IsDetachedFromGit}'
docker ps --filter name=mcp-google-search-console
```

Expected: `GitConfig` non-null, `IsDetachedFromGit` false, container `healthy`.

---

### Task 15: Expose and verify end to end

**Files:**
- Create: `DEPLOY.md` in `Klartika/gsc-mcp-server`

**Interfaces:**
- Consumes: the running stack from Task 14.
- Produces: a working connector in Claude and a deployment guide for the fork.

- [ ] **Step 1: Configure the Nginx Proxy Manager host**

Proxy Host:
- Domain: `<gsc-host>`
- Scheme `http`, Forward Hostname `mcp-google-search-console`, Forward Port `8080`
- **Websockets Support: ON**
- SSL: Let's Encrypt + **Force SSL**
- Advanced → Custom Nginx Configuration:

```nginx
proxy_buffering off;
proxy_read_timeout 3600s;
```

If the zone is on Cloudflare, set the DNS record to **DNS-only (grey cloud)**.

- [ ] **Step 2: Verify the public endpoints**

```bash
curl -sf https://<gsc-host>/health
curl -sf https://<gsc-host>/.well-known/oauth-protected-resource | jq .
curl -si -X POST https://<gsc-host>/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | head -5
```

Expected: `{"status":"healthy","service":"gsc-mcp"}`; metadata listing
`webmasters.readonly` in `scopes_supported`; and, following the `307` that
`Mount("/mcp", ...)` issues to `/mcp/`, a `401` with a `WWW-Authenticate`
header. Use `curl -sL -o /dev/null -w '%{http_code}\n'` to check the final
code.

- [ ] **Step 3: Connect from Claude and exercise a real tool**

Settings → Connectors → Add custom connector → `https://<gsc-host>/mcp`. Sign in
with an allowlisted Google account. Then confirm, in order:

1. `tools/list` shows exactly **13** tools and no `add_site`, `delete_site`,
   `submit_sitemap`, `delete_sitemap` or `manage_sitemaps`.
2. `list_properties` returns the signed-in user's own GSC properties.
3. `get_search_analytics` on one of those properties returns rows.
4. Signing in with a non-allowlisted account is refused with the 403 message.

Record the outcome of each. A failure here is a real defect, not a config nit —
stop and diagnose rather than working around it.

- [ ] **Step 4: Write `DEPLOY.md` in the fork**

Keep it hostname-free (`<your-host>`), since the fork is public. Cover: creating
the Google OAuth client and enabling the Search Console API; the environment
variables and what each does; that the image is published on a `v*` tag and
deployed from a separate infra repo; the NPM settings above and why (SSE
buffering, `X-Forwarded-Proto`, the `/mcp` → `/mcp/` 307); and the three curl
checks from step 2. Add a "Syncing with upstream" section:

```bash
git fetch upstream
git rebase upstream/main
uv run pytest -q     # tools_test and credentials_test guard the two seams
git push origin remote-oauth-mcp
```

- [ ] **Step 5: Commit and PR**

```bash
cd /home/nosync/Coding/Klartika/gsc-mcp-server
git checkout -b docs-deploy
git add DEPLOY.md
git commit -m "docs: deployment guide for the remote transport"
git push -u origin docs-deploy
gh pr create --repo Klartika/gsc-mcp-server --title "Add DEPLOY.md" --body "Deployment guide covering the Google OAuth client, env vars, NPM settings, and verification."
```

---

### Task 16: Narrow security review on Fable

**Files:** none changed by the review itself; fixes land in follow-up commits.

**Interfaces:**
- Consumes: the merged `gsc_remote/` package.
- Produces: a reviewed auth surface, with any findings either fixed or filed as GitHub issues.

- [ ] **Step 1: Run the review, scoped tightly**

Fable is expensive, so the scope is only the auth code this fork wrote — not
upstream's `gsc_server.py`, not the deployment YAML, not the tests.

Dispatch a single agent with `model: "fable"` over exactly these files:

```
gsc_remote/provider.py
gsc_remote/app.py
gsc_remote/store.py
gsc_remote/google.py
gsc_remote/credentials.py
gsc_remote/allowlist.py
gsc_remote/ratelimit.py
```

Ask it for concrete, exploitable findings only, each with a failure scenario,
concentrating on: authorization-code and refresh-token handling (replay, client
substitution, PKCE), redirect-URI validation, federation-state binding and
expiry, allowlist bypass (unverified email, `hd` spoofing, case handling),
credential `ContextVar` leakage between concurrent requests, SQL construction in
`store.py`, and secret leakage through log lines or error responses.

- [ ] **Step 2: Triage every finding**

For each: confirm it against the code before acting — an agent's report is a
lead, not a verdict. Fix confirmed issues on a branch with a regression test
first (TDD still applies). File anything real but out of scope as a GitHub issue
on `Klartika/gsc-mcp-server` with the evidence and the concrete fix, per the
fork's issue-tracking practice.

- [ ] **Step 3: Re-run the suite and report**

```bash
uv run pytest -q
```

Expected: green. Then report to the operator: what was reviewed, what was found,
what was fixed, and what was filed. If nothing was found, say that plainly.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: repository layout and
`pyproject` edits → Task 1; hard rules → Global Constraints and Task 1's
`AGENTS.md`; each `gsc_remote` module → Tasks 2–10; the FastMCP integration risk
→ Task 8's `low_level_server()` and its test; the read-only tool surface →
Task 8; access control → Tasks 3 and 10; configuration table → Task 2;
deployment (app repo) → Tasks 11–12; Google Cloud → Task 13; deployment
(infra-ops) → Task 14; NPM, bootstrap, release flow → Tasks 14–15; testing →
each task plus Task 15; the Fable security pass → Task 16. The spec's
"out of scope" items are correctly absent.

**Known divergences from the spec, deliberate:** the spec's file table lists
`DEPLOY.md` alongside `AGENTS.md` in one row; here `AGENTS.md` lands in Task 1
(it governs all later work) and `DEPLOY.md` in Task 15 (it documents a
deployment that does not exist until then).

**Type consistency.** `Config` field order is identical in Tasks 2, 3, 6 and 9.
`GSC_SCOPE` is the single scope constant everywhere. `apply_patch()`,
`use_credentials()`, `current_credentials` and `_patched_get_gsc_service` are
named identically in Tasks 7 and 10. `apply_filter()`, `low_level_server()`,
`REMOVED_TOOLS` and `EXPECTED_REMOTE_TOOLS` match across Tasks 8 and 10. The
image reference `ghcr.io/klartika/gsc-mcp-server:v0.1.0` is the same in Tasks 12
and 14. The container name `mcp-google-search-console` matches between Task 14's
compose file and Task 15's NPM forward host.

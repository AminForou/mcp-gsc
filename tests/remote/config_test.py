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
        "ALLOW_OPEN_ACCESS",
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
    # Open access is never the default — it must be asked for.
    assert cfg.allow_open_access is False


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


def test_open_access_is_an_explicit_opt_in(monkeypatch):
    assert _load(monkeypatch, ALLOW_OPEN_ACCESS="true").allow_open_access is True
    assert _load(monkeypatch, ALLOW_OPEN_ACCESS="no").allow_open_access is False


def test_empty_domains_env_means_open(monkeypatch):
    cfg = _load(monkeypatch, ALLOWED_GOOGLE_DOMAINS="")
    assert cfg.allowed_google_domains == set()

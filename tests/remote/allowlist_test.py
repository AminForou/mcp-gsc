from datetime import timedelta

from gsc_remote.allowlist import identity_allowed, is_open
from gsc_remote.config import Config


def _cfg(emails=None, domains=None, open_access=False):
    return Config(
        port=8080,
        base_url="https://x",
        google_client_id="",
        google_client_secret="",
        jwt_secret="",
        allowed_emails=emails or set(),
        allowed_google_domains=domains or set(),
        allow_open_access=open_access,
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


def test_unconfigured_allowlist_fails_closed():
    """A forgotten env var must not silently open the server to everyone."""
    cfg = _cfg()
    assert is_open(cfg) is True
    assert identity_allowed(cfg, "anyone@example.net", None, True) is False


def test_open_access_requires_an_explicit_opt_in():
    cfg = _cfg(open_access=True)
    assert identity_allowed(cfg, "anyone@example.net", None, True) is True


def test_opt_in_does_not_override_a_configured_allowlist():
    cfg = _cfg(domains={"example.com"}, open_access=True)
    assert identity_allowed(cfg, "x@example.net", None, True) is False

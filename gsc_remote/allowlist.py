# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/allowlist.py).
"""Access allowlist enforced after Google verifies a user's identity."""

import logging

from gsc_remote.config import Config

log = logging.getLogger("gsc_remote")


def is_open(cfg: Config) -> bool:
    """True when no allowlist is configured at all."""
    return not cfg.allowed_emails and not cfg.allowed_google_domains


def identity_allowed(cfg: Config, email, hd, verified) -> bool:
    if is_open(cfg):
        # Fail closed. An unset allowlist is far more often a forgotten
        # environment variable than a deliberate decision to let every Google
        # account in, so running open requires saying so explicitly.
        if not cfg.allow_open_access:
            log.error(
                "refusing sign-in: no allowlist configured. Set "
                "ALLOWED_GOOGLE_DOMAINS or ALLOWED_EMAILS, or set "
                "ALLOW_OPEN_ACCESS=true to deliberately accept any Google "
                "account."
            )
            return False
        log.warning(
            "access allowlist is OPEN (ALLOW_OPEN_ACCESS=true) — any Google "
            "account can use this server"
        )
        return True
    if not email or not verified:
        return False
    email = email.lower()
    if email in cfg.allowed_emails:
        return True
    domain = (hd or email.split("@")[-1]).lower()
    return domain in cfg.allowed_google_domains

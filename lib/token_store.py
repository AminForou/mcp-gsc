"""Vercel KV (Upstash Redis) token storage for the shared multi-account pool.

Keys:
- ``gsc:token:<email>``   -> JSON string of google.oauth2.credentials.Credentials
- ``gsc:accounts``        -> SET of linked Google emails
- ``gsc:default_account`` -> string, the default account when a tool call omits ``account``
- ``gsc:oauth_state:<s>`` -> short-lived nonce written by /api/oauth/start, popped by /callback
"""

from __future__ import annotations

import json
import os
from typing import Optional

import requests


_TOKEN_PREFIX = "gsc:token:"
_ACCOUNTS_SET = "gsc:accounts"
_DEFAULT_KEY = "gsc:default_account"
_STATE_PREFIX = "gsc:oauth_state:"


def _kv_url() -> str:
    url = os.environ.get("KV_REST_API_URL")
    if not url:
        raise RuntimeError(
            "KV_REST_API_URL is not set. Provision Vercel KV (Upstash Redis) and "
            "redeploy so KV_REST_API_URL and KV_REST_API_TOKEN are populated."
        )
    return url.rstrip("/")


def _kv_token() -> str:
    tok = os.environ.get("KV_REST_API_TOKEN")
    if not tok:
        raise RuntimeError("KV_REST_API_TOKEN is not set.")
    return tok


def _kv(*command: str) -> object:
    """Execute a single Upstash REST command and return the parsed `result` field."""
    resp = requests.post(
        _kv_url(),
        headers={"Authorization": f"Bearer {_kv_token()}"},
        json=list(command),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json().get("result")


def get_token(email: str) -> Optional[dict]:
    raw = _kv("GET", _TOKEN_PREFIX + email)
    if not raw:
        return None
    return json.loads(raw)


def set_token(email: str, creds_json: str) -> None:
    _kv("SET", _TOKEN_PREFIX + email, creds_json)
    _kv("SADD", _ACCOUNTS_SET, email)
    if not get_default():
        set_default(email)


def list_accounts() -> list[str]:
    members = _kv("SMEMBERS", _ACCOUNTS_SET) or []
    return sorted(members)


def get_default() -> Optional[str]:
    return _kv("GET", _DEFAULT_KEY)


def set_default(email: str) -> None:
    _kv("SET", _DEFAULT_KEY, email)


def put_oauth_state(state: str, value: str = "1", ttl_seconds: int = 600) -> None:
    _kv("SET", _STATE_PREFIX + state, value, "EX", str(ttl_seconds))


def pop_oauth_state(state: str) -> Optional[str]:
    key = _STATE_PREFIX + state
    value = _kv("GET", key)
    if value is not None:
        _kv("DEL", key)
    return value

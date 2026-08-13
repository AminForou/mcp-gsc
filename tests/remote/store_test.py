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

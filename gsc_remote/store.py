# Adapted from Klartika/google-analytics-mcp (analytics_mcp/remote/store.py).
"""SQLite-backed persistence for OAuth clients, tokens, codes, and states."""

import json
import os
import sqlite3
import threading
import time

from mcp.shared.auth import OAuthClientInformationFull


class TokenStore:
    def __init__(self, path: str):
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS clients (
                    client_id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS states (
                    state TEXT PRIMARY KEY,
                    client_id TEXT, redirect_uri TEXT,
                    redirect_uri_provided_explicitly INTEGER,
                    code_challenge TEXT, scopes TEXT, resource TEXT,
                    expires_at REAL, binding_hash TEXT
                );
                CREATE TABLE IF NOT EXISTS auth_codes (
                    code TEXT PRIMARY KEY,
                    client_id TEXT, redirect_uri TEXT,
                    redirect_uri_provided_explicitly INTEGER,
                    code_challenge TEXT, scopes TEXT, resource TEXT, subject TEXT,
                    google_access TEXT, google_refresh TEXT, google_expiry REAL,
                    expires_at REAL, email TEXT, hd TEXT
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    access_token TEXT PRIMARY KEY,
                    refresh_token TEXT, client_id TEXT, scopes TEXT,
                    expires_at REAL, google_access TEXT, google_refresh TEXT,
                    google_expiry REAL, subject TEXT, email TEXT, hd TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tokens_refresh
                    ON tokens(refresh_token);
                """)

    # --- clients ---
    def save_client(self, client: OAuthClientInformationFull) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO clients(client_id, data) VALUES (?, ?)",
                (client.client_id, client.model_dump_json()),
            )

    def get_client(self, client_id: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM clients WHERE client_id = ?", (client_id,)
            ).fetchone()
        if row is None:
            return None
        return OAuthClientInformationFull.model_validate_json(row["data"])

    # --- states ---
    def save_state(
        self,
        *,
        state,
        client_id,
        redirect_uri,
        redirect_uri_provided_explicitly,
        code_challenge,
        scopes,
        resource,
        expires_at,
        binding_hash=None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO states VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    state,
                    client_id,
                    redirect_uri,
                    int(redirect_uri_provided_explicitly),
                    code_challenge,
                    json.dumps(scopes),
                    resource,
                    expires_at,
                    binding_hash,
                ),
            )

    def pop_state(self, state: str):
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT * FROM states WHERE state = ?", (state,)
            ).fetchone()
            if row is None:
                return None
            self._conn.execute("DELETE FROM states WHERE state = ?", (state,))
        if row["expires_at"] < time.time():
            return None
        return {
            "client_id": row["client_id"],
            "redirect_uri": row["redirect_uri"],
            "redirect_uri_provided_explicitly": bool(
                row["redirect_uri_provided_explicitly"]
            ),
            "code_challenge": row["code_challenge"],
            "scopes": json.loads(row["scopes"]),
            "resource": row["resource"],
            "binding_hash": row["binding_hash"],
        }

    # --- auth codes ---
    def save_auth_code(
        self,
        *,
        code,
        client_id,
        redirect_uri,
        redirect_uri_provided_explicitly,
        code_challenge,
        scopes,
        resource,
        subject,
        google_access,
        google_refresh,
        google_expiry,
        expires_at,
        email=None,
        hd=None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO auth_codes "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    code,
                    client_id,
                    redirect_uri,
                    int(redirect_uri_provided_explicitly),
                    code_challenge,
                    json.dumps(scopes),
                    resource,
                    subject,
                    google_access,
                    google_refresh,
                    google_expiry,
                    expires_at,
                    email,
                    hd,
                ),
            )

    def get_auth_code(self, code: str):
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM auth_codes WHERE code = ?", (code,)
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["scopes"] = json.loads(data["scopes"])
        data["redirect_uri_provided_explicitly"] = bool(
            data["redirect_uri_provided_explicitly"]
        )
        return data

    def delete_auth_code(self, code: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM auth_codes WHERE code = ?", (code,))

    # --- tokens ---
    def save_token(
        self,
        *,
        access_token,
        refresh_token,
        client_id,
        scopes,
        expires_at,
        google_access,
        google_refresh,
        google_expiry,
        subject,
        email=None,
        hd=None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    access_token,
                    refresh_token,
                    client_id,
                    json.dumps(scopes),
                    expires_at,
                    google_access,
                    google_refresh,
                    google_expiry,
                    subject,
                    email,
                    hd,
                ),
            )

    def _token_row(self, where: str, value: str):
        with self._lock:
            row = self._conn.execute(
                f"SELECT * FROM tokens WHERE {where} = ?", (value,)
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["scopes"] = json.loads(data["scopes"])
        return data

    def get_by_access(self, access_token: str):
        return self._token_row("access_token", access_token)

    def get_by_refresh(self, refresh_token: str):
        return self._token_row("refresh_token", refresh_token)

    def rotate_token(self, *, old_refresh, **new) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM tokens WHERE refresh_token = ?", (old_refresh,)
            )
            self._conn.execute(
                "INSERT OR REPLACE INTO tokens VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new["access_token"],
                    new["refresh_token"],
                    new["client_id"],
                    json.dumps(new["scopes"]),
                    new["expires_at"],
                    new["google_access"],
                    new["google_refresh"],
                    new["google_expiry"],
                    new["subject"],
                    new.get("email"),
                    new.get("hd"),
                ),
            )

    def delete_by_token(self, token: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM tokens WHERE access_token = ? OR refresh_token = ?",
                (token, token),
            )

    def purge_expired(self) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "DELETE FROM states WHERE expires_at < ?", (now,)
            )
            self._conn.execute(
                "DELETE FROM auth_codes WHERE expires_at < ?", (now,)
            )

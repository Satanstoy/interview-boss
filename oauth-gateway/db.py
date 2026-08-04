"""SQLite database for OAuth gateway (clients, codes, tokens)."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

_DB_PATH = os.getenv("OAUTH_DB_PATH", "/app/oauth-data/oauth-gateway.db")


def _ensure_dir() -> None:
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_conn() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def run_db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with run_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS oauth_clients (
                client_id       TEXT PRIMARY KEY,
                client_secret   TEXT,
                client_name     TEXT NOT NULL,
                redirect_uris   TEXT NOT NULL,
                grant_types     TEXT NOT NULL DEFAULT '["authorization_code","refresh_token"]',
                auth_method     TEXT DEFAULT 'none',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS oauth_codes (
                code              TEXT PRIMARY KEY,
                client_id         TEXT NOT NULL,
                user_id           INTEGER NOT NULL,
                code_challenge    TEXT NOT NULL,
                code_method       TEXT DEFAULT 'S256',
                scopes            TEXT,
                resource          TEXT,
                expires_at        TIMESTAMP NOT NULL,
                used              BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (client_id) REFERENCES oauth_clients(client_id)
            );

            CREATE TABLE IF NOT EXISTS oauth_access_tokens (
                token_hash    TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                client_id     TEXT NOT NULL,
                scopes        TEXT,
                expires_at    TIMESTAMP NOT NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
                token_hash    TEXT PRIMARY KEY,
                user_id       INTEGER NOT NULL,
                client_id     TEXT NOT NULL,
                scopes        TEXT,
                expires_at    TIMESTAMP NOT NULL,
                created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)


# ── InterviewBoss DB helpers ──


def get_interviewboss_db_path() -> str:
    return os.getenv("INTERVIEW_BOSS_DB", "/app/data/interview-boss.db")


def get_interviewboss_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_interviewboss_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def verify_interviewboss_user(username: str, password: str) -> int | None:
    """Verify InterviewBoss credentials, return user_id or None."""
    import bcrypt

    conn = get_interviewboss_conn()
    try:
        row = conn.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if not row:
            return None

        stored_hash = row["password_hash"]
        # bcrypt hashes start with "$2"
        if stored_hash.startswith("$2"):
            if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
                return row["id"]
        return None
    finally:
        conn.close()


def get_user_mcp_token(user_id: int) -> str | None:
    """Get the user's InterviewBoss MCP token (raw, via seed reconstruction)."""
    import hashlib
    import hmac
    import base64
    import os

    conn = get_interviewboss_conn()
    try:
        row = conn.execute(
            "SELECT token_seed, token_hash FROM mcp_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return None

        secret = os.getenv("JWT_SECRET", "")
        seed = row["token_seed"]
        msg = f"interview-boss:mcp:{user_id}:{seed}"
        derived = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()
        token = "ib_mcp_" + base64.urlsafe_b64encode(derived).rstrip(b"=").decode()

        # Verify against stored hash
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        if hmac.compare_digest(token_hash, row["token_hash"]):
            return token
        return None
    finally:
        conn.close()


def issue_interviewboss_mcp_token(user_id: int) -> str | None:
    """Issue an MCP token for the user if they don't have one."""
    import requests

    # This requires the backend to be running; alternatively we can call the
    # token service directly. For the gateway, we'll try direct DB first.
    token = get_user_mcp_token(user_id)
    if token:
        return token

    # No token exists — we can't issue one from the gateway without the
    # HMAC secret that InterviewBoss uses. Return None; the user must
    # first generate a token via the InterviewBoss settings page.
    return None


# ── OAuth CRUD ──


def create_client(
    client_id: str,
    client_secret_hash: str | None,
    client_name: str,
    redirect_uris: list[str],
    auth_method: str = "none",
) -> dict:
    import json

    with run_db() as conn:
        conn.execute(
            """INSERT INTO oauth_clients (client_id, client_secret, client_name, redirect_uris, auth_method)
               VALUES (?, ?, ?, ?, ?)""",
            (
                client_id,
                client_secret_hash,
                client_name,
                json.dumps(redirect_uris),
                auth_method,
            ),
        )
    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "auth_method": auth_method,
    }


def get_client(client_id: str) -> dict | None:
    import json

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM oauth_clients WHERE client_id = ?", (client_id,)
        ).fetchone()
        if not row:
            return None
        return {
            "client_id": row["client_id"],
            "client_secret": row["client_secret"],
            "client_name": row["client_name"],
            "redirect_uris": json.loads(row["redirect_uris"]),
            "auth_method": row["auth_method"],
        }
    finally:
        conn.close()


def save_code(
    code: str,
    client_id: str,
    user_id: int,
    code_challenge: str,
    scopes: str,
    resource: str,
    expires_at: str,
) -> None:
    with run_db() as conn:
        conn.execute(
            """INSERT INTO oauth_codes (code, client_id, user_id, code_challenge, scopes, resource, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, client_id, user_id, code_challenge, scopes, resource, expires_at),
        )


def get_and_use_code(code: str) -> dict | None:
    from datetime import datetime, timezone

    with run_db() as conn:
        row = conn.execute(
            "SELECT * FROM oauth_codes WHERE code = ? AND used = FALSE AND expires_at > ?",
            (code, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        if not row:
            return None
        conn.execute("UPDATE oauth_codes SET used = TRUE WHERE code = ?", (code,))
        return dict(row)


def save_access_token(
    token_hash: str, user_id: int, client_id: str, scopes: str, expires_at: str
) -> None:
    with run_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO oauth_access_tokens (token_hash, user_id, client_id, scopes, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token_hash, user_id, client_id, scopes, expires_at),
        )


def get_access_token(token_hash: str) -> dict | None:
    from datetime import datetime, timezone

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM oauth_access_tokens WHERE token_hash = ? AND expires_at > ?",
            (token_hash, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_refresh_token(
    token_hash: str, user_id: int, client_id: str, scopes: str, expires_at: str
) -> None:
    with run_db() as conn:
        conn.execute(
            """INSERT INTO oauth_refresh_tokens (token_hash, user_id, client_id, scopes, expires_at)
               VALUES (?, ?, ?, ?, ?)""",
            (token_hash, user_id, client_id, scopes, expires_at),
        )


def get_refresh_token(token_hash: str) -> dict | None:
    from datetime import datetime, timezone

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM oauth_refresh_tokens WHERE token_hash = ? AND expires_at > ?",
            (token_hash, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_refresh_token(token_hash: str) -> None:
    with run_db() as conn:
        conn.execute(
            "DELETE FROM oauth_refresh_tokens WHERE token_hash = ?", (token_hash,)
        )

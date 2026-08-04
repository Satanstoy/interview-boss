"""Per-account MCP token lifecycle and authentication helpers."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from app.db.connection import get_db_connection


MCP_TOKEN_PREFIX = "ib_mcp_"
MCP_TOKEN_BYTES = 32


def generate_mcp_token() -> str:
    """Generate an opaque bearer token suitable for an external MCP client."""
    return f"{MCP_TOKEN_PREFIX}{secrets.token_urlsafe(MCP_TOKEN_BYTES)}"


def hash_mcp_token(token: str) -> str:
    """Hash a raw token for storage and constant-shape database lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_hint(token: str) -> str:
    """Return a non-secret hint that helps users identify the active token."""
    return f"…{token[-8:]}"


def issue_mcp_token(user_id: int) -> dict[str, Any]:
    """Create or rotate the single MCP token belonging to ``user_id``."""
    token = generate_mcp_token()
    token_hash = hash_mcp_token(token)
    hint = _token_hint(token)

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO mcp_tokens (user_id, token_hash, token_hint)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                token_hash = excluded.token_hash,
                token_hint = excluded.token_hint,
                rotated_at = CURRENT_TIMESTAMP,
                last_used_at = NULL
            """,
            (int(user_id), token_hash, hint),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT user_id, token_hint, created_at, rotated_at, last_used_at
            FROM mcp_tokens
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()

    return {
        "token": token,
        "token_hint": hint,
        "created_at": row["created_at"] if row else None,
        "rotated_at": row["rotated_at"] if row else None,
        "last_used_at": row["last_used_at"] if row else None,
    }


def get_mcp_token_metadata(user_id: int) -> dict[str, Any] | None:
    """Return token metadata without ever returning the raw token."""
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT token_hint, created_at, rotated_at, last_used_at
            FROM mcp_tokens
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()
    return dict(row) if row else None


def revoke_mcp_token(user_id: int) -> bool:
    """Revoke the current MCP token, if one exists."""
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM mcp_tokens WHERE user_id = ?", (int(user_id),))
        conn.commit()
    return cursor.rowcount > 0


def authenticate_mcp_token(token: str) -> dict[str, Any] | None:
    """Authenticate a raw MCP token and update its last-used timestamp."""
    if not isinstance(token, str) or not token or len(token) > 256:
        return None

    token_hash = hash_mcp_token(token)
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT t.user_id, u.id AS existing_user_id
            FROM mcp_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = ?
            LIMIT 1
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE mcp_tokens SET last_used_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (row["user_id"],),
        )
        conn.commit()

    # The token represents the authenticated account.  "all" lets that
    # account use public questions plus its own personal bank; the tool layer
    # still enforces authoritative visibility on every selected question.
    return {"user_id": int(row["user_id"]), "bank_mode": "all"}

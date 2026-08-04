"""Per-account MCP token lifecycle and authentication helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any

from app.core.auth import SECRET_KEY
from app.db.connection import get_db_connection


MCP_TOKEN_PREFIX = "ib_mcp_"
MCP_TOKEN_BYTES = 32


def _derive_mcp_token(user_id: int, token_seed: str) -> str:
    """Derive a stable opaque token from a non-secret seed and server secret."""
    message = f"interview-boss:mcp:{int(user_id)}:{token_seed}".encode("utf-8")
    digest = hmac.new(SECRET_KEY.encode("utf-8"), message, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{MCP_TOKEN_PREFIX}{encoded}"


def generate_mcp_token(user_id: int, token_seed: str | None = None) -> tuple[str, str]:
    """Return ``(raw_token, seed)`` without persisting the raw token."""
    seed = token_seed or secrets.token_urlsafe(MCP_TOKEN_BYTES)
    return _derive_mcp_token(user_id, seed), seed


def hash_mcp_token(token: str) -> str:
    """Hash a raw token for storage and constant-shape database lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_hint(token: str) -> str:
    """Return a non-secret hint that helps users identify the active token."""
    return f"…{token[-8:]}"


def issue_mcp_token(user_id: int) -> dict[str, Any]:
    """Create or rotate the single MCP token belonging to ``user_id``."""
    token, token_seed = generate_mcp_token(user_id)
    token_hash = hash_mcp_token(token)
    hint = _token_hint(token)

    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO mcp_tokens (user_id, token_hash, token_hint, token_seed)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                token_hash = excluded.token_hash,
                token_hint = excluded.token_hint,
                token_seed = excluded.token_seed,
                rotated_at = CURRENT_TIMESTAMP,
                last_used_at = NULL
            """,
            (int(user_id), token_hash, hint, token_seed),
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


def get_mcp_token_connection(user_id: int) -> dict[str, Any] | None:
    """Return metadata and reconstruct the active raw token when possible."""
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT token_hash, token_hint, token_seed,
                   created_at, rotated_at, last_used_at
            FROM mcp_tokens
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()

    if row is None:
        return None

    result = {
        "token_hint": row["token_hint"],
        "created_at": row["created_at"],
        "rotated_at": row["rotated_at"],
        "last_used_at": row["last_used_at"],
        "token_available": False,
    }
    token_seed = row["token_seed"]
    if not token_seed:
        return result

    token = _derive_mcp_token(user_id, token_seed)
    if not hmac.compare_digest(hash_mcp_token(token), row["token_hash"]):
        return result

    result["token"] = token
    result["token_available"] = True
    return result


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

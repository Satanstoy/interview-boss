"""JWT creation and validation for OAuth tokens."""

from __future__ import annotations

import hashlib
import os
import secrets
import time

from jose import JWTError, jwt

_SECRET = os.getenv("OAUTH_SECRET_KEY", "")
_ALGORITHM = "HS256"
_ACCESS_TTL = 3600  # 1 hour
_REFRESH_TTL = 30 * 86400  # 30 days


def _get_secret() -> str:
    global _SECRET
    if not _SECRET:
        _SECRET = secrets.token_hex(32)
    return _SECRET


def create_access_token(user_id: int, client_id: str, scopes: str) -> str:
    now = int(time.time())
    payload = {
        "iss": "interview-boss-oauth",
        "sub": str(user_id),
        "aud": "mcp",
        "scope": scopes,
        "client_id": client_id,
        "iat": now,
        "exp": now + _ACCESS_TTL,
    }
    return jwt.encode(payload, _get_secret(), algorithm=_ALGORITHM)


def create_refresh_token(user_id: int, client_id: str, scopes: str) -> str:
    return secrets.token_urlsafe(48)


def verify_access_token(token: str) -> dict | None:
    """Verify an OAuth JWT access token. Returns claims or None."""
    try:
        claims = jwt.decode(
            token, _get_secret(), algorithms=[_ALGORITHM], audience="mcp"
        )
        if claims.get("iss") != "interview-boss-oauth":
            return None
        return claims
    except JWTError:
        return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

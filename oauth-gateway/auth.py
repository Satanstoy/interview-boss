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
    if len(_SECRET) < 32:
        raise RuntimeError(
            "OAUTH_SECRET_KEY must be at least 32 characters before serving OAuth tokens"
        )
    return _SECRET


def require_configured_secret() -> None:
    """Fail closed during startup instead of rotating an in-memory secret."""

    _get_secret()


def create_access_token(
    user_id: int, client_id: str, scopes: str, resource: str = ""
) -> str:
    now = int(time.time())
    audience = resource or "mcp"
    payload = {
        "iss": "interview-boss-oauth",
        "sub": str(user_id),
        "aud": audience,
        "scope": scopes,
        "client_id": client_id,
        "iat": now,
        "exp": now + _ACCESS_TTL,
    }
    if resource:
        payload["resource"] = resource
    return jwt.encode(payload, _get_secret(), algorithm=_ALGORITHM)


def create_refresh_token(user_id: int, client_id: str, scopes: str) -> str:
    return secrets.token_urlsafe(48)


def verify_access_token(token: str, expected_resource: str | None = None) -> dict | None:
    """Verify an OAuth JWT access token. Returns claims or None."""
    try:
        claims = jwt.decode(
            token,
            _get_secret(),
            algorithms=[_ALGORITHM],
            audience=expected_resource or "mcp",
        )
        if claims.get("iss") != "interview-boss-oauth":
            return None
        if expected_resource and claims.get("resource") != expected_resource:
            return None
        return claims
    except JWTError:
        return None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

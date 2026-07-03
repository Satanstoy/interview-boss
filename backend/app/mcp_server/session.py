"""Stateful MCP session storage.

Interview MCP tool calls may span multiple HTTP requests. This module stores
per-session chat state (active skills, retrieved questions, etc.) so that an
external agent can load a skill in one call and draw/select questions in the
next without passing the entire state back and forth.

Storage priority:
1. Redis if ``app.state.redis`` is available.
2. SQLite ``mcp_sessions`` table as fallback.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from inspect import isawaitable
from typing import Any

logger = logging.getLogger(__name__)

_MCP_SESSION_TTL_SECONDS = 3600
_SQLITE_TABLE_NAME = "mcp_sessions"

_PERSISTED_STATE_KEYS = (
    "active_skills",
    "active_skill_instructions",
    "candidate_questions",
    "retrieved_questions",
    "session_notes",
    "question_source",
    "question_source_reason",
)


def _get_redis_pool():
    try:
        from app.asgi import app

        return getattr(app.state, "redis", None)
    except Exception:
        return None


def _ensure_sqlite_table(conn) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_SQLITE_TABLE_NAME} (
            session_id TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def _sqlite_conn():
    from app.db.connection import get_db_connection

    conn = get_db_connection()
    _ensure_sqlite_table(conn)
    return conn


def _prune_sqlite_sessions(conn) -> None:
    cutoff = int(time.time()) - _MCP_SESSION_TTL_SECONDS
    conn.execute(
        f"DELETE FROM {_SQLITE_TABLE_NAME} WHERE updated_at < ?",
        (cutoff,),
    )
    conn.commit()


def _load_from_redis(pool, session_id: str) -> dict[str, Any] | None:
    try:
        raw = pool.get(session_id)
        if isawaitable(raw):
            if hasattr(raw, "close"):
                raw.close()
            logger.debug(
                "Redis get returned awaitable in sync MCP session loader; "
                "falling back to SQLite"
            )
            return None
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to load MCP session from Redis")
        return None


def _save_to_redis(
    pool,
    session_id: str,
    state: dict[str, Any],
    ttl_seconds: int = _MCP_SESSION_TTL_SECONDS,
) -> None:
    result = pool.setex(
        session_id,
        ttl_seconds,
        json.dumps(state, ensure_ascii=False),
    )
    if isawaitable(result):
        if hasattr(result, "close"):
            result.close()
        raise RuntimeError("Redis setex returned awaitable in sync MCP session saver")


async def _load_from_redis_async(pool, session_id: str) -> dict[str, Any] | None:
    try:
        raw = pool.get(session_id)
        if isawaitable(raw):
            raw = await raw
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("Failed to load MCP session from Redis")
        return None


async def _save_to_redis_async(
    pool,
    session_id: str,
    state: dict[str, Any],
    ttl_seconds: int = _MCP_SESSION_TTL_SECONDS,
) -> None:
    result = pool.setex(
        session_id,
        ttl_seconds,
        json.dumps(state, ensure_ascii=False),
    )
    if isawaitable(result):
        await result


def _load_from_sqlite(session_id: str) -> dict[str, Any] | None:
    try:
        conn = _sqlite_conn()
        _prune_sqlite_sessions(conn)
        row = conn.execute(
            f"SELECT data_json FROM {_SQLITE_TABLE_NAME} WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["data_json"])
    except Exception:
        logger.exception("Failed to load MCP session from SQLite")
        return None


def _save_to_sqlite(session_id: str, state: dict[str, Any]) -> None:
    conn = _sqlite_conn()
    conn.execute(
        f"""
        INSERT INTO {_SQLITE_TABLE_NAME} (session_id, data_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            data_json = excluded.data_json,
            updated_at = excluded.updated_at
        """,
        (session_id, json.dumps(state, ensure_ascii=False), int(time.time())),
    )
    conn.commit()


def load_mcp_session(session_id: str | None) -> dict[str, Any] | None:
    """Load persisted MCP session state. Returns None if missing or expired."""
    if not session_id:
        return None

    pool = _get_redis_pool()
    if pool is not None:
        state = _load_from_redis(pool, session_id)
        if state is not None:
            return state

    return _load_from_sqlite(session_id)


async def load_mcp_session_async(session_id: str | None) -> dict[str, Any] | None:
    """Async variant for ASGI/MCP paths backed by async Redis clients."""
    if not session_id:
        return None

    pool = _get_redis_pool()
    if pool is not None:
        state = await _load_from_redis_async(pool, session_id)
        if state is not None:
            return state

    return _load_from_sqlite(session_id)


def save_mcp_session(
    session_id: str,
    state: dict[str, Any],
    ttl_seconds: int = _MCP_SESSION_TTL_SECONDS,
) -> None:
    """Persist MCP session state. Only whitelisted keys are stored."""
    persisted = {k: state.get(k) for k in _PERSISTED_STATE_KEYS if k in state}

    pool = _get_redis_pool()
    if pool is not None:
        try:
            _save_to_redis(pool, session_id, persisted, ttl_seconds)
            return
        except Exception:
            logger.exception(
                "Failed to save MCP session to Redis, falling back to SQLite"
            )

    _save_to_sqlite(session_id, persisted)


async def save_mcp_session_async(
    session_id: str,
    state: dict[str, Any],
    ttl_seconds: int = _MCP_SESSION_TTL_SECONDS,
) -> None:
    """Async variant for ASGI/MCP paths backed by async Redis clients."""
    persisted = {k: state.get(k) for k in _PERSISTED_STATE_KEYS if k in state}

    pool = _get_redis_pool()
    if pool is not None:
        try:
            await _save_to_redis_async(pool, session_id, persisted, ttl_seconds)
            return
        except Exception:
            logger.exception(
                "Failed to save MCP session to Redis, falling back to SQLite"
            )

    _save_to_sqlite(session_id, persisted)


def new_session_id() -> str:
    """Generate a new opaque session identifier."""
    return uuid.uuid4().hex

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
import os
import uuid
from datetime import datetime, timedelta, timezone
import asyncio
from contextlib import asynccontextmanager
from inspect import isawaitable
from typing import Any

logger = logging.getLogger(__name__)

_MCP_SESSION_TTL_SECONDS = 3600
_SQLITE_TABLE_NAME = "mcp_sessions"


def _now_iso() -> str:
    """UTC 无时区 ISO 文本，与 SQLite datetime('now') 输出一致（迁移 084 口径）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

_PERSISTED_STATE_KEYS = (
    "active_skills",
    "active_skill_instructions",
    "candidate_questions",
    "retrieved_questions",
    "job_position",
    "session_notes",
    "question_source",
    "question_source_reason",
    "canonical_job_position",
    "job_position_id",
    "job_position_resolution",
    "used_question_ids",
    "session_version",
)

_LOCAL_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


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
            updated_at TEXT NOT NULL
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
    # updated_at 为 ISO 文本（与迁移 084 统一口径），文本比较即时间比较
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=_MCP_SESSION_TTL_SECONDS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn.execute(
        f"DELETE FROM {_SQLITE_TABLE_NAME} WHERE updated_at < ?",
        (cutoff,),
    )
    conn.commit()


def _session_storage_key(session_id: str, user_id: int | None = None) -> str:
    """Keep the same opaque session id separate for every user."""
    namespace = str(int(user_id)) if user_id is not None else "anonymous"
    return f"mcp:{namespace}:{session_id}"


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
        (session_id, json.dumps(state, ensure_ascii=False), _now_iso()),
    )
    conn.commit()


def load_mcp_session(
    session_id: str | None, user_id: int | None = None
) -> dict[str, Any] | None:
    """Load persisted MCP session state. Returns None if missing or expired."""
    if not session_id:
        return None

    storage_key = _session_storage_key(session_id, user_id)
    pool = _get_redis_pool()
    if pool is not None:
        state = _load_from_redis(pool, storage_key)
        if state is not None:
            return state

    return _load_from_sqlite(storage_key)


async def load_mcp_session_async(
    session_id: str | None, user_id: int | None = None
) -> dict[str, Any] | None:
    """Async variant for ASGI/MCP paths backed by async Redis clients."""
    if not session_id:
        return None

    storage_key = _session_storage_key(session_id, user_id)
    pool = _get_redis_pool()
    if pool is not None:
        state = await _load_from_redis_async(pool, storage_key)
        if state is not None:
            return state

    return _load_from_sqlite(storage_key)


def save_mcp_session(
    session_id: str,
    state: dict[str, Any],
    ttl_seconds: int = _MCP_SESSION_TTL_SECONDS,
    user_id: int | None = None,
) -> None:
    """Persist MCP session state. Only whitelisted keys are stored."""
    persisted = {k: state.get(k) for k in _PERSISTED_STATE_KEYS if k in state}

    storage_key = _session_storage_key(session_id, user_id)
    pool = _get_redis_pool()
    if pool is not None:
        try:
            _save_to_redis(pool, storage_key, persisted, ttl_seconds)
            return
        except Exception:
            logger.exception(
                "Failed to save MCP session to Redis, falling back to SQLite"
            )

    _save_to_sqlite(storage_key, persisted)


async def save_mcp_session_async(
    session_id: str,
    state: dict[str, Any],
    ttl_seconds: int = _MCP_SESSION_TTL_SECONDS,
    user_id: int | None = None,
) -> None:
    """Async variant for ASGI/MCP paths backed by async Redis clients."""
    persisted = {k: state.get(k) for k in _PERSISTED_STATE_KEYS if k in state}

    storage_key = _session_storage_key(session_id, user_id)
    pool = _get_redis_pool()
    if pool is not None:
        try:
            await _save_to_redis_async(pool, storage_key, persisted, ttl_seconds)
            return
        except Exception:
            logger.exception(
                "Failed to save MCP session to Redis, falling back to SQLite"
            )

    _save_to_sqlite(storage_key, persisted)


class MCPSessionLockUnavailable(RuntimeError):
    """Raised when a distributed session lock cannot be acquired safely."""


@asynccontextmanager
async def mcp_session_lock(
    session_id: str,
    user_id: int | None = None,
    *,
    timeout_seconds: int = 60,
):
    """Serialize one session across workers, preferring Redis.

    Redis deployments use a distributed lock so two backend processes cannot
    load the same candidate set and then overwrite each other's selection.
    Test/fallback environments without a Redis lock use a bounded-scope local
    lock, which still protects single-process SQLite operation.
    """

    storage_key = _session_storage_key(session_id, user_id)
    pool = _get_redis_pool()
    redis_lock = None
    acquired = False
    # Pytest creates a fresh event loop per test while the FastAPI fixture may
    # keep one Redis client alive; redis-py locks are loop-bound. Production
    # ASGI workers use one loop per client and take the distributed path.
    lock_factory = (
        getattr(pool, "lock", None)
        if pool is not None and os.getenv("ENV", "").lower() != "test"
        else None
    )
    if callable(lock_factory):
        try:
            redis_lock = lock_factory(
                f"mcp-lock:{storage_key}",
                timeout=timeout_seconds,
                blocking_timeout=max(1, timeout_seconds - 5),
            )
            acquired = redis_lock.acquire()
            if isawaitable(acquired):
                acquired = await acquired
        except Exception:
            logger.exception("Failed to acquire MCP Redis session lock")
        else:
            if not acquired:
                raise MCPSessionLockUnavailable("MCP session is busy")
            try:
                yield
            finally:
                released = redis_lock.release()
                if isawaitable(released):
                    await released
            return

    lock = _LOCAL_SESSION_LOCKS.setdefault(storage_key, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise MCPSessionLockUnavailable("MCP session is busy") from exc
    try:
        yield
    finally:
        lock.release()


def new_session_id() -> str:
    """Generate a new opaque session identifier."""
    return uuid.uuid4().hex

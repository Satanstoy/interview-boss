"""Small, fail-open Redis cache helpers for user-facing read models."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import (
    MASTER_BANK_CACHE_MAX_BYTES,
    MASTER_BANK_CACHE_TTL_SECONDS,
)

logger = logging.getLogger("interview-boss")

_cache_client: Redis | None = None
_MASTER_BANK_PREFIX = "interview-boss:cache:v1:master-bank"
_MASTER_BANK_EPOCH_KEY = f"{_MASTER_BANK_PREFIX}:epoch"


def set_cache_client(client: Redis | None) -> None:
    """Set the process-local client created during application startup."""

    global _cache_client
    _cache_client = client


def get_cache_client() -> Redis | None:
    return _cache_client


async def close_cache_client() -> None:
    """Close the async pool without making shutdown depend on Redis."""

    global _cache_client
    client = _cache_client
    _cache_client = None
    if client is None:
        return

    try:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result
    except Exception as exc:  # pragma: no cover - defensive shutdown path
        logger.warning("关闭 Redis cache 连接池失败: %s", exc)


def _cache_signature(
    user: dict,
    *,
    sort: str,
    page: int,
    page_size: int,
    cat1: str | None,
    compact: bool,
    filter_mode: str,
    epoch: str,
) -> str:
    """Build a bounded key while retaining every visibility dimension."""

    payload = {
        "user_id": int(user["id"]),
        "bank_mode": user.get("bank_mode", ""),
        "position_id": user.get("current_position_id"),
        "position": user.get("current_position", ""),
        "sort": sort,
        "page": page,
        "page_size": page_size,
        "cat1": cat1 or "",
        "compact": bool(compact),
        "filter": filter_mode,
        "epoch": epoch,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"{_MASTER_BANK_PREFIX}:u{int(user['id'])}:{digest}"


async def _get_master_bank_epoch(client: Redis) -> str:
    epoch = await client.get(_MASTER_BANK_EPOCH_KEY)
    if epoch is None:
        await client.set(_MASTER_BANK_EPOCH_KEY, "1", nx=True)
        epoch = await client.get(_MASTER_BANK_EPOCH_KEY)
    return str(epoch or "1")


async def get_master_bank_cache(
    user: dict,
    *,
    sort: str,
    page: int,
    page_size: int,
    cat1: str | None,
    compact: bool,
    filter_mode: str,
) -> dict[str, Any] | None:
    """Return a cached response, or None when cache is unavailable/missed."""

    client = get_cache_client()
    if client is None:
        return None
    try:
        epoch = await _get_master_bank_epoch(client)
        key = _cache_signature(
            user,
            sort=sort,
            page=page,
            page_size=page_size,
            cat1=cat1,
            compact=compact,
            filter_mode=filter_mode,
            epoch=epoch,
        )
        raw = await client.get(key)
        if raw is None:
            return None
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except (RedisError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug("读取 master-bank Redis cache 失败，回退 SQLite: %s", exc)
        return None


async def set_master_bank_cache(
    user: dict,
    response: dict[str, Any],
    *,
    sort: str,
    page: int,
    page_size: int,
    cat1: str | None,
    compact: bool,
    filter_mode: str,
) -> None:
    """Cache a bounded response. Cache errors never fail the API request."""

    client = get_cache_client()
    if client is None:
        return
    try:
        epoch = await _get_master_bank_epoch(client)
        key = _cache_signature(
            user,
            sort=sort,
            page=page,
            page_size=page_size,
            cat1=cat1,
            compact=compact,
            filter_mode=filter_mode,
            epoch=epoch,
        )
        encoded = json.dumps(
            response, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MASTER_BANK_CACHE_MAX_BYTES:
            return
        await client.set(
            key,
            encoded.decode("utf-8"),
            ex=MASTER_BANK_CACHE_TTL_SECONDS,
        )
    except (RedisError, TypeError, ValueError) as exc:
        logger.debug("写入 master-bank Redis cache 失败，继续返回 SQLite 结果: %s", exc)


async def invalidate_master_bank_cache() -> None:
    """Invalidate all user variants with one version bump, without key scans."""

    client = get_cache_client()
    if client is None:
        return
    try:
        await client.incr(_MASTER_BANK_EPOCH_KEY)
    except RedisError as exc:
        logger.debug("失效 master-bank Redis cache 失败: %s", exc)

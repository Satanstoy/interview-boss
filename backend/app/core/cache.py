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
_MASTER_BANK_PREFIX = "interview-boss:cache:v2:master-bank"
_MASTER_BANK_EPOCH_KEY = f"{_MASTER_BANK_PREFIX}:epoch"
# per-user epoch process cache：复习/收藏只改本人视图，避免全局 epoch 失效全站缓存。
# 进程内缓存降低 Redis 往返；失效时 pop 该用户条目。
_USER_EPOCH_CACHE: dict[int, str] = {}


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
    user_epoch: str = "1",
) -> str:
    """Build a bounded key while retaining every visibility dimension.

    ``epoch`` is the global version bump (bank-level changes invalidate
    everyone); ``user_epoch`` is the per-user version bump (review/star
    only invalidate that user's master-bank view).
    """

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
        "user_epoch": user_epoch,
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


async def _user_epoch(client: Redis, user_id: int) -> str:
    """Return the per-user epoch (process-cached), used to invalidate only
    the reviewing user's master-bank view on review/star mutations."""

    user_id = int(user_id)
    cached = _USER_EPOCH_CACHE.get(user_id)
    if cached is not None:
        return cached
    key = f"{_MASTER_BANK_PREFIX}:u{user_id}:epoch"
    epoch = await client.get(key)
    if epoch is None:
        await client.set(key, "1", nx=True)
        epoch = await client.get(key)
    value = str(epoch or "1")
    _USER_EPOCH_CACHE[user_id] = value
    return value


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
        user_epoch = await _user_epoch(client, int(user["id"]))
        key = _cache_signature(
            user,
            sort=sort,
            page=page,
            page_size=page_size,
            cat1=cat1,
            compact=compact,
            filter_mode=filter_mode,
            epoch=epoch,
            user_epoch=user_epoch,
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
        user_epoch = await _user_epoch(client, int(user["id"]))
        key = _cache_signature(
            user,
            sort=sort,
            page=page,
            page_size=page_size,
            cat1=cat1,
            compact=compact,
            filter_mode=filter_mode,
            epoch=epoch,
            user_epoch=user_epoch,
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


async def invalidate_master_bank_cache(user_id: int | None = None) -> None:
    """Invalidate master-bank caches with version bumps, without key scans.

    - ``user_id`` omitted -> bump the global epoch (bank-level changes).
    - ``user_id`` given -> bump only that user's epoch (review/star only).
    """

    client = get_cache_client()
    if client is None:
        return
    try:
        if user_id is None:
            await client.incr(_MASTER_BANK_EPOCH_KEY)
        else:
            _USER_EPOCH_CACHE.pop(int(user_id), None)
            uid = int(user_id)
            await client.incr(f"{_MASTER_BANK_PREFIX}:u{uid}:epoch")
    except RedisError as exc:
        logger.debug("失效 master-bank Redis cache 失败: %s", exc)

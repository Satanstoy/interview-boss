"""Redis-based fast idempotency guard for chat turn submissions."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from redis.exceptions import RedisError

from app.core.cache import (
    try_claim_chat_turn,
    release_chat_turn_claim,
    _CHAT_TURN_IDEMPOTENCY_PREFIX,
)


def _make_mock_cache(existing_keys: set[str] | None = None):
    """Return an async mock that simulates Redis SET NX behaviour."""
    store: dict[str, str] = {}
    if existing_keys:
        for k in existing_keys:
            store[k] = "1"

    async def _set(key, value=None, nx=False, ex=None):
        if nx and key in store:
            return None  # NX conflict
        store[key] = value
        return True

    async def _delete(key):
        store.pop(key, None)

    mock = AsyncMock()
    mock.set = AsyncMock(side_effect=_set)
    mock.delete = AsyncMock(side_effect=_delete)
    return mock, store


class TestTryClaimChatTurn:
    """try_claim_chat_turn returns True on first claim, False on duplicate."""

    @pytest.mark.asyncio
    async def test_first_claim_succeeds(self):
        mock_cache, store = _make_mock_cache()
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            result = await try_claim_chat_turn("conv-1", "req-1", user_id=1)
        assert result is True
        expected_key = f"{_CHAT_TURN_IDEMPOTENCY_PREFIX}:conv-1:req-1"
        assert expected_key in store

    @pytest.mark.asyncio
    async def test_duplicate_claim_rejected(self):
        existing_key = f"{_CHAT_TURN_IDEMPOTENCY_PREFIX}:conv-1:req-1"
        mock_cache, store = _make_mock_cache(existing_keys={existing_key})
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            result = await try_claim_chat_turn("conv-1", "req-1", user_id=1)
        assert result is False

    @pytest.mark.asyncio
    async def test_different_request_ids_are_independent(self):
        mock_cache, store = _make_mock_cache()
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            first = await try_claim_chat_turn("conv-1", "req-1", user_id=1)
            second = await try_claim_chat_turn("conv-1", "req-2", user_id=1)
        assert first is True
        assert second is True

    @pytest.mark.asyncio
    async def test_different_conversations_are_independent(self):
        mock_cache, store = _make_mock_cache()
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            first = await try_claim_chat_turn("conv-1", "req-1", user_id=1)
            second = await try_claim_chat_turn("conv-2", "req-1", user_id=1)
        assert first is True
        assert second is True

    @pytest.mark.asyncio
    async def test_fail_open_when_redis_unavailable(self):
        """When get_cache_client returns None, the check passes (fail-open)."""
        with patch("app.core.cache.get_cache_client", return_value=None):
            result = await try_claim_chat_turn("conv-1", "req-1", user_id=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_fail_open_on_redis_error(self):
        """When Redis raises an error, the check passes (fail-open)."""
        mock_cache = AsyncMock()
        mock_cache.set = AsyncMock(side_effect=RedisError("connection refused"))
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            result = await try_claim_chat_turn("conv-1", "req-1", user_id=1)
        assert result is True


class TestReleaseChatTurnClaim:
    """release_chat_turn_claim cleans up the Redis key."""

    @pytest.mark.asyncio
    async def test_release_deletes_key(self):
        mock_cache, store = _make_mock_cache()
        key = f"{_CHAT_TURN_IDEMPOTENCY_PREFIX}:conv-1:req-1"
        store[key] = "1"
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            await release_chat_turn_claim("conv-1", "req-1")
        assert key not in store

    @pytest.mark.asyncio
    async def test_release_is_idempotent(self):
        mock_cache, store = _make_mock_cache()
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            await release_chat_turn_claim("conv-1", "req-1")  # no-op, key not in store
        # Should not raise

    @pytest.mark.asyncio
    async def test_release_fail_open_on_redis_error(self):
        mock_cache = AsyncMock()
        mock_cache.delete = AsyncMock(side_effect=RedisError("connection refused"))
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            await release_chat_turn_claim("conv-1", "req-1")  # should not raise


class TestClaimThenReleaseCycle:
    """Full lifecycle: claim → duplicate rejected → release → re-claim succeeds."""

    @pytest.mark.asyncio
    async def test_full_cycle(self):
        mock_cache, store = _make_mock_cache()
        with patch("app.core.cache.get_cache_client", return_value=mock_cache):
            # First claim succeeds
            assert await try_claim_chat_turn("conv-1", "req-1", user_id=1) is True
            # Duplicate rejected
            assert await try_claim_chat_turn("conv-1", "req-1", user_id=1) is False
            # Release
            await release_chat_turn_claim("conv-1", "req-1")
            # Re-claim after release succeeds
            assert await try_claim_chat_turn("conv-1", "req-1", user_id=1) is True

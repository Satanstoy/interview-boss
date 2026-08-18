"""Tests for the fail-open master-bank Redis cache."""

import pytest

from app.core import cache


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def incr(self, key):
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value


@pytest.fixture
def fake_cache(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(cache, "_cache_client", client)
    # 进程级 per-user epoch 缓存会跨测试泄漏，每个测试清空
    monkeypatch.setattr(cache, "_USER_EPOCH_CACHE", {})
    return client


def _user(user_id=7, position_id=2, position="后端开发"):
    return {
        "id": user_id,
        "bank_mode": "mixed",
        "current_position_id": position_id,
        "current_position": position,
    }


@pytest.mark.asyncio
async def test_master_bank_cache_isolated_by_user_and_context(fake_cache):
    response = {"items": [{"id": 1}], "total": 1}
    user = _user()

    await cache.set_master_bank_cache(
        user,
        response,
        sort="frequency_desc",
        page=1,
        page_size=50,
        cat1=None,
        compact=True,
        filter_mode="all",
    )

    cached = await cache.get_master_bank_cache(
        user,
        sort="frequency_desc",
        page=1,
        page_size=50,
        cat1=None,
        compact=True,
        filter_mode="all",
    )
    assert cached == response

    other_user = _user(user_id=8)
    assert (
        await cache.get_master_bank_cache(
            other_user,
            sort="frequency_desc",
            page=1,
            page_size=50,
            cat1=None,
            compact=True,
            filter_mode="all",
        )
        is None
    )


@pytest.mark.asyncio
async def test_master_bank_invalidation_changes_cache_epoch(fake_cache):
    response = {"items": [], "total": 0}
    user = _user()
    kwargs = {
        "sort": "frequency_desc",
        "page": 1,
        "page_size": 50,
        "cat1": None,
        "compact": False,
        "filter_mode": "all",
    }

    await cache.set_master_bank_cache(user, response, **kwargs)
    assert await cache.get_master_bank_cache(user, **kwargs) == response

    await cache.invalidate_master_bank_cache()
    assert await cache.get_master_bank_cache(user, **kwargs) is None



@pytest.mark.asyncio
async def test_master_bank_per_user_invalidation_only_affects_that_user(fake_cache):
    """R16: review/star 只失效本人 master-bank 缓存，不影响其他用户。"""
    kwargs = {
        "sort": "frequency_desc",
        "page": 1,
        "page_size": 50,
        "cat1": None,
        "compact": False,
        "filter_mode": "all",
    }
    user_a = _user(user_id=7)
    user_b = _user(user_id=8)

    resp_a = {"items": [{"id": 1}], "total": 1}
    resp_b = {"items": [{"id": 2}], "total": 1}
    await cache.set_master_bank_cache(user_a, resp_a, **kwargs)
    await cache.set_master_bank_cache(user_b, resp_b, **kwargs)
    assert await cache.get_master_bank_cache(user_a, **kwargs) == resp_a
    assert await cache.get_master_bank_cache(user_b, **kwargs) == resp_b

    # 只失效 user_a（复习/收藏场景）
    await cache.invalidate_master_bank_cache(user_id=user_a["id"])

    assert await cache.get_master_bank_cache(user_a, **kwargs) is None, (
        "user_a 缓存应失效"
    )
    assert await cache.get_master_bank_cache(user_b, **kwargs) == resp_b, (
        "user_b 缓存不应被 user_a 的复习失效连带清掉"
    )



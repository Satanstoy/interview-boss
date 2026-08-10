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

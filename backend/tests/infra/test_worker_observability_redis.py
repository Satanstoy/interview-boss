"""Worker/cron observability status moved to Redis (fail-open).

问题:worker 的 cron 观察记账(`worker_cron_runs`)`与心跳(`worker_heartbeats`)
每次运行写两次 SQLite,与读端共享同一把单写锁,48h 产生 1009 次
`database is locked`。目标:状态记账优先走 Redis,Redis 不可用时回退 SQLite。
"""
import pytest

from app.core import cache


class FakeRedis:
    """与 tests/cache/test_master_bank_cache.py 一致的 async 假客户端。"""

    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, nx=False):
        self.values[key] = value
        return True


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(cache, "_cache_client", client)
    return client


@pytest.mark.asyncio
async def test_worker_status_set_get_roundtrip(fake_redis):
    ok = await cache.worker_status_set("scheduled_compaction_task", "running")
    assert ok is True
    assert (
        await cache.worker_status_get("scheduled_compaction_task") == "running"
    )


@pytest.mark.asyncio
async def test_worker_status_fail_open_without_client(monkeypatch):
    monkeypatch.setattr(cache, "_cache_client", None)
    assert await cache.worker_status_set("x", "running") is False
    assert await cache.worker_status_get("x") is None

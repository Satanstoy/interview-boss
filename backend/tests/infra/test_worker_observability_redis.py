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



# ── Task 2: 心跳 Redis 优先、SQLite 兜底 ────────────────────────────


@pytest.mark.asyncio
async def test_heartbeat_async_writes_redis_only(fake_redis, monkeypatch):
    """Redis 可用时心跳只写 Redis,不碰 SQLite(worker_heartbeats)。"""
    from app import worker as worker_mod

    def _fail_if_called(*a, **k):
        raise AssertionError("Redis 可用时不应写 SQLite 心跳")

    monkeypatch.setattr(worker_mod, "record_worker_heartbeat", _fail_if_called)
    ok = await worker_mod.record_worker_heartbeat_async(
        "arq-worker", status="online", queue_name="arq:default", metadata={"pid": 1}
    )
    assert ok is True
    assert await cache.worker_status_get("arq-worker") == "online"


@pytest.mark.asyncio
async def test_heartbeat_async_falls_back_to_sqlite(monkeypatch):
    """Redis 不可用时回退 SQLite(record_worker_heartbeat 被调用)。"""
    monkeypatch.setattr(cache, "_cache_client", None)
    from app import worker as worker_mod

    calls = {}

    def _spy(*a, **kw):
        calls.update(kw)

    monkeypatch.setattr(worker_mod, "record_worker_heartbeat", _spy)
    ok = await worker_mod.record_worker_heartbeat_async(
        "arq-worker", status="online", queue_name="arq:default"
    )
    assert ok is False
    assert calls.get("status") == "online"




# ── Task 3: cron 记账走 Redis,仅失败/状态变化写 SQLite ─────────────


async def _noop_cron_task(ctx):
    return {"ok": True}


async def _failing_cron_task(ctx):
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_cron_success_marks_redis_and_skips_sqlite_repeat(fake_redis, test_db, monkeypatch):
    """Redis 可用:首次成功写一次 SQLite;连续成功不再写(削减高频成功重写)。"""
    from app import worker as worker_mod

    wrapped = worker_mod.observed_cron_task(_noop_cron_task)
    calls = {"n": 0}
    orig = worker_mod.record_cron_execution

    def spy(*a, **kw):
        calls["n"] += 1
        return orig(*a, **kw)

    monkeypatch.setattr(worker_mod, "record_cron_execution", spy)
    await wrapped({})
    await wrapped({})

    assert calls["n"] == 1  # 仅首次成功落一次 SQLite
    assert await cache.worker_status_get("_noop_cron_task") == "succeeded"


@pytest.mark.asyncio
async def test_cron_failure_still_writes_sqlite(fake_redis, test_db, monkeypatch):
    """失败路径仍写 SQLite 且记录 last_error。"""
    from app import worker as worker_mod

    wrapped = worker_mod.observed_cron_task(_failing_cron_task)
    calls = []
    orig = worker_mod.record_cron_execution

    def spy(*a, **kw):
        calls.append(kw)
        return orig(*a, **kw)

    monkeypatch.setattr(worker_mod, "record_cron_execution", spy)
    with pytest.raises(RuntimeError):
        await wrapped({})

    assert any(c.get("status") == "failed" for c in calls)
    assert any("boom" in (c.get("error") or "") for c in calls)


@pytest.mark.asyncio
async def test_cron_falls_back_to_sqlite_when_redis_down(test_db, monkeypatch):
    """Redis 不可用:维持旧行为(running + succeeded 双写 SQLite)。"""
    monkeypatch.setattr(cache, "_cache_client", None)
    from app import worker as worker_mod

    wrapped = worker_mod.observed_cron_task(_noop_cron_task)
    calls = {"n": 0}
    orig = worker_mod.record_cron_execution

    def spy(*a, **kw):
        calls["n"] += 1
        return orig(*a, **kw)

    monkeypatch.setattr(worker_mod, "record_cron_execution", spy)
    await wrapped({})
    await wrapped({})

    assert calls["n"] == 4  # 2 次运行 × (running + succeeded)


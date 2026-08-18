"""重活任务接入 AdaptiveSemaphore 限流测试(spec M5 / Task 7)。

批量答案生成/题库重建是高频长写源(48h 275+ 次);接入共享信号量控制并发,
降低对 SQLite 单写锁的突发压力。
"""
import asyncio

import pytest

from app.services.backpressure import AdaptiveSemaphore


class FakeSemaphore:
    def __init__(self):
        self.entered = 0
        self.exited = 0
        self.success = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *a):
        self.exited += 1
        return False

    def record_success(self):
        self.success += 1


@pytest.mark.asyncio
async def test_generate_answer_task_acquires_db_semaphore(monkeypatch):
    """generate_answer_task 包装必须经过共享信号量,并记录成功。"""
    from app import worker as worker_mod

    fake = FakeSemaphore()
    monkeypatch.setattr(worker_mod, "_WORKER_DB_SEMAPHORE", fake)
    calls = {"n": 0}

    async def fake_job(ctx, job_id):
        calls["n"] += 1
        return {"status": "completed", "job_id": job_id}

    monkeypatch.setattr(worker_mod, "_generate_answer_job", fake_job)
    res = await worker_mod.generate_answer_task(None, 42)
    assert res == {"status": "completed", "job_id": 42}
    assert fake.entered == 1 and fake.exited == 1
    assert fake.success == 1
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_generate_answer_concurrency_capped(monkeypatch):
    """并发调用时,同一时刻进入临界区的数量不超过信号量上限。"""
    from app import worker as worker_mod

    sem = AdaptiveSemaphore(initial=2, min_concurrency=1)
    monkeypatch.setattr(worker_mod, "_WORKER_DB_SEMAPHORE", sem)
    lock = asyncio.Lock()
    state = {"in_crit": 0, "peak": 0}

    async def fake_job(ctx, job_id):
        async with lock:
            state["in_crit"] += 1
            state["peak"] = max(state["peak"], state["in_crit"])
        await asyncio.sleep(0.02)
        async with lock:
            state["in_crit"] -= 1
        return {"status": "completed", "job_id": job_id}

    monkeypatch.setattr(worker_mod, "_generate_answer_job", fake_job)
    await asyncio.gather(*(worker_mod.generate_answer_task(None, i) for i in range(6)))
    assert state["peak"] <= 2

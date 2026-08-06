import asyncio

"""P3 聚类异步化：后台攒批任务调度与队列流转"""


async def test_run_cluster_batch_immediate_when_pool_large(monkeypatch):
    """pending >= BATCH_SIZE → 立即执行（delay=0）"""
    import app.services.pipeline.queue as q

    monkeypatch.setattr(q, "_cluster_task_running", False)
    monkeypatch.setattr(q, "get_pending_count", lambda: q.BATCH_SIZE)
    monkeypatch.setattr(q, "_recover_stuck_processing", lambda: None)
    monkeypatch.setattr(q, "dequeue_batch", lambda *a, **k: [{"queue_id": 1}])
    called = {"cluster": 0, "done": 0, "failed": 0}

    async def fake_cluster(batch, user_id=None):
        called["cluster"] += 1
        return 3

    def fake_done(ids):
        called["done"] += 1

    def fake_failed(ids):
        called["failed"] += 1

    monkeypatch.setattr("app.services.pipeline.cluster_batch", fake_cluster)
    monkeypatch.setattr("app.services.pipeline.mark_batch_done", fake_done)
    monkeypatch.setattr("app.services.pipeline.mark_batch_failed", fake_failed)
    monkeypatch.setattr(q, "CLUSTER_DELAY_SECONDS", 0)

    scheduled = q._run_cluster_batch_in_background(user_id=1)
    assert scheduled is True
    # 让后台任务跑完
    await asyncio.sleep(0.2)
    assert called["cluster"] == 1
    assert called["done"] == 1
    assert called["failed"] == 0
    # 标志复位
    assert q._cluster_task_running is False


async def test_run_cluster_batch_dedupe_flag(monkeypatch):
    """已有任务在跑 → 不重复调度"""
    import app.services.pipeline.queue as q

    monkeypatch.setattr(q, "_cluster_task_running", True)
    scheduled = q._run_cluster_batch_in_background(user_id=1)
    assert scheduled is False


async def test_run_cluster_batch_failure_marks_failed(monkeypatch):
    """聚类失败 → mark_batch_failed（队列回滚 pending，下次提交/worker 补处理）"""
    import app.services.pipeline.queue as q

    monkeypatch.setattr(q, "_cluster_task_running", False)
    monkeypatch.setattr(q, "get_pending_count", lambda: q.BATCH_SIZE)
    monkeypatch.setattr(q, "_recover_stuck_processing", lambda: None)
    monkeypatch.setattr(q, "dequeue_batch", lambda *a, **k: [{"queue_id": 1}])
    called = {"failed": 0}

    async def broken_cluster(batch, user_id=None):
        raise RuntimeError("llm down")

    def fake_failed(ids):
        called["failed"] += 1

    monkeypatch.setattr("app.services.pipeline.cluster_batch", broken_cluster)
    monkeypatch.setattr("app.services.pipeline.mark_batch_failed", fake_failed)
    monkeypatch.setattr(q, "CLUSTER_DELAY_SECONDS", 0)

    q._run_cluster_batch_in_background(user_id=1)
    await asyncio.sleep(0.2)
    assert called["failed"] == 1
    assert q._cluster_task_running is False

"""Eval Queue 与普通用户任务队列隔离契约。"""

import asyncio
import importlib

import pytest


def _queue_module():
    try:
        return importlib.import_module("app.evaluation.queue")
    except ModuleNotFoundError:
        pytest.fail("app.evaluation.queue 尚未实现")


def _worker_module():
    try:
        return importlib.import_module("app.eval_worker")
    except ModuleNotFoundError:
        pytest.fail("app.eval_worker 尚未实现")


def test_enqueue_eval_run_uses_dedicated_queue(monkeypatch):
    queue = _queue_module()
    calls = []

    class FakePool:
        async def enqueue_job(self, *args, **kwargs):
            calls.append((args, kwargs))
            return "queued"

        async def close(self):
            calls.append(("close", {}))

    async def fake_pool():
        return FakePool()

    monkeypatch.setattr(queue, "_get_eval_redis_pool", fake_pool)
    result = asyncio.run(queue.enqueue_eval_run_job(42))

    assert result == "queued"
    assert calls[0] == (
        ("eval_run_task", 42),
        {"_queue_name": queue.EVAL_QUEUE_NAME, "_job_id": "eval-run-42"},
    )
    assert calls[-1] == ("close", {})


def test_eval_worker_has_low_concurrency_and_separate_queue():
    queue = _queue_module()
    worker = _worker_module()
    settings = worker.EvalWorkerSettings

    assert settings.queue_name == queue.EVAL_QUEUE_NAME
    assert settings.max_jobs == 1
    assert settings.queue_read_limit == 1
    assert settings.max_tries == 3
    assert settings.job_timeout >= 6 * 60 * 60
    assert worker.eval_run_task in settings.functions


def test_eval_worker_reconciles_cancelled_run(monkeypatch):
    worker = _worker_module()
    calls = []

    async def cancelled_run(run_id):
        raise asyncio.CancelledError

    def reconcile(run_id, *, reason):
        calls.append((run_id, reason))
        return {"run_id": run_id, "status": "failed"}

    def heartbeat(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(
        "app.services.evaluation_executor.execute_eval_run", cancelled_run
    )
    monkeypatch.setattr(
        "app.services.evaluation_executor.reconcile_interrupted_eval_run",
        reconcile,
    )
    monkeypatch.setattr("app.worker.record_worker_heartbeat", heartbeat)

    result = asyncio.run(worker.eval_run_task({}, 99))

    assert result == {"run_id": 99, "status": "failed"}
    assert calls[0] == (99, "worker_cancelled")

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
    assert worker.eval_run_task in settings.functions

"""Disposable real-stack failure injection used by AC-029 only."""

from __future__ import annotations

import pytest


class MemoryRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, *, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True


@pytest.mark.asyncio
async def test_public_failure_gate_is_one_shot_and_survives_worker_restart(monkeypatch):
    from app.worker_cluster_tasks import maybe_inject_e2e_public_failure

    monkeypatch.setenv("E2E_STUB_PROVIDER", "1")
    redis = MemoryRedis()
    ctx = {"redis": redis}
    batch = [{
        "queue_id": 81,
        "qd_id": 404,
        "question": "AC029_FAIL_PUBLIC_ORDINAL_40: 分布式锁如何避免误释放？",
        "owner_id": None,
        "contribution_request_id": 99,
    }]

    with pytest.raises(RuntimeError, match="AC029_PUBLIC_ITEM_FAILURE"):
        await maybe_inject_e2e_public_failure(ctx, batch, root_import_id="imp-ac029")

    # ARQ worker process restart creates a new context, while isolated Redis
    # keeps the one-shot marker so a later explicit retry can proceed.
    restarted_ctx = {"redis": redis}
    await maybe_inject_e2e_public_failure(restarted_ctx, batch, root_import_id="imp-ac029")
    assert len(redis.values) == 1


@pytest.mark.asyncio
async def test_public_failure_gate_ignores_private_or_unmarked_work(monkeypatch):
    from app.worker_cluster_tasks import maybe_inject_e2e_public_failure

    monkeypatch.setenv("E2E_STUB_PROVIDER", "1")
    redis = MemoryRedis()
    await maybe_inject_e2e_public_failure(
        {"redis": redis},
        [{"question": "private question", "owner_id": 101, "contribution_request_id": 99}],
        root_import_id="imp-ac029",
    )
    await maybe_inject_e2e_public_failure(
        {"redis": redis},
        [{"question": "public question", "owner_id": None, "contribution_request_id": None}],
        root_import_id="imp-ac029",
    )
    assert redis.values == {}

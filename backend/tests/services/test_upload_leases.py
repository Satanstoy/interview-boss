"""AC-012 / UR-012：job 租约代次（fencing）与业务写入保护。

契约（contracts.md §2.2）：

- claim 原子递增 ``lease_generation``，本次领取的 fence 就是该代次；
- 回收看 ``locked_until``，不用 ``created_at``：刚被领取的任务不能立刻被回收；
- 旧代次的 worker 提交业务数据必须被拒绝（业务写入前检查 fence）；
- 心跳只对当前代次续租。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.job_lifecycle import (
    JobFenceError,
    assert_job_fence,
    claim_job_with_generation,
    heartbeat_job,
    reclaim_expired_leases,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k1', 'h1', 'private', 'interview', 'v1')"
    )
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key) "
        "VALUES ('submit_import', 'pending', 101, 'imp-1', 'extract:document:v1')"
    )
    conn.commit()
    return conn


def _job_id(conn) -> int:
    return conn.execute("SELECT id FROM jobs").fetchone()[0]


def test_claim_increments_generation_and_locks():
    conn = _db()
    job_id = _job_id(conn)
    claimed = claim_job_with_generation(conn, job_id, worker_id="w1")
    assert claimed is not None
    assert claimed["lease_generation"] == 1
    assert claimed["status"] == "running"
    assert claimed["locked_until"] is not None
    assert claimed["worker_id"] == "w1"
    # 同一 job 不能被第二个 worker 领取
    assert claim_job_with_generation(conn, job_id, worker_id="w2") is None
    conn.close()


def test_expired_lease_reclaim_gets_new_generation():
    conn = _db()
    job_id = _job_id(conn)
    first = claim_job_with_generation(conn, job_id, worker_id="w1")
    # 模拟租约过期（回拨 locked_until）
    conn.execute(
        "UPDATE jobs SET locked_until = datetime('now','-10 seconds') WHERE id = ?",
        (job_id,),
    )
    reclaimed = reclaim_expired_leases(conn, job_type="submit_import")
    assert reclaimed == 1
    second = claim_job_with_generation(conn, job_id, worker_id="w2")
    assert second is not None
    assert second["lease_generation"] > first["lease_generation"]
    conn.close()


def test_recently_claimed_job_is_not_recycled_immediately():
    conn = _db()
    job_id = _job_id(conn)
    # 队列行创建于 1 小时前，但刚被领取（locked_until 在未来）
    conn.execute(
        "UPDATE jobs SET created_at = datetime('now','-60 minutes') WHERE id = ?",
        (job_id,),
    )
    claim_job_with_generation(conn, job_id, worker_id="w1")
    assert reclaim_expired_leases(conn, job_type="submit_import") == 0
    row = conn.execute("SELECT status, worker_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["status"] == "running"
    assert row["worker_id"] == "w1"
    conn.close()


def test_old_generation_business_write_is_rejected():
    conn = _db()
    job_id = _job_id(conn)
    stale = claim_job_with_generation(conn, job_id, worker_id="w1")
    # 租约过期后被另一 worker 接管
    conn.execute(
        "UPDATE jobs SET locked_until = datetime('now','-10 seconds') WHERE id = ?",
        (job_id,),
    )
    reclaim_expired_leases(conn, job_type="submit_import")
    current = claim_job_with_generation(conn, job_id, worker_id="w2")
    assert current["lease_generation"] > stale["lease_generation"]

    # 旧 worker 提交业务数据：必须拒绝，业务表不留痕
    with pytest.raises(JobFenceError):
        assert_job_fence(conn, job_id, stale["lease_generation"])
    assert conn.execute("SELECT COUNT(*) FROM questions_detail").fetchone()[0] == 0

    # 当前代次可以提交
    assert_job_fence(conn, job_id, current["lease_generation"])
    conn.close()


def test_heartbeat_only_extends_current_generation():
    conn = _db()
    job_id = _job_id(conn)
    claimed = claim_job_with_generation(conn, job_id, worker_id="w1")
    before = conn.execute("SELECT locked_until FROM jobs WHERE id = ?", (job_id,)).fetchone()[
        "locked_until"
    ]
    assert heartbeat_job(conn, job_id, claimed["lease_generation"]) is True
    after = conn.execute("SELECT locked_until FROM jobs WHERE id = ?", (job_id,)).fetchone()[
        "locked_until"
    ]
    assert after >= before

    # 旧代次心跳无效
    assert heartbeat_job(conn, job_id, claimed["lease_generation"] + 5) is False
    conn.close()


def test_v2_jobs_must_provide_generation_on_business_commit():
    """v2 业务提交必须显式传 generation；不传视为编程错误。"""

    conn = _db()
    job_id = _job_id(conn)
    claimed = claim_job_with_generation(conn, job_id, worker_id="w1")
    with pytest.raises(TypeError):
        assert_job_fence(conn, job_id)  # 缺 generation
    assert_job_fence(conn, job_id, claimed["lease_generation"])
    conn.close()

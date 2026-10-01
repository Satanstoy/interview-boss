"""AC-012 / UR-012：job 租约代次（fencing）与业务写入保护。

契约（contracts.md §2.2）：

- claim 原子递增 ``lease_generation``，本次领取的 fence 就是该代次；
- 回收看 ``locked_until``，不用 ``created_at``：刚被领取的任务不能立刻被回收；
- 旧代次的 worker 提交业务数据必须被拒绝（业务写入前检查 fence）；
- 心跳只对当前代次续租。
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.migrations import run_migrations
from app.services.job_lifecycle import (
    JobFenceError,
    assert_job_fence,
    claim_job_with_generation,
    complete_job,
    fail_job,
    heartbeat_job,
    reclaim_expired_leases,
)
from app.services.upload_scope_leases import (
    UploadScopeLeaseError,
    acquire_upload_scope_lease,
    assert_upload_scope_lease,
    heartbeat_upload_scope_lease,
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


def test_upload_scope_lease_serializes_shared_pool_and_fences_stale_holder():
    conn = _db()
    first = acquire_upload_scope_lease(
        conn, "1:public", holder_token="worker-a:job-1:1", lease_seconds=120
    )
    assert first is not None
    assert first["generation"] == 1
    assert acquire_upload_scope_lease(
        conn, "1:public", holder_token="worker-b:job-2:1", lease_seconds=120
    ) is None

    assert heartbeat_upload_scope_lease(
        conn,
        "1:public",
        holder_token="worker-a:job-1:1",
        generation=first["generation"],
        lease_seconds=120,
    )
    assert_upload_scope_lease(
        conn,
        "1:public",
        holder_token="worker-a:job-1:1",
        generation=first["generation"],
    )

    conn.execute(
        "UPDATE upload_scope_leases SET locked_until = datetime('now','-1 second') "
        "WHERE scope_key = '1:public'"
    )
    second = acquire_upload_scope_lease(
        conn, "1:public", holder_token="worker-b:job-2:1", lease_seconds=120
    )
    assert second is not None
    assert second["generation"] > first["generation"]
    with pytest.raises(UploadScopeLeaseError):
        assert_upload_scope_lease(
            conn,
            "1:public",
            holder_token="worker-a:job-1:1",
            generation=first["generation"],
        )
    conn.close()


def test_root_cluster_recovery_only_requeues_its_own_queue_rows(monkeypatch):
    import app.services.pipeline.queue as queue_module

    conn = _db()
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-2', 101, 'k2', 'h2', 'private', 'interview', 'v1')"
    )
    conn.execute("INSERT INTO job_positions (name) VALUES ('后端')")
    details = []
    for index, import_id in enumerate(("imp-1", "imp-2"), start=1):
        interview_id = conn.execute(
            "INSERT INTO interview (url, owner_id, status, job_position) "
            "VALUES (?, 101, 'approved', '后端')",
            (f"https://example.test/recovery-{index}",),
        ).lastrowid
        detail_id = conn.execute(
            "INSERT INTO questions_detail (interview_id, question, owner_id, job_position, import_id) "
            "VALUES (?, ?, 101, '后端', ?)",
            (interview_id, f"root recovery {index}", import_id),
        ).lastrowid
        queue_id = conn.execute(
            "INSERT INTO analysis_queue (interview_id, question_detail_id, status, owner_id, "
            "root_import_id, locked_until) VALUES (?, ?, 'processing', 101, ?, "
            "datetime('now','-1 second'))",
            (interview_id, detail_id, import_id),
        ).lastrowid
        conn.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
            "pipeline_version, status) VALUES (?, 'resolve', ?, 1, 'upload-pipeline-v1', 'running')",
            (import_id, f"detail:{detail_id}"),
        )
        details.append((int(queue_id), str(import_id)))
    job_id = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key) "
        "VALUES ('cluster_batch', 'pending', 101, 'imp-1', 'cluster:root:v1')"
    ).lastrowid
    claimed = claim_job_with_generation(conn, job_id, worker_id="root-worker")
    conn.commit()
    monkeypatch.setattr(queue_module, "get_db_connection", lambda: conn)

    queue_module._recover_stuck_processing(
        job_fence=(int(job_id), int(claimed["lease_generation"])),
        root_import_id="imp-1",
    )

    statuses = {
        root_id: conn.execute(
            "SELECT status FROM analysis_queue WHERE id = ?", (queue_id,)
        ).fetchone()["status"]
        for queue_id, root_id in details
    }
    assert statuses == {"imp-1": "pending", "imp-2": "processing"}
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


def test_current_generation_with_expired_lease_cannot_commit():
    conn = _db()
    job_id = _job_id(conn)
    claimed = claim_job_with_generation(conn, job_id, worker_id="w1")
    conn.execute(
        "UPDATE jobs SET locked_until = datetime('now','-1 second') WHERE id = ?",
        (job_id,),
    )

    with pytest.raises(JobFenceError):
        assert_job_fence(conn, job_id, claimed["lease_generation"])
    conn.close()


def test_stale_generation_cannot_complete_or_fail_reclaimed_job():
    conn = _db()
    job_id = _job_id(conn)
    stale = claim_job_with_generation(conn, job_id, worker_id="w1")
    conn.execute(
        "UPDATE jobs SET locked_until = datetime('now','-1 second') WHERE id = ?",
        (job_id,),
    )
    reclaim_expired_leases(conn, job_type="submit_import")
    current = claim_job_with_generation(conn, job_id, worker_id="w2")

    assert not complete_job(
        conn,
        job_id,
        "w1",
        result="stale",
        lease_generation=stale["lease_generation"],
    )
    stale_failure = fail_job(
        conn,
        job_id,
        "w1",
        "stale",
        lease_generation=stale["lease_generation"],
    )
    assert stale_failure["status"] == "stale"
    row = conn.execute(
        "SELECT status, worker_id, lease_generation FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    assert (row["status"], row["worker_id"], row["lease_generation"]) == (
        "running",
        "w2",
        current["lease_generation"],
    )
    conn.close()


def test_expired_generation_cannot_complete_or_fail_job():
    conn = _db()
    job_id = _job_id(conn)
    claimed = claim_job_with_generation(conn, job_id, worker_id="w-expired")
    conn.execute(
        "UPDATE jobs SET locked_until = datetime('now','-1 second') WHERE id = ?",
        (job_id,),
    )

    assert not heartbeat_job(conn, job_id, claimed["lease_generation"])
    assert not complete_job(
        conn,
        job_id,
        "w-expired",
        result="too late",
        lease_generation=claimed["lease_generation"],
    )
    outcome = fail_job(
        conn,
        job_id,
        "w-expired",
        "too late",
        lease_generation=claimed["lease_generation"],
    )
    assert outcome["status"] == "stale"
    row = conn.execute(
        "SELECT status, worker_id FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    assert (row["status"], row["worker_id"]) == ("running", "w-expired")
    conn.close()


@pytest.mark.asyncio
async def test_cluster_canonical_write_is_fenced_after_model_work(monkeypatch):
    import app.db.connection as db_connection
    import app.db.operations as db_operations
    import app.services.pipeline.batch as batch_module

    conn = _db()
    conn.execute("INSERT INTO job_positions (name) VALUES ('后端')")
    interview_cursor = conn.execute(
        "INSERT INTO interview (url, company, round, owner_id, status, job_position) "
        "VALUES ('https://example.test/fence', '', '', 101, 'approved', '后端')"
    )
    interview_id = int(interview_cursor.lastrowid)
    detail_cursor = conn.execute(
        "INSERT INTO questions_detail (interview_id, question, cat1, cat2, tags, "
        "url, owner_id, job_position) VALUES (?, 'stale cluster question', '数据库', "
        "'Redis', 'persistence', 'https://example.test/fence', 101, '后端')",
        (interview_id,),
    )
    detail_id = int(detail_cursor.lastrowid)
    job_cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key) "
        "VALUES ('cluster_batch', 'pending', 101, 'imp-1', 'cluster:root:v1')"
    )
    job_id = int(job_cursor.lastrowid)
    stale = claim_job_with_generation(conn, job_id, worker_id="cluster-w1")
    conn.commit()

    monkeypatch.setattr(batch_module, "get_db_connection", lambda: conn)
    monkeypatch.setattr(db_operations, "get_db_connection", lambda: conn)

    async def run_db(function):
        return function()

    monkeypatch.setattr(db_connection, "run_db", run_db)
    monkeypatch.setattr(
        batch_module,
        "sanitize_batch",
        lambda rows: (rows, []),
    )
    monkeypatch.setattr(
        batch_module,
        "_load_existing_clusters_by_cat2",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(batch_module, "get_index_manager", lambda: MagicMock())

    async def model_work_then_lose_lease(*_args, **_kwargs):
        conn.execute(
            "UPDATE jobs SET lease_generation = lease_generation + 1 WHERE id = ?",
            (job_id,),
        )
        conn.commit()
        return {
            "matched_to_existing": [],
            "new_clusters": [
                {
                    "ids": [str(detail_id)],
                    "representative": "stale cluster question",
                    "items": [{"id": detail_id, "question": "stale cluster question"}],
                }
            ],
        }

    process_mock = AsyncMock(side_effect=model_work_then_lose_lease)
    monkeypatch.setattr(batch_module, "process_incremental_batch", process_mock)
    tracked_batch = [
        {
            "queue_id": 1,
            "qd_id": detail_id,
            "question": "stale cluster question",
            "cat1": "数据库",
            "cat2": "Redis",
            "tags": "persistence",
            "diff_tag": "L2-中等",
            "url": "https://example.test/fence",
            "company": "",
            "round": "",
            "job_position": "后端",
            "owner_id": 101,
            "interview_id": interview_id,
            "root_import_id": "imp-1",
        }
    ]

    with pytest.raises(JobFenceError):
        await batch_module.cluster_batch(
            tracked_batch,
            user_id=101,
            return_new_ids=True,
            job_fence=(job_id, int(stale["lease_generation"])),
        )

    assert process_mock.await_count == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM question_bank WHERE question = 'stale cluster question'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM question_resolutions WHERE detail_id = ?",
        (detail_id,),
    ).fetchone()[0] == 0
    conn.close()


@pytest.mark.asyncio
async def test_cluster_scope_write_is_fenced_after_model_work(monkeypatch):
    import app.db.connection as db_connection
    import app.db.operations as db_operations
    import app.services.pipeline.batch as batch_module

    conn = _db()
    conn.execute("INSERT INTO job_positions (name) VALUES ('后端')")
    interview_cursor = conn.execute(
        "INSERT INTO interview (url, company, round, owner_id, status, job_position) "
        "VALUES ('https://example.test/scope-fence', '', '', NULL, 'approved', '后端')"
    )
    interview_id = int(interview_cursor.lastrowid)
    detail_cursor = conn.execute(
        "INSERT INTO questions_detail (interview_id, question, cat1, cat2, tags, "
        "url, owner_id, job_position) VALUES (?, 'stale scope question', '数据库', "
        "'Redis', 'persistence', 'https://example.test/scope-fence', NULL, '后端')",
        (interview_id,),
    )
    detail_id = int(detail_cursor.lastrowid)
    job_cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key) "
        "VALUES ('cluster_batch', 'pending', 101, 'imp-1', 'cluster:scope:v1')"
    )
    job_id = int(job_cursor.lastrowid)
    claimed = claim_job_with_generation(conn, job_id, worker_id="scope-w1")
    scope = acquire_upload_scope_lease(
        conn, "1:public", holder_token=f"scope-w1:{job_id}:{claimed['lease_generation']}"
    )
    conn.commit()

    monkeypatch.setattr(batch_module, "get_db_connection", lambda: conn)
    monkeypatch.setattr(db_operations, "get_db_connection", lambda: conn)

    async def run_db(function):
        return function()

    monkeypatch.setattr(db_connection, "run_db", run_db)
    monkeypatch.setattr(batch_module, "sanitize_batch", lambda rows: (rows, []))
    monkeypatch.setattr(
        batch_module, "_load_existing_clusters_by_cat2", AsyncMock(return_value={})
    )
    monkeypatch.setattr(batch_module, "get_index_manager", lambda: MagicMock())

    async def model_work_then_lose_scope(*_args, **_kwargs):
        conn.execute(
            "UPDATE upload_scope_leases SET generation = generation + 1 "
            "WHERE scope_key = '1:public'"
        )
        conn.commit()
        return {
            "matched_to_existing": [],
            "new_clusters": [
                {
                    "ids": [str(detail_id)],
                    "representative": "stale scope question",
                    "items": [{"id": detail_id, "question": "stale scope question"}],
                }
            ],
        }

    process_mock = AsyncMock(side_effect=model_work_then_lose_scope)
    monkeypatch.setattr(batch_module, "process_incremental_batch", process_mock)
    tracked_batch = [
        {
            "queue_id": 1,
            "qd_id": detail_id,
            "question": "stale scope question",
            "cat1": "数据库",
            "cat2": "Redis",
            "tags": "persistence",
            "diff_tag": "L2-中等",
            "url": "https://example.test/scope-fence",
            "company": "",
            "round": "",
            "job_position": "后端",
            "owner_id": None,
            "interview_id": interview_id,
            "root_import_id": "imp-1",
        }
    ]

    with pytest.raises(UploadScopeLeaseError):
        await batch_module.cluster_batch(
            tracked_batch,
            return_new_ids=True,
            job_fence=(job_id, int(claimed["lease_generation"])),
            scope_fence=(
                "1:public",
                f"scope-w1:{job_id}:{claimed['lease_generation']}",
                int(scope["generation"]),
            ),
        )

    assert process_mock.await_count == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM question_bank WHERE question = 'stale scope question'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM question_resolutions WHERE detail_id = ?", (detail_id,)
    ).fetchone()[0] == 0
    conn.close()


@pytest.mark.asyncio
async def test_answer_write_is_fenced_after_model_work(monkeypatch):
    import app.db.connection as db_connection
    import app.services.submit_service as submit_service
    import app.services.answer_enrichment as answer_enrichment
    import app.services.llm as llm

    conn = _db()
    question_cursor = conn.execute(
        "INSERT INTO question_bank (question, cat1, cat2, owner_id, status, job_position) "
        "VALUES ('answer fence question', '数据库', 'Redis', 101, 'approved', '后端')"
    )
    question_id = int(question_cursor.lastrowid)
    answer_job_cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key) "
        "VALUES ('generate_answer', 'pending', 101, 'imp-1', 'answer:1:v1')"
    )
    answer_job_id = int(answer_job_cursor.lastrowid)
    stale = claim_job_with_generation(conn, answer_job_id, worker_id="answer-w1")
    conn.commit()

    monkeypatch.setattr(db_connection, "get_db_connection", lambda: conn)
    monkeypatch.setattr(submit_service, "get_db_connection", lambda: conn)

    async def run_db(function):
        return function()

    monkeypatch.setattr(db_connection, "run_db", run_db)
    monkeypatch.setattr(submit_service, "run_db", run_db)
    monkeypatch.setattr(
        answer_enrichment,
        "prepare_answer_prompt",
        AsyncMock(return_value=("prompt", [])),
    )
    monkeypatch.setattr(
        answer_enrichment,
        "refine_answer",
        AsyncMock(side_effect=lambda _p, answer, *_a, **_kw: (answer, [])),
    )

    async def model_work_then_lose_lease(*_args, **_kwargs):
        conn.execute(
            "UPDATE jobs SET lease_generation = lease_generation + 1 WHERE id = ?",
            (answer_job_id,),
        )
        conn.commit()
        return "a sufficiently complete answer"

    monkeypatch.setattr(
        llm, "_call_llm_with_retry", AsyncMock(side_effect=model_work_then_lose_lease)
    )

    with pytest.raises(JobFenceError):
        await submit_service.background_generate_answer(
            question_id,
            "answer fence question",
            101,
            raise_on_error=True,
            job_fence=(answer_job_id, int(stale["lease_generation"])),
        )

    answer = conn.execute(
        "SELECT ai_answer FROM question_bank WHERE id = ?", (question_id,)
    ).fetchone()["ai_answer"]
    assert answer is None
    conn.close()

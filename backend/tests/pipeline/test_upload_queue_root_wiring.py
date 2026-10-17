"""R06/AC-007：真实入队写 root；对账补单发出可执行 job（非孤儿类型）。"""

from __future__ import annotations

import sqlite3

from app.db.migrations import run_migrations
from app.services.pipeline.queue import enqueue_questions
from app.services.upload_queue import (
    ensure_bucket_job,
    reconcile_pending_buckets,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k-1', 'h-1', 'private', 'interview', 'upload-pipeline-v1')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (1, 'internal://a', 101, 'approved', '后端开发')"
    )
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, owner_id, "
        "import_id, source_ordinal) "
        "VALUES (11, 1, '解释 TCP 三次握手', '网络', 'tcp', 101, 'imp-1', 1), "
        "       (12, 1, 'Redis 持久化机制', '数据库', 'Redis', 101, 'imp-1', 2)"
    )
    conn.commit()
    return conn


def test_enqueue_propagates_root_from_detail_import_id():
    """R06：明细带 import_id 时，入队自动回填 root（真实上传队列行有归属）。"""

    conn = _db()
    enqueue_questions(1, owner_id=101, conn=conn)
    rows = conn.execute(
        "SELECT root_import_id, question_detail_id FROM analysis_queue WHERE status='pending'"
    ).fetchall()
    assert len(rows) == 2
    assert {r["root_import_id"] for r in rows} == {"imp-1"}
    stages = conn.execute(
        "SELECT unit_key, status FROM upload_stage_results "
        "WHERE import_id = 'imp-1' AND stage = 'resolve' ORDER BY unit_key"
    ).fetchall()
    assert [(row["unit_key"], row["status"]) for row in stages] == [
        ("detail:11", "pending"),
        ("detail:12", "pending"),
    ]
    conn.close()


def test_cluster_queue_lease_updates_and_releases_root_checkpoint():
    """The checkpoint follows the durable queue lease across retryable failures."""

    import app.services.pipeline.queue as queue

    conn = _db()
    enqueue_questions(1, owner_id=101, conn=conn, question_detail_ids=[11])
    original_get_db_connection = queue.get_db_connection
    queue.get_db_connection = lambda: conn
    try:
        batch = queue.dequeue_batch(1, owner_id=101, root_import_id="imp-1")

        assert len(batch) == 1
        assert batch[0]["root_import_id"] == "imp-1"
        stage = conn.execute(
            "SELECT status FROM upload_stage_results WHERE import_id = 'imp-1' "
            "AND stage = 'resolve' AND unit_key = 'detail:11'"
        ).fetchone()
        assert stage["status"] == "running"

        queue.mark_batch_failed([batch[0]["queue_id"]])
        stage = conn.execute(
            "SELECT status FROM upload_stage_results WHERE import_id = 'imp-1' "
            "AND stage = 'resolve' AND unit_key = 'detail:11'"
        ).fetchone()
        queue_row = conn.execute(
            "SELECT status, locked_until FROM analysis_queue WHERE id = ?",
            (batch[0]["queue_id"],),
        ).fetchone()
        assert stage["status"] == "pending"
        assert queue_row["status"] == "pending"
        assert queue_row["locked_until"] is None
    finally:
        queue.get_db_connection = original_get_db_connection
        conn.close()


def test_ensure_bucket_job_emits_dispatchable_type():
    """R06：对账补单 job 必须用已注册/可执行类型（cluster_batch），不再用孤儿 analysis_batch。"""

    conn = _db()
    enqueue_questions(1, owner_id=101, conn=conn)
    bucket = {
        "root_import_id": "imp-1",
        "owner_id": 101,
        "job_position": "后端开发",
        "scope_key": "imp-1:user:101:后端开发",
        "work_key": "cluster:imp-1:user:101:后端开发:v1",
        "pending_count": 2,
        "available_at": "2026-09-30 00:00:00",
    }
    result = ensure_bucket_job(conn, bucket=bucket, created_by=101)
    conn.commit()
    assert result["created"] is True
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (result["job_id"],)).fetchone()
    assert job["job_type"] == "cluster_batch", (
        "补单 job 必须用已注册的 cluster_batch 类型"
    )
    assert job["root_import_id"] == "imp-1"
    assert job["work_key"] == bucket["work_key"]
    # 幂等：再补不重复
    again = ensure_bucket_job(conn, bucket=bucket, created_by=101)
    conn.commit()
    assert again["created"] is False
    assert again["job_id"] == result["job_id"]
    conn.close()


def test_reconcile_creates_job_for_real_upload_queue():
    """R06：真实上传产生的队列能被对账补单（collect 不再被 root=null 漏掉）。"""

    conn = _db()
    enqueue_questions(1, owner_id=101, conn=conn)
    report = reconcile_pending_buckets(conn, created_by=101)
    conn.commit()
    assert report["buckets"] == 1
    assert report["jobs_created"] == 1
    job = conn.execute(
        "SELECT job_type, root_import_id FROM jobs "
        "WHERE job_type = 'cluster_batch'"
    ).fetchone()
    assert job is not None
    assert job["root_import_id"] == "imp-1"
    conn.close()

def test_stuck_processing_recovered_by_locked_until_not_created_at():
    """contracts §2.5：analysis_queue 超时回收必须按 locked_until，
    不能用 created_at（dequeue 时写租约，避免误伤新增/运行中的行）。"""

    import app.services.pipeline.queue as q

    conn = _db()
    # 两行任务：一行 40 分钟前标 processing + 有过期租约；一行 2 分钟前
    # 标 processing + 未过期租约
    # 9001：created_at 超时且租约过期 → 回收；
    # 9002：created_at 超时但 locked_until 仍有效 → 必须保留
    #（决定性反例：按 created_at 会误回收 9002，只有 locked_until 语义正确）。
    conn.execute(
        "INSERT INTO analysis_queue (id, interview_id, question_detail_id, owner_id, "
        "status, created_at, locked_until) VALUES "
        "(9001, 1, 11, 101, 'processing', datetime('now','-40 minutes'), datetime('now','-5 minutes')), "
        "(9002, 1, 12, 101, 'processing', datetime('now','-40 minutes'), datetime('now','+25 minutes'))"
    )
    conn.commit()

    # sweep queue 模块的连接到连接本测试库
    def _test_get_db_connection():
        return conn

    async def _sync_run_db(func):
        return func()

    import sys as _sys
    patched = []
    for _mn, _md in list(_sys.modules.items()):
        if _mn.startswith("app.") and _md is not None:
            if hasattr(_md, "get_db_connection"):
                patched.append((_md, _md.get_db_connection))
                _md.get_db_connection = _test_get_db_connection
    try:
        q._recover_stuck_processing()
    finally:
        for _md, _orig in patched:
            _md.get_db_connection = _orig

    rows = {
        r["id"]: r["status"]
        for r in conn.execute("SELECT id, status FROM analysis_queue").fetchall()
    }
    assert rows[9001] == "pending", "过期租约（locked_until 超时）必须回收"
    assert rows[9002] == "processing", (
        "未过期租约不得被 created_at 误伤（created_at 早但租约仍有效）"
    )
    conn.close()

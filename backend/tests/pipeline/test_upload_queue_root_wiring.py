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
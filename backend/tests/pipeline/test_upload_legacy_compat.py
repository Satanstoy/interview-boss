"""AC-024 / AC-025：JD 与旧数据兼容、源状态变化检查。

契约（contracts §5、§4.5）：

- JD 走同一任务外壳但不进题目聚类阶段（显式 skip）；
- 无新发布元数据的旧 approved 公共数据保持可见；
- 旧 job 重试先解析到同一根任务，不重复执行；
- 原文删除后恢复 → ``SOURCE_DELETED``，不复活已删内容；恢复不重置已成功阶段。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_lifecycle import UploadRestoreError, accept_upload, restore_upload
from app.services.upload_repository import save_stage_result


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.commit()
    return conn


def _loaders():
    return {
        "user": lambda uid: {
            "api_key": "k",
            "base_url": "https://u.example.com/v1",
            "model": "m",
            "timeout": 60,
        },
        "global": lambda: {
            "api_key": "k",
            "base_url": "https://s.example.com/v1",
            "model": "m",
            "timeout": 60,
        },
    }


def _accept(conn, **overrides):
    params = dict(
        actor_id=101,
        actor_is_admin=False,
        idempotency_key="k1",
        target_intent="private",
        source_type="interview",
        text="面经：TCP 三次握手",
        url="",
        season="",
        content_type="",
        position_id=1,
        position_name="后端",
        files=[],
        images=[],
        entry="api",
        credential_loaders=_loaders(),
    )
    params.update(overrides)
    return accept_upload(conn, **params)


def test_jd_upload_skips_question_pipeline_work():
    conn = _db()
    result = _accept(conn, source_type="jd", text="岗位：后端工程师，要求熟悉 MySQL")
    assert result["created"] is True
    # JD 不建聚类/答案工作
    assert conn.execute("SELECT COUNT(*) FROM analysis_queue").fetchone()[0] == 0
    row = conn.execute("SELECT source_type FROM upload_imports").fetchone()
    assert row["source_type"] == "jd"
    conn.close()


def test_legacy_public_questions_without_resolution_stay_visible():
    conn = _db()
    # 旧公共题：没有 question_resolutions、没有发布元数据
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, owner_id, status, frequency, sources, original_questions) "
        "VALUES (5, '旧公共题', 'a', 'b', NULL, 'approved', 1, '[]', '[]')"
    )
    conn.commit()
    visible = conn.execute(
        "SELECT COUNT(*) FROM question_bank WHERE id = 5 AND owner_id IS NULL "
        "AND status = 'approved' AND deleted_at IS NULL"
    ).fetchone()[0]
    assert visible == 1
    # 没有 resolution 也不影响可见性
    assert (
        conn.execute("SELECT COUNT(*) FROM question_resolutions WHERE canonical_id = 5").fetchone()[
            0
        ]
        == 0
    )
    conn.close()


def test_legacy_job_retry_resolves_root_and_is_idempotent():
    conn = _db()
    created = _accept(conn)
    root_job_id = created["job_id"]
    # 模拟旧链：A(root) → B → C
    b = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, parent_job_id, work_key) "
        "VALUES ('submit_import', 'failed', 101, ?, ?, 'classify:document:v1')",
        (created["import_id"], root_job_id),
    ).lastrowid
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, parent_job_id, work_key) "
        "VALUES ('submit_import', 'running', 101, ?, ?, 'persist:document:v1')",
        (created["import_id"], b),
    )
    conn.commit()

    first = restore_upload(conn, actor_id=101, job_id=b)
    second = restore_upload(conn, actor_id=101, job_id=root_job_id)
    assert first["import_id"] == created["import_id"]
    assert first["created_attempt"] is False  # 已有活跃 attempt
    assert second["attempt_id"] == first["attempt_id"]
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()


def test_restore_detects_deleted_source_and_blocks():
    conn = _db()
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (7, 'https://a/7', 'A', '一面', '1.x', 101, 'approved', '后端')"
    )
    created = _accept(conn)
    conn.execute(
        "UPDATE upload_imports SET interview_id = 7 WHERE id = ?",
        (created["import_id"],),
    )
    conn.commit()

    # 原文被删除 → 恢复必须给出可解释阻塞，而不是复活内容
    conn.execute("UPDATE interview SET deleted_at = CURRENT_TIMESTAMP WHERE id = 7")
    conn.commit()
    with pytest.raises(UploadRestoreError) as exc:
        restore_upload(conn, actor_id=101, import_id=created["import_id"])
    assert exc.value.code == "SOURCE_DELETED"
    conn.close()


def test_restore_does_not_reset_successful_stage_results():
    conn = _db()
    created = _accept(conn)
    save_stage_result(
        conn,
        import_id=created["import_id"],
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json='{"questions": []}',
    )
    conn.commit()
    before = conn.execute("SELECT COUNT(*) FROM upload_stage_results").fetchone()[0]

    restore_upload(conn, actor_id=101, import_id=created["import_id"])
    assert conn.execute("SELECT COUNT(*) FROM upload_stage_results").fetchone()[0] == before
    row = conn.execute("SELECT status FROM upload_stage_results WHERE stage = 'extract'").fetchone()
    assert row["status"] == "succeeded", "恢复不得重置已成功阶段"
    conn.close()

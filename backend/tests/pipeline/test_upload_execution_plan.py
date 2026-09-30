"""R03/R04：恢复规划与根状态聚合的执行层测试。

覆盖：
- restore 在同一事务内为同 root 规划未完成 work_key 并写可派发 job
  （失败 root 恢复后 job 存在、绑定 root+attempt+work_key、payload 可执行）；
- 已有在途同 work_key job 时不重复建（部分唯一索引 + 幂等检查）；
- worker 完成/失败后根任务聚合：status/revision/error_code 推进，
  已完成 root 可打开结果；partial_failed 允许重试失败步骤；
- 根快照构造共用 snapshot_from_parts，不再各自拼 DTO。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_lifecycle import (
    FIRST_WORK_KEY,
    UploadRestoreError,
    accept_upload,
    restore_upload,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (101, 'u101', 'x', 0)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO user_llm_config (user_id, api_key, base_url, model) "
        "VALUES (101, 'user-key', 'https://user.example.com/v1', 'user-model')"
    )
    conn.commit()
    return conn


def _accept(conn, *, key="k-1", target="private", extra=None):
    params = {
        "actor_id": 101,
        "actor_is_admin": False,
        "idempotency_key": key,
        "target_intent": target,
        "text": "面经：解释 TCP 三次握手",
        "position_id": 1,
        "position_name": "后端开发",
        "job_position": "后端开发",
        # 注入 loader，避免走到真实生产库读取器（测试内直连内存 DB）
        "credential_loaders": {
            "user": lambda uid: {
                "api_key": "user-key",
                "base_url": "https://user.example.com/v1",
                "model": "user-model",
            }
        },
    }
    if extra:
        params.update(extra)
    return accept_upload(conn, **params)


def test_restore_creates_executable_job_for_failed_root():
    """R03：恢复不止建 attempt，还要为同 root 写可派发 job（含 payload）。"""

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    # 模拟失败：把在途 job 置为 failed（已耗尽尝试）
    conn.execute(
        "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL "
        "WHERE root_import_id = ?",
        (import_id,),
    )
    conn.commit()

    restored = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    assert restored["attempt_no"] >= 1

    jobs = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND status = 'pending'",
        (import_id,),
    ).fetchall()
    # 至少一个可派发 job 绑定 root + attempt + work_key
    assert len(jobs) >= 1, "恢复后必须存在可派发的 job"
    job = jobs[0]
    assert job["job_type"] == "submit_import"
    assert job["work_key"]
    assert job["upload_attempt_id"] == restored["attempt_id"]
    payload_row = conn.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (job["id"],)
    ).fetchone()
    assert payload_row is not None, "恢复的 job 必须有可执行 payload"
    payload = json.loads(payload_row["payload"])
    assert payload["raw_text"], "payload 必须携带原稿"
    conn.close()


def test_restore_reuses_active_work_instead_of_duplicating():
    """R03：已有在途同 work_key job 时不重复建（幂等恢复）。"""

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    conn.commit()

    before = conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE root_import_id = ? AND status IN ('pending','queued','running')",
        (import_id,),
    ).fetchone()["c"]

    # 第一次恢复：无在途 job（初始 pending 仍在），应重复用而非新建
    restored1 = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    after = conn.execute(
        "SELECT COUNT(*) AS c FROM jobs WHERE root_import_id = ? AND status IN ('pending','queued','running')",
        (import_id,),
    ).fetchone()["c"]
    # 原有在途 job 已经覆盖该 work；恢复不得建重复 job
    assert after == before, "已有在途工作时不新建 job"
    assert restored1["created_attempt"] is False
    conn.close()


def test_restore_failed_root_after_attempt_exhausted_updates_attempt_no():
    """R03：失败 root 恢复时新建 attempt 并规划新 job。"""

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    conn.execute(
        "UPDATE jobs SET status = 'failed', worker_id = NULL, locked_until = NULL "
        "WHERE root_import_id = ?",
        (import_id,),
    )
    conn.commit()

    restored = restore_upload(conn, actor_id=101, import_id=import_id)
    conn.commit()
    assert restored["created_attempt"] is True
    # 接受时已建立 attempt 1，失败后恢复为下一个批次 attempt 2
    assert restored["attempt_no"] == 2
    root = conn.execute(
        "SELECT current_attempt_no FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["current_attempt_no"] == 2
    job = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND status = 'pending'",
        (import_id,),
    ).fetchone()
    assert job["upload_attempt_id"] is not None
    conn.close()


def test_restore_non_owner_raises_not_found():
    conn = _db()
    result = _accept(conn)
    with pytest.raises(UploadRestoreError) as exc_info:
        restore_upload(conn, actor_id=102, import_id=result["import_id"])
    assert exc_info.value.code == "NOT_FOUND"
    conn.close()


# ── R04：worker 完成/失败后的根状态聚合 ─────────────────────────

from app.services.upload_lifecycle import finalize_attempt_and_aggregate_root


def _seed_stage_results(conn, import_id: str, stages: list[tuple[str, str]]):
    """stages: [(stage, unit_key, status)] 写入阶段检查点。"""

    for index, (stage, unit_key, status) in enumerate(stages):
        conn.execute(
            "INSERT INTO upload_stage_results ("
            "  import_id, stage, unit_key, input_version, pipeline_version, status, job_id"
            ") VALUES (?, ?, ?, 1, 'upload-pipeline-v1', ?, ?)",
            (import_id, stage, unit_key, status, 1),
        )
    conn.commit()


def test_finalize_success_aggregates_root_to_completed():
    """R04：全部阶段成功后根聚合为 completed、revision 推进、结果可打开。"""

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    _seed_stage_results(
        conn,
        import_id,
        [
            ("extract", "extract:document:v1", "succeeded"),
            ("classify", "classify:all:v1", "succeeded"),
            ("persist", "persist:interview:v1", "succeeded"),
        ],
    )
    # 模拟 worker 已把面经写进 interview 表
    conn.execute(
        "INSERT INTO interview (id, url, owner_id, status, job_position) "
        "VALUES (900, 'internal://abc', 101, 'approved', '后端开发')"
    )
    conn.execute(
        "UPDATE upload_imports SET interview_id = 900 WHERE id = ?", (import_id,)
    )
    # 关联的提交 job 先完成
    conn.execute(
        "UPDATE jobs SET status = 'completed', result = '{\"interview_id\": 900}', "
        "completed_at = CURRENT_TIMESTAMP WHERE root_import_id = ?",
        (import_id,),
    )
    conn.commit()

    snap = finalize_attempt_and_aggregate_root(
        conn, import_id=import_id, actor_id=101
    )
    conn.commit()
    assert snap["status"] == "completed"
    assert snap["result_available"] is True
    assert snap["interview_id"] == 900
    root = conn.execute(
        "SELECT * FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["status"] == "completed"
    assert int(root["revision"]) >= 1
    attempt = conn.execute(
        "SELECT status FROM upload_attempts WHERE import_id = ? "
        "ORDER BY attempt_no DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    assert attempt["status"] == "completed"
    conn.close()


def test_finalize_partial_failed_sets_error_and_allows_retry():
    """R04：部分阶段失败 → partial_failed（有保留结果）+ error_code + 允许重试。"""

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    _seed_stage_results(
        conn,
        import_id,
        [
            ("extract", "extract:document:v1", "succeeded"),
            ("classify", "classify:all:v1", "failed"),
        ],
    )
    conn.execute(
        "UPDATE jobs SET status = 'failed', last_error = 'UPSTREAM_TIMEOUT: 超时', "
        "completed_at = CURRENT_TIMESTAMP WHERE root_import_id = ?",
        (import_id,),
    )
    conn.commit()

    snap = finalize_attempt_and_aggregate_root(
        conn,
        import_id=import_id,
        actor_id=101,
        error_code="UPSTREAM_TIMEOUT",
        error_message="UPSTREAM_TIMEOUT: 超时",
    )
    conn.commit()
    # extract 已成功（有保留结果）+ classify 失败 → 根 partial_failed
    assert snap["status"] == "partial_failed", snap
    assert snap["error"] and snap["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert "retry_failed_steps" in snap["allowed_actions"]
    root = conn.execute(
        "SELECT status, error_code FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert root["status"] == "partial_failed"
    assert root["error_code"] == "UPSTREAM_TIMEOUT"
    conn.close()


def test_finalize_unknown_root_raises():
    conn = _db()
    with pytest.raises(ValueError):
        finalize_attempt_and_aggregate_root(
            conn, import_id="no-such-import", actor_id=101
        )
    conn.close()
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
    UploadRestoreError,
    accept_upload,
    restore_upload,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO job_positions(id,name) VALUES(1, '后端开发')")
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


def _pass_preflight(conn, import_id: str) -> int | None:
    """模拟 worker 预检全部通过：落 succeeded 阶段结果并创建首个业务 job。

    contracts §5：所有必需 scope 通过后才原子创建首个业务 job。
    """

    from app.services.credential_preflight import create_initial_submit_job_if_ready

    rows = conn.execute(
        "SELECT j.id, j.upload_attempt_id, "
        "json_extract(p.payload, '$.credential_scope') AS scope "
        "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.root_import_id = ? AND j.job_type = 'credential_preflight' "
        "AND j.status IN ('pending', 'queued', 'running') ORDER BY j.id",
        (import_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
            "pipeline_version, status, job_id) "
            "VALUES (?, 'credential_preflight', ?, 1, 'upload-pipeline-v1', 'succeeded', ?)",
            (import_id, f"initial:{row['scope']}", row["id"]),
        )
        conn.execute("UPDATE jobs SET status = 'completed' WHERE id = ?", (row["id"],))
    conn.commit()
    attempt = conn.execute(
        "SELECT id FROM upload_attempts WHERE import_id = ? AND status = 'active' "
        "ORDER BY attempt_no DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    if attempt is None:
        return None
    job_id = create_initial_submit_job_if_ready(
        conn, root_import_id=import_id, attempt_id=int(attempt["id"])
    )
    conn.commit()
    return job_id


def test_restore_plans_dispatchable_preflight_and_withholds_business_job():
    """R03 + AC-004：恢复必须规划可派发工作，且预检通过前不得派发业务 job。

    contracts §4：接受/恢复只创建持久 ``credential_preflight`` job，
    "此时不得派发提取/分类/聚类工作"；§5：``job_id`` 可以是尚待执行的预检 job。
    预检全部通过后，首个业务 job 才出现并携带原稿。
    """

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

    pending = conn.execute(
        "SELECT * FROM jobs WHERE root_import_id = ? AND status = 'pending'",
        (import_id,),
    ).fetchall()
    preflight = [j for j in pending if j["job_type"] == "credential_preflight"]
    assert len(preflight) == 1, "恢复必须为本次 attempt 重建可派发的预检 job"
    job = preflight[0]
    assert job["work_key"]
    assert job["upload_attempt_id"] == restored["attempt_id"]
    payload_row = conn.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (job["id"],)
    ).fetchone()
    assert payload_row is not None, "恢复的 job 必须有可执行 payload"
    assert json.loads(payload_row["payload"])["credential_scope"] == "user"
    # AC-004：预检未通过前不得派发任何业务处理 job
    assert [j for j in pending if j["job_type"] == "submit_import"] == [], (
        "预检未通过时不得派发提取/分类等业务 job"
    )

    submit_job_id = _pass_preflight(conn, import_id)
    assert submit_job_id, "预检全部通过后必须创建首个业务 job"
    submit_job = conn.execute(
        "SELECT * FROM jobs WHERE id = ?", (submit_job_id,)
    ).fetchone()
    assert submit_job["status"] == "pending"
    assert submit_job["upload_attempt_id"] == restored["attempt_id"]
    assert submit_job["work_key"]
    submit_payload = json.loads(
        conn.execute(
            "SELECT payload FROM job_payloads WHERE job_id = ?", (submit_job_id,)
        ).fetchone()["payload"]
    )
    assert submit_payload["raw_text"], "业务 job 的 payload 必须携带原稿"
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
    # 先领取（获 lease_generation），再完成，最后用该代次聚合（真实 worker 顺序）
    from app.services.job_lifecycle import claim_job_with_generation

    claimed = claim_job_with_generation(conn, result["job_id"], worker_id="w1")
    lease_generation = int(claimed["lease_generation"])
    conn.execute(
        "UPDATE jobs SET status = 'completed', result = '{\"interview_id\": 900}', "
        "completed_at = CURRENT_TIMESTAMP WHERE root_import_id = ?",
        (import_id,),
    )
    conn.commit()

    snap = finalize_attempt_and_aggregate_root(
        conn, import_id=import_id, actor_id=101, lease_generation=lease_generation
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
    from app.services.job_lifecycle import claim_job_with_generation

    claimed = claim_job_with_generation(conn, result["job_id"], worker_id="w1")
    lease_generation = int(claimed["lease_generation"])
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
        lease_generation=lease_generation,
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


@pytest.mark.parametrize(
    "is_admin,expected_action",
    [(False, "wait_for_global_model"), (True, "configure_system_model")],
)
def test_finalize_global_model_actions_follow_root_owner_role(is_admin, expected_action):
    """Worker snapshots use the task owner's role, not the current API viewer."""

    conn = _db()
    actor_id = 201 if is_admin else 101
    if is_admin:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin) "
            "VALUES (201, 'admin201', 'x', 1)"
        )
    result = _accept(
        conn,
        key=f"global-{actor_id}",
        target="share",
        extra={"actor_id": actor_id, "actor_is_admin": is_admin},
    )
    import_id = result["import_id"]
    conn.execute(
        "UPDATE upload_imports SET policy_json = ? WHERE id = ?",
        (json.dumps({"credential_scope": "global"}), import_id),
    )
    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status, error_code, job_id) "
        "VALUES (?, 'credential_preflight', 'global-attempt-1', 1, 'upload-pipeline-v1', "
        "'needs_action', 'MODEL_CONFIG_MISSING', ?)",
        (import_id, result["job_id"]),
    )
    conn.commit()

    from app.services.job_lifecycle import claim_job_with_generation

    claimed = claim_job_with_generation(conn, result["job_id"], worker_id="w1")
    lease_generation = int(claimed["lease_generation"])
    conn.execute(
        "UPDATE jobs SET status = 'completed', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (result["job_id"],),
    )
    conn.commit()

    snapshot = finalize_attempt_and_aggregate_root(
        conn,
        import_id=import_id,
        actor_id=actor_id,
        error_code="MODEL_CONFIG_MISSING",
        error_message="system model unavailable",
        lease_generation=lease_generation,
    )
    conn.commit()

    assert snapshot["status"] == "needs_action"
    assert expected_action in snapshot["allowed_actions"]
    assert (
        "configure_system_model" not in snapshot["allowed_actions"]
        if not is_admin
        else "wait_for_global_model" not in snapshot["allowed_actions"]
    )
    conn.close()


def test_finalize_unknown_root_raises():
    conn = _db()
    with pytest.raises(ValueError):
        finalize_attempt_and_aggregate_root(
            conn, import_id="no-such-import", actor_id=101
        )
    conn.close()

# ── F09/F12：worker generation fencing（租约代次隔离）─────────────────


def test_finalize_with_stale_generation_is_rejected_without_root_write():
    """F09/F12：根聚合必须持当前 lease_generation；被回收的旧代次写入被拒绝，
    根任务状态与 revision 不得被旧 worker 改写。"""

    from app.services.job_lifecycle import (
        JobFenceError,
        claim_job_with_generation,
    )
    from app.services.upload_lifecycle import finalize_attempt_and_aggregate_root

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    conn.commit()

    # AC-004：业务 job 只在预检全部通过后出现（contracts §5）
    submit_job_id = _pass_preflight(conn, import_id)
    assert submit_job_id, "预检通过后必须存在业务 job"
    conn.commit()

    # 代次 1 的 worker 领取业务 job
    claimed = claim_job_with_generation(conn, submit_job_id, worker_id="w1")
    conn.commit()
    assert claimed is not None
    gen1 = int(claimed["lease_generation"])

    # 旧 worker 租约过期 → 回收回 pending → 新 worker 重新领取（代次递增）
    from app.services.job_lifecycle import recover_expired_jobs

    conn.execute(
        "UPDATE jobs SET locked_until = '2000-01-01 00:00:00' WHERE id = ?",
        (submit_job_id,),
    )
    recovered = recover_expired_jobs(conn, job_type="submit_import")
    assert recovered >= 1
    conn.commit()

    claimed2 = claim_job_with_generation(
        conn, submit_job_id, worker_id="w2", lease_seconds=3600
    )
    assert claimed2 is not None, "回收后新 worker 应可领取"
    conn.commit()
    gen2 = int(claimed2["lease_generation"])
    assert gen2 == gen1 + 1

    revision_before = int(
        conn.execute(
            "SELECT revision FROM upload_imports WHERE id = ?", (import_id,)
        ).fetchone()["revision"]
    )

    # 旧代次 w1 聚合根任务 → 必须拒绝，且根任务不被写
    with pytest.raises(JobFenceError):
        finalize_attempt_and_aggregate_root(
            conn,
            import_id=import_id,
            actor_id=101,
            lease_generation=gen1,
        )
    conn.rollback()
    root = conn.execute(
        "SELECT status, revision FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert int(root["revision"]) == revision_before, "被拒的旧代次不得推进 revision"

    # 当前代次 w2 聚合成功
    snap = finalize_attempt_and_aggregate_root(
        conn,
        import_id=import_id,
        actor_id=101,
        lease_generation=gen2,
    )
    conn.commit()
    assert snap["status"] in ("completed", "queued", "failed")
    root_after = conn.execute(
        "SELECT revision FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    assert int(root_after["revision"]) > revision_before
    conn.close()


def test_finalize_without_generation_rejects_v2_service_contract():
    """F12：v2 根聚合不传 lease_generation 视为编程错误（不允许裸写）。"""

    from app.services.upload_lifecycle import finalize_attempt_and_aggregate_root

    conn = _db()
    result = _accept(conn)
    import_id = result["import_id"]
    conn.commit()

    revision_before = int(
        conn.execute(
            "SELECT revision FROM upload_imports WHERE id = ?", (import_id,)
        ).fetchone()["revision"]
    )
    with pytest.raises(TypeError):
        finalize_attempt_and_aggregate_root(
            conn, import_id=import_id, actor_id=101
        )
    conn.rollback()
    root = conn.execute(
        "SELECT revision FROM upload_imports WHERE id = ?", (import_id,)
    ).fetchone()
    # accept 自身会推进 revision（contracts §5 返回 revision），
    # 被拒的聚合不得再推进
    assert int(root["revision"]) == revision_before
    conn.close()

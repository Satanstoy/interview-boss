"""AC-013 / UR-013：统一 snapshot 协议与重试预算。

契约（contracts.md §4.3、§4.4）：

- pending/running/needs_action/completed 使用同一 snapshot 结构；
- 401/配置/权限/额度类错误**一次即停**；上游限流/超时最多 3 次物理尝试；
- 结构错误的修复调用计入同一总预算（禁止“外3次×内3次”）；
- 错误码决定根状态与动作，重试决策由一个执行层统一给出。
"""

from __future__ import annotations

from app.models.upload_contracts import UploadStatus
from app.services.upload_retry_budget import (
    ERROR_POLICY,
    RetryBudget,
    build_snapshot_event,
    decide_retry,
    snapshot_from_parts,
)


def test_error_policy_covers_contract_codes():
    for code in (
        "MODEL_AUTH_INVALID",
        "MODEL_CONFIG_MISSING",
        "PERMISSION_REVOKED",
        "SOURCE_DELETED",
        "QUOTA_EXCEEDED",
        "UPSTREAM_RATE_LIMIT",
        "UPSTREAM_TIMEOUT",
        "UPSTREAM_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
        "STATE_CONFLICT",
        "IDEMPOTENCY_CONFLICT",
        "LEGACY_MAPPING_AMBIGUOUS",
    ):
        assert code in ERROR_POLICY
        assert "retryable" in ERROR_POLICY[code]
        assert "action" in ERROR_POLICY[code]


def test_auth_error_stops_after_one_physical_call():
    budget = RetryBudget()
    first = decide_retry("MODEL_AUTH_INVALID", budget)
    assert first["retry"] is False
    assert first["root_status"] == "needs_action"
    assert budget.physical_attempts == 1
    assert decide_retry("MODEL_AUTH_INVALID", budget)["retry"] is False


def test_upstream_errors_get_at_most_three_physical_attempts():
    budget = RetryBudget()
    outcomes = [decide_retry("UPSTREAM_TIMEOUT", budget)["retry"] for _ in range(4)]
    assert outcomes == [True, True, True, False]
    assert budget.physical_attempts == 3


def test_structure_repairs_share_the_same_budget():
    budget = RetryBudget()
    assert decide_retry("UPSTREAM_TIMEOUT", budget)["retry"] is True  # 1
    assert decide_retry("MODEL_OUTPUT_INVALID", budget)["retry"] is True  # 2（修复1）
    assert decide_retry("MODEL_OUTPUT_INVALID", budget)["retry"] is True  # 3（修复2）
    assert decide_retry("MODEL_OUTPUT_INVALID", budget)["retry"] is False  # 超预算


def test_quota_and_state_conflicts_never_retry():
    for code in (
        "QUOTA_EXCEEDED",
        "STATE_CONFLICT",
        "IDEMPOTENCY_CONFLICT",
        "LEGACY_MAPPING_AMBIGUOUS",
    ):
        budget = RetryBudget()
        assert decide_retry(code, budget)["retry"] is False


def test_snapshot_shape_is_identical_for_all_statuses():
    for status in (
        UploadStatus.QUEUED,
        UploadStatus.RUNNING,
        UploadStatus.NEEDS_ACTION,
        UploadStatus.PARTIAL_FAILED,
        UploadStatus.FAILED,
        UploadStatus.WAITING_REVIEW,
        UploadStatus.COMPLETED,
    ):
        snapshot = snapshot_from_parts(
            import_id="imp-1",
            revision=5,
            status=status,
            stage="answer",
            counts={"answered": 8, "failed": 2},
            allowed_actions=["retry_failed_steps"],
        )
        for key in (
            "import_id",
            "revision",
            "status",
            "target_intent",
            "attempt_no",
            "review_status",
            "stage",
            "progress",
            "counts",
            "result",
            "error",
            "allowed_actions",
            "updated_at",
        ):
            assert key in snapshot.model_dump(), f"{status} 缺少字段 {key}"


def test_snapshot_event_carries_revision_as_event_id():
    snapshot = snapshot_from_parts(import_id="imp-1", revision=9, status=UploadStatus.RUNNING)
    event = build_snapshot_event(snapshot)
    assert event["event"] == "snapshot"
    assert event["id"] == 9
    assert event["data"]["import_id"] == "imp-1"


def test_snapshot_never_contains_raw_text_or_key():
    snapshot = snapshot_from_parts(
        import_id="imp-1",
        revision=1,
        status=UploadStatus.FAILED,
        error={
            "code": "MODEL_AUTH_INVALID",
            "message": "请更新个人模型配置后继续",
            "retryable": False,
            "action": "configure_user_model",
            "scope": "user",
        },
    )
    dumped = snapshot.model_dump()
    assert "api_key" not in str(dumped).lower()
    assert "authorization" not in str(dumped).lower()


def test_stage_counts_reflect_extract_counts_and_resolutions(tmp_path):
    """AC-013：counts 必须是逐题统计——extracted/retained/excluded/
    needs_review 来自 extract 阶段「提取计数」，resolved 来自逐题
    resolution 计数，不再以检查点行数充当。"""

    import json as _json
    import sqlite3

    from app.db.migrations import run_migrations
    from app.routers.upload_imports import _stage_counts

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (101, 'u101', 'x', 0)"
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, "
        "status, revision) VALUES ('imp-c1', 101, 'k-c1', 'h-c1', 'private', "
        "'interview', 'upload-pipeline-v1', '{}', '{}', 'completed', 2)"
    )
    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status, result_json) VALUES "
        "('imp-c1', 'extract', 'document', 1, 'upload-pipeline-v1', 'succeeded', ?)",
        (
            _json.dumps(
                {
                    "提取计数": {
                        "extracted": 5,
                        "retained": 4,
                        "excluded": 1,
                        "needs_review": 2,
                    }
                },
                ensure_ascii=False,
            ),
        ),
    )
    # 2 条明细，1 条 matched（成功 resolution）、1 条 failed
    conn.execute(
        "INSERT INTO interview (id, url, company, owner_id, status) VALUES "
        "(9001, 'https://c1.example.com', '字节', 101, 'approved')"
    )
    for detail_id in (501, 502):
        conn.execute(
            "INSERT INTO questions_detail (id, url, question, interview_id, owner_id, "
            "status, import_id, source_ordinal) VALUES (?, ?, ?, 9001, 101, 'approved', "
            "'imp-c1', ?)",
            (detail_id, f"https://c1.example.com/q{detail_id}", f"题{detail_id}", detail_id - 500),
        )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, status, job_position) "
        "VALUES (7001, 'TCP握手', '网络', 'TCP', 'approved', '后端')"
    )
    conn.execute(
        "INSERT INTO question_resolutions (detail_id, occurrence_scope, occurrence_owner_id, "
        "canonical_id, status, pipeline_version, input_version) "
        "VALUES (501, 'private', 101, 7001, 'matched', 'upload-pipeline-v1', 1)"
    )
    conn.execute(
        "INSERT INTO question_resolutions (detail_id, occurrence_scope, occurrence_owner_id, "
        "status, pipeline_version, input_version) "
        "VALUES (502, 'private', 101, 'failed', 'upload-pipeline-v1', 1)"
    )
    conn.commit()

    counts = _stage_counts(conn, "imp-c1")
    assert counts["extracted"] == 5, "extracted 必须来自提取计数"
    assert counts["retained"] == 4
    assert counts["excluded"] == 1, "excluded 必须来自提取计数（不再恒 0）"
    assert counts["needs_review"] == 2, "needs_review 必须来自提取计数（不再硬编码 0）"
    assert counts["resolved"] == 1, "resolved 必须是逐题成功的 resolution 数（501）"
    conn.close()


def test_snapshot_review_status_from_bound_contribution(tmp_path):
    """AC-010/AC-013：root 绑定公共化申请后，快照 review_status 不再恒空
    （此前 _snapshot 只透出 contribution_request_id 不计算 review_status）。"""

    import sqlite3

    from app.db.migrations import run_migrations
    from app.routers.upload_imports import _snapshot

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (101, 'u101', 'x', 0)"
    )
    conn.execute(
        "INSERT INTO interview (id, url, company, owner_id, status) VALUES "
        "(9001, 'https://c.example.com', '字节', 101, 'approved')"
    )
    conn.execute(
        "INSERT INTO public_contribution_requests (source_type, source_id, requester_id, "
        "status, revision) VALUES ('interview', 9001, 101, 'pending_review', 1)"
    )
    request_id = conn.execute(
        "SELECT id FROM public_contribution_requests WHERE source_id = 9001"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, "
        "status, revision, contribution_request_id) "
        "VALUES ('imp-r1', 101, 'k-r1', 'h-r1', 'share', 'interview', "
        "'upload-pipeline-v1', '{}', '{}', 'completed', 2, ?)",
        (request_id,),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM upload_imports WHERE id = 'imp-r1'").fetchone()
    snap = _snapshot(row, conn=conn)
    assert snap["review_status"] == "pending_review", (
        "绑定公共化申请后快照 review_status 必须来自申请状态"
    )
    assert snap["contribution_request_id"] is not None
    assert snap["status"] == "completed", (
        "根状态由 worker 聚合推进（waiting_review 转换在 aggregate 层），快照透传 review_status"
    )
    conn.close()


def test_snapshot_global_preflight_actions_follow_viewer_role(test_db):
    """Global credential errors direct admins to settings and users to wait."""
    import json as _json

    from app.routers.upload_imports import _snapshot

    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (101, 'upload-user', 'x', 0)"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
        "VALUES (201, 'upload-admin', 'x', 1)"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, policy_json, payload_json, "
        "status, error_code, error_message) "
        "VALUES ('imp-global-block', 101, 'global-block', 'hash', 'share', 'interview', "
        "'upload-pipeline-v1', ?, '{}', 'needs_action', 'MODEL_CONFIG_MISSING', 'system model unavailable')",
        (_json.dumps({"credential_scope": "user", "post_approval_credential_scope": "global"}),),
    )
    job_id = test_db.execute(
        "INSERT INTO jobs (job_type, status, root_import_id, work_key) "
        "VALUES ('credential_preflight', 'failed', 'imp-global-block', 'preflight:credential:v1') "
        "RETURNING id"
    ).fetchone()["id"]
    test_db.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, _json.dumps({"credential_scope": "global"})),
    )
    test_db.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, input_version, "
        "pipeline_version, status, error_code, job_id) VALUES "
        "('imp-global-block', 'credential_preflight', 'global-attempt-1', 1, 'upload-pipeline-v1', "
        "'failed', 'MODEL_CONFIG_MISSING', ?)",
        (job_id,),
    )
    test_db.commit()
    row = test_db.execute(
        "SELECT * FROM upload_imports WHERE id = 'imp-global-block'"
    ).fetchone()

    user_snapshot = _snapshot(row, conn=test_db, actor_is_admin=False)
    admin_snapshot = _snapshot(row, conn=test_db, actor_is_admin=True)

    assert user_snapshot["error"]["scope"] == "global"
    assert user_snapshot["error"]["action"] == "wait_for_global_model"
    assert "wait_for_global_model" in user_snapshot["allowed_actions"]
    assert "configure_system_model" not in user_snapshot["allowed_actions"]
    assert admin_snapshot["error"]["action"] == "configure_system_model"
    assert "configure_system_model" in admin_snapshot["allowed_actions"]


def test_snapshot_keeps_non_credential_error_scope_from_error_policy():
    from app.routers.upload_imports import _error_dto

    assert _error_dto("UPSTREAM_TIMEOUT", "timeout")["scope"] == "system"

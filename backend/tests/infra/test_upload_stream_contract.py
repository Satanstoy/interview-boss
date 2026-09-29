"""AC-013 / UR-013：统一 snapshot 协议与重试预算。

契约（contracts.md §4.3、§4.4）：

- pending/running/needs_action/completed 使用同一 snapshot 结构；
- 401/配置/权限/额度类错误**一次即停**；上游限流/超时最多 3 次物理尝试；
- 结构错误的修复调用计入同一总预算（禁止“外3次×内3次”）；
- 错误码决定根状态与动作，重试决策由一个执行层统一给出。
"""

from __future__ import annotations

import pytest

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

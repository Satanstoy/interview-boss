"""AC-011 / UR-011：真实完成状态与 allowed_actions。

契约（contracts.md §5.1）：

- 聚合顺序：running → queued → needs_action → partial_failed/failed →
  waiting_review → completed；``warnings``/``review_status`` 独立存在；
- “面经已保存但聚类未完成”不得显示 completed；
- 10 题 8 答案成功 2 失败 → partial_failed，结果可打开，恢复只补失败项；
- 只显示服务端 ``allowed_actions``；没有暂停能力时禁止显示暂停。
"""

from __future__ import annotations

import pytest

from app.services.upload_status import (
    allowed_actions,
    aggregate_status,
    summarize_progress,
)


def _work(**overrides):
    base = {
        "stage": "answer",
        "unit_key": "canonical:public:1",
        "status": "succeeded",
        "has_result": True,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "items,expected",
    [
        ([_work(status="running")], "running"),
        ([_work(status="pending"), _work(status="succeeded")], "queued"),
        ([_work(status="needs_action")], "needs_action"),
        (
            [_work(status="succeeded"), _work(status="failed")],
            "partial_failed",
        ),
        ([_work(status="failed", has_result=False)], "failed"),
        ([_work(status="succeeded")], "completed"),
        ([], "completed"),
    ],
)
def test_status_aggregation_priority(items, expected):
    assert aggregate_status(items)["status"] == expected


def test_saved_interview_without_cluster_work_is_not_completed():
    items = [
        {"stage": "persist", "unit_key": "document", "status": "succeeded", "has_result": True},
        {"stage": "cluster", "unit_key": "root:v1", "status": "pending", "has_result": False},
    ]
    assert aggregate_status(items)["status"] == "queued"
    assert aggregate_status(items)["stage"] == "cluster"


def test_partial_failure_reports_counts_and_keeps_result():
    items = [_work(status="succeeded", has_result=True) for _ in range(8)]
    items += [
        _work(status="failed", has_result=False, unit_key=f"canonical:public:{i}") for i in range(2)
    ]
    agg = aggregate_status(items)
    assert agg["status"] == "partial_failed"
    assert agg["counts"]["answered"] == 8
    assert agg["counts"]["failed"] == 2
    assert agg["result_available"] is True


def test_review_status_is_independent_of_computation_status():
    items = [_work(status="succeeded")]
    agg = aggregate_status(items, review_status="pending_review")
    assert agg["status"] == "waiting_review"
    assert agg["review_status"] == "pending_review"


def test_warnings_are_not_swallowed_by_status():
    items = [_work(status="succeeded")]
    agg = aggregate_status(items, warnings=["答案缺失，已跳过"])
    assert agg["status"] == "completed"
    assert agg["warnings"] == ["答案缺失，已跳过"]


def test_allowed_actions_never_invent_pause():
    for status in (
        "running",
        "queued",
        "needs_action",
        "partial_failed",
        "failed",
        "completed",
        "waiting_review",
    ):
        actions = allowed_actions(status)
        assert "pause" not in actions
        assert "cancel" not in actions


def test_allowed_actions_needs_action_points_to_configuration():
    actions = allowed_actions("needs_action", error_code="MODEL_AUTH_INVALID")
    assert "configure_user_model" in actions
    assert "retry_after_configuration" in actions


def test_allowed_actions_partial_failed_retries_only_failed_steps():
    actions = allowed_actions("partial_failed", has_result=True)
    assert "retry_failed_steps" in actions
    assert "open_result" in actions


def test_progress_is_indeterminate_when_total_unknown():
    progress = summarize_progress(completed=3, total=None)
    assert progress["total"] is None
    assert progress["indeterminate"] is True
    assert "percent" not in progress


def test_allowed_actions_global_scope_points_to_system_configuration():
    """contracts §4.4：global scope（管理员公共导入）错误动作是
    configure_system_model，不是 configure_user_model。"""

    actions = allowed_actions(
        "needs_action",
        error_code="MODEL_AUTH_INVALID",
        credential_scope="global",
    )
    assert "configure_system_model" in actions
    assert "configure_user_model" not in actions
    assert "retry_after_configuration" in actions


def test_allowed_actions_shared_user_global_missing_warns_wait_global():
    """contracts §4.4：普通用户公共（share 后公共阶段）global 缺失 →
    wait_for_global_model 提示（系统配置待管理修复），非本人配置。"""

    actions = allowed_actions(
        "needs_action",
        error_code="MODEL_CONFIG_MISSING",
        credential_scope="global",
    )
    assert "wait_for_global_model" in actions
    assert "configure_user_model" not in actions
    assert "retry_after_configuration" in actions


def test_allowed_actions_user_scope_unchanged():
    actions = allowed_actions(
        "needs_action",
        error_code="MODEL_AUTH_INVALID",
        credential_scope="user",
    )
    assert "configure_user_model" in actions
    assert "configure_system_model" not in actions

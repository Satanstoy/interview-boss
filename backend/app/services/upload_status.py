"""根任务状态聚合与操作白名单（AC-011 / UR-011）。

规则（contracts §5.1）：

- 聚合顺序：running → queued → needs_action → partial_failed/failed →
  waiting_review → completed；
- ``warnings`` 与 ``review_status`` 独立存在，不被聚合状态覆盖；
- 结果是否可打开（``result_available``）与“全部完成”是两件事；
- 只返回服务端 ``allowed_actions``：没有暂停/取消能力就绝不出现该按钮。
"""

from __future__ import annotations

STAGE_ORDER = (
    "extract",
    "classify",
    "persist",
    "resolve",
    "cluster",
    "answer",
    "review",
    "publish",
)

_ACTIVE_STATUSES = ("pending", "queued", "running", "failed", "needs_action")
_QUEUED_STATUSES = ("pending", "queued")
_REVIEW_WAITING = ("pending_review", "approved_for_processing", "queued", "processing")


def aggregate_status(work_items, *, review_status: str | None = None, warnings=None) -> dict:
    """把子步骤状态聚合成根任务状态。"""

    items = list(work_items or [])
    has_running = any(item.get("status") == "running" for item in items)
    has_queued = any(item.get("status") in _QUEUED_STATUSES for item in items)
    has_needs_action = any(item.get("status") == "needs_action" for item in items)
    failed = [item for item in items if item.get("status") == "failed"]
    succeeded = [item for item in items if item.get("status") == "succeeded"]
    has_result = any(item.get("has_result") for item in items) or bool(succeeded)

    if has_running:
        status = "running"
    elif has_queued:
        status = "queued"
    elif has_needs_action:
        status = "needs_action"
    elif failed:
        status = "partial_failed" if has_result else "failed"
    elif review_status in _REVIEW_WAITING:
        status = "waiting_review"
    else:
        status = "completed"

    current_stage = None
    for stage in STAGE_ORDER:
        if any(
            item.get("stage") == stage and item.get("status") in _ACTIVE_STATUSES for item in items
        ):
            current_stage = stage
            break

    counts = {
        "total": len(items),
        "succeeded": len(succeeded),
        "answered": len(succeeded),
        "failed": len(failed),
        "needs_action": sum(1 for item in items if item.get("status") == "needs_action"),
    }
    return {
        "status": status,
        "stage": current_stage,
        "counts": counts,
        "result_available": has_result,
        "review_status": review_status,
        "warnings": list(warnings or []),
    }


def allowed_actions(
    status: str,
    *,
    error_code: str | None = None,
    has_result: bool = False,
    credential_scope: str = "user",
    is_admin: bool = False,
) -> list[str]:
    """服务端允许的操作；绝不虚构暂停/取消。

    ``credential_scope`` 携带服务端 policy 的凭据 scope（contracts §4.4）：
    全局凭据缺失/失效时，管理员公共导入与用户公共化申请的动作是
    ``configure_system_model`` / ``wait_for_global_model``（系统配置待
    管理员修复），而不是错误地引导去配置本人模型。
    """

    actions: list[str] = []
    if has_result:
        actions.append("open_result")
    if status == "needs_action":
        if error_code in (
            "SOURCE_DELETED",
            "SOURCE_EXPIRED",
            "POSITION_RETIRED",
            "TAXONOMY_CHANGED",
            "PIPELINE_VERSION_UNSUPPORTED",
        ):
            actions.append("resubmit_source")
        elif error_code in ("MODEL_AUTH_INVALID", "MODEL_CONFIG_MISSING"):
            if credential_scope == "global":
                actions.append(
                    "configure_system_model" if is_admin else "wait_for_global_model"
                )
            else:
                actions.append("configure_user_model")
        if error_code == "QUOTA_EXCEEDED":
            actions.append("view_budget")
        if error_code not in (
            "SOURCE_DELETED",
            "SOURCE_EXPIRED",
            "POSITION_RETIRED",
            "TAXONOMY_CHANGED",
            "PIPELINE_VERSION_UNSUPPORTED",
        ):
            actions.append("retry_after_configuration")
    elif status == "partial_failed":
        actions.append("retry_failed_steps")
    elif status == "failed":
        actions.append("retry")
    elif status in ("queued", "running"):
        actions.append("view_progress")
    elif status == "waiting_review":
        actions.append("view_review_status")
    elif status == "completed" and not has_result:
        actions.append("view_summary")

    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped


def summarize_progress(*, completed: int, total: int | None) -> dict:
    """分母未定时显示不确定进度，不伪造百分比。"""

    if total is None:
        return {"completed": int(completed), "total": None, "indeterminate": True}
    total_value = int(total)
    percent = round(completed * 100 / total_value, 1) if total_value else 0.0
    return {
        "completed": int(completed),
        "total": total_value,
        "indeterminate": False,
        "percent": percent,
    }

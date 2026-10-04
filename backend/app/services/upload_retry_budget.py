"""统一错误分类与重试预算（AC-013 / UR-013）。

契约（contracts §4.4）：错误码唯一决定“是否自动重试、根状态、用户动作”；
总物理尝试次数只由这一个执行层控制，LLM helper 的内部重试不得另起预算。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.upload_contracts import (
    UploadCountsDTO,
    UploadErrorDTO,
    UploadProgressDTO,
    UploadResultDTO,
    UploadResultTargetDTO,
    UploadSnapshot,
    UploadStatus,
)

# code → {retryable, action, root_status, scope}
ERROR_POLICY: dict[str, dict] = {
    "MODEL_AUTH_INVALID": {
        "retryable": False,
        "action": "configure_user_model",
        "root_status": "needs_action",
        "scope": "user",
    },
    "MODEL_CONFIG_MISSING": {
        "retryable": False,
        "action": "configure_user_model",
        "root_status": "needs_action",
        "scope": "user",
    },
    "PERMISSION_REVOKED": {
        "retryable": False,
        "action": "check_permission",
        "root_status": "needs_action",
        "scope": "user",
    },
    "SOURCE_DELETED": {
        "retryable": False,
        "action": "view_source_status",
        "root_status": "needs_action",
        "scope": "user",
    },
    "SOURCE_EXPIRED": {
        "retryable": False,
        "action": "resubmit_source",
        "root_status": "needs_action",
        "scope": "user",
    },
    "POSITION_RETIRED": {
        "retryable": False,
        "action": "resubmit_source",
        "root_status": "needs_action",
        "scope": "user",
    },
    "TAXONOMY_CHANGED": {
        "retryable": False,
        "action": "resubmit_source",
        "root_status": "needs_action",
        "scope": "user",
    },
    "PIPELINE_VERSION_UNSUPPORTED": {
        "retryable": False,
        "action": "resubmit_source",
        "root_status": "needs_action",
        "scope": "user",
    },
    "QUOTA_EXCEEDED": {
        "retryable": False,
        "action": "wait_for_daily_reset",
        "root_status": "needs_action",
        "scope": "user",
    },
    "UPSTREAM_RATE_LIMIT": {
        "retryable": True,
        "action": "auto_retry",
        "root_status": "queued",
        "scope": "system",
    },
    "UPSTREAM_TIMEOUT": {
        "retryable": True,
        "action": "auto_retry",
        "root_status": "queued",
        "scope": "system",
    },
    "UPSTREAM_UNAVAILABLE": {
        "retryable": True,
        "action": "auto_retry",
        "root_status": "queued",
        "scope": "system",
    },
    "MODEL_OUTPUT_INVALID": {
        "retryable": True,
        "action": "auto_retry",
        "root_status": "queued",
        "scope": "system",
    },
    "STATE_CONFLICT": {
        "retryable": False,
        "action": "refresh_snapshot",
        "root_status": "needs_action",
        "scope": "user",
    },
    "IDEMPOTENCY_CONFLICT": {
        "retryable": False,
        "action": "view_existing_task",
        "root_status": "needs_action",
        "scope": "user",
    },
    "LEGACY_MAPPING_AMBIGUOUS": {
        "retryable": False,
        "action": "confirm_mapping",
        "root_status": "needs_action",
        "scope": "user",
    },
}

# 退避：第 1、2 次失败后分别 30、60 秒
BACKOFF_SECONDS = (30, 60)


@dataclass
class RetryBudget:
    """一次步骤执行的物理尝试预算（默认 3 次，含结构修复调用）。"""

    max_attempts: int = 3
    physical_attempts: int = 0

    @property
    def exhausted(self) -> bool:
        return self.physical_attempts >= self.max_attempts


def decide_retry(code: str, budget: RetryBudget) -> dict:
    """在一次失败后决定是否自动重试；预算耗尽即停止。"""

    policy = ERROR_POLICY.get(code)
    if policy is None:
        policy = {
            "retryable": False,
            "action": "view_error",
            "root_status": "failed",
            "scope": "system",
        }

    if not policy["retryable"]:
        # 这次失败已经消耗一次物理尝试，但绝不重试
        budget.physical_attempts += 1
        return {
            "retry": False,
            "code": code,
            "root_status": policy["root_status"],
            "action": policy["action"],
            "scope": policy["scope"],
            "delay_seconds": 0,
        }

    if budget.exhausted:
        return {
            "retry": False,
            "code": code,
            "root_status": policy["root_status"],
            "action": policy["action"],
            "scope": policy["scope"],
            "delay_seconds": 0,
        }

    budget.physical_attempts += 1
    delay = (
        BACKOFF_SECONDS[budget.physical_attempts - 1]
        if budget.physical_attempts - 1 < len(BACKOFF_SECONDS)
        else BACKOFF_SECONDS[-1]
    )
    return {
        "retry": True,
        "code": code,
        "root_status": policy["root_status"],
        "action": policy["action"],
        "scope": policy["scope"],
        "delay_seconds": delay,
    }


def snapshot_from_parts(
    *,
    import_id: str,
    revision: int,
    status: UploadStatus | str,
    target_intent: str = "private",
    attempt_no: int = 0,
    review_status=None,
    stage: str | None = None,
    progress=None,
    counts=None,
    result=None,
    result_target=None,
    error=None,
    allowed_actions=None,
    recovery_available: bool = True,
    recovery_message: str | None = None,
    updated_at: str | None = None,
) -> UploadSnapshot:
    """所有状态共用的 snapshot 构造（AC-013：协议一致）。"""

    return UploadSnapshot(
        import_id=import_id,
        revision=int(revision),
        status=UploadStatus(status) if not isinstance(status, UploadStatus) else status,
        target_intent=target_intent,
        attempt_no=int(attempt_no),
        review_status=review_status,
        stage=stage,
        progress=UploadProgressDTO(**progress) if isinstance(progress, dict) else progress,
        counts=UploadCountsDTO(**counts) if isinstance(counts, dict) else counts,
        result=UploadResultDTO(**result) if isinstance(result, dict) else result,
        result_target=(
            UploadResultTargetDTO(**result_target)
            if isinstance(result_target, dict)
            else result_target
        ),
        error=UploadErrorDTO(**error) if isinstance(error, dict) else error,
        allowed_actions=list(allowed_actions or []),
        recovery_available=bool(recovery_available),
        recovery_message=recovery_message,
        updated_at=updated_at,
    )


def build_snapshot_event(snapshot: UploadSnapshot) -> dict:
    """SSE ``snapshot`` 事件：``id`` 即 revision，客户端忽略更小的版本。"""

    return {
        "event": "snapshot",
        "id": int(snapshot.revision),
        "data": snapshot.model_dump(mode="json"),
    }

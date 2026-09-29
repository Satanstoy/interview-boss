"""upload recovery 事务内读写（repository）。

职责（contracts.md §1.1–§1.4、§2.4）：

- 幂等根任务：同用户同键同 hash 复用同一 import；同键不同 hash 冲突。
- 恢复批次：一个 import 至多一个 active attempt（数据库 partial unique 兜底）。
- 阶段检查点：``UNIQUE(import_id, stage, unit_key, input_version)``。

**所有函数都不 commit**：调用方持有外层事务，回滚必须带走这些写入。
本模块不调用模型、不投递 ARQ。
"""

from __future__ import annotations

import uuid

UPLOAD_PIPELINE_VERSION_DEFAULT = "upload-pipeline-v1"


class IdempotencyConflict(Exception):
    """同幂等键提交了不同内容（contracts §1.1）。"""

    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, *, idempotency_key: str, import_id: str):
        self.idempotency_key = idempotency_key
        self.import_id = import_id
        super().__init__(f"幂等键 {idempotency_key!r} 已绑定不同内容（import_id={import_id}）")


def create_or_get_import(
    conn,
    *,
    requester_id: int,
    idempotency_key: str,
    request_hash: str,
    target_intent: str,
    source_type: str,
    pipeline_version: str = UPLOAD_PIPELINE_VERSION_DEFAULT,
    resolved_type: str | None = None,
    position_id: int | None = None,
    position_name: str = "",
    input_version: int = 1,
    policy_json: str = "{}",
    payload_json: str = "{}",
    import_id: str | None = None,
) -> tuple[str, bool]:
    """返回 ``(import_id, created)``；同键同 hash 复用，同键不同 hash 抛冲突。"""

    if not idempotency_key:
        raise ValueError("idempotency_key 不能为空")
    if not request_hash:
        raise ValueError("request_hash 不能为空")

    existing = conn.execute(
        "SELECT id, request_hash FROM upload_imports "
        "WHERE requester_id = ? AND idempotency_key = ?",
        (requester_id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if existing["request_hash"] != request_hash:
            raise IdempotencyConflict(idempotency_key=idempotency_key, import_id=existing["id"])
        return existing["id"], False

    new_id = import_id or str(uuid.uuid4())
    conn.execute(
        "INSERT INTO upload_imports ("
        "  id, requester_id, idempotency_key, request_hash, target_intent, "
        "  source_type, resolved_type, position_id, position_name, input_version, "
        "  pipeline_version, policy_json, payload_json"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id,
            requester_id,
            idempotency_key,
            request_hash,
            target_intent,
            source_type,
            resolved_type,
            position_id,
            position_name,
            input_version,
            pipeline_version,
            policy_json,
            payload_json,
        ),
    )
    return new_id, True


def get_import_by_key(conn, *, requester_id: int, idempotency_key: str):
    """按幂等键查询本人的根任务；他人同键一律不可见。"""

    return conn.execute(
        "SELECT * FROM upload_imports WHERE requester_id = ? AND idempotency_key = ?",
        (requester_id, idempotency_key),
    ).fetchone()


def create_attempt(conn, *, import_id: str, requested_by: int, status: str = "active"):
    """为根任务建立新的恢复批次；已有 active 时由唯一索引拒绝。"""

    if status not in ("active", "completed", "failed", "superseded"):
        raise ValueError(f"不合法的 attempt 状态: {status}")
    row = conn.execute(
        "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_no FROM upload_attempts "
        "WHERE import_id = ?",
        (import_id,),
    ).fetchone()
    attempt_no = int(row["next_no"])
    conn.execute(
        "INSERT INTO upload_attempts (import_id, attempt_no, status, requested_by) "
        "VALUES (?,?,?,?)",
        (import_id, attempt_no, status, requested_by),
    )
    return conn.execute(
        "SELECT * FROM upload_attempts WHERE import_id = ? AND attempt_no = ?",
        (import_id, attempt_no),
    ).fetchone()


def save_stage_result(
    conn,
    *,
    import_id: str,
    stage: str,
    unit_key: str,
    input_version: int,
    pipeline_version: str,
    status: str,
    result_json: str | None = None,
    output_hash: str | None = None,
    error_code: str | None = None,
    retryable: bool = False,
    job_id: int | None = None,
):
    """持久化一次阶段结果；同一 (import, stage, unit, input_version) 只能成功一次。"""

    if status not in (
        "pending",
        "running",
        "succeeded",
        "skipped",
        "failed",
        "needs_action",
    ):
        raise ValueError(f"不合法的 stage 状态: {status}")
    if status == "skipped" and not error_code:
        raise ValueError("skipped 必须带 reason（记在 error_code）")
    cursor = conn.execute(
        "INSERT INTO upload_stage_results ("
        "  import_id, stage, unit_key, input_version, pipeline_version, status, "
        "  result_json, output_hash, error_code, retryable, job_id"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            import_id,
            stage,
            unit_key,
            input_version,
            pipeline_version,
            status,
            result_json,
            output_hash,
            error_code,
            1 if retryable else 0,
            job_id,
        ),
    )
    return cursor.lastrowid


def get_stage_result(conn, *, import_id: str, stage: str, unit_key: str, input_version: int):
    """读取某版本输入的检查点；不存在返回 None。"""

    return conn.execute(
        "SELECT * FROM upload_stage_results WHERE import_id = ? AND stage = ? "
        "AND unit_key = ? AND input_version = ?",
        (import_id, stage, unit_key, input_version),
    ).fetchone()

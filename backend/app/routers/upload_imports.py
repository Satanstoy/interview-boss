"""上传根任务查询/恢复 API（contracts §4.1）。

- ``GET /api/upload-imports``：本人任务分页，按 created_at DESC。
- ``GET /api/upload-imports/by-key/{key}``：本人按幂等键查询（响应丢失后恢复）；
  **必须注册在 ``/api/upload-imports/{id}`` 之前**。
- ``GET /api/upload-imports/{id}``：本人完整快照；非本人一律 404（含管理员）。
- ``POST /api/upload-imports/{id}/retry``：恢复剩余工作，返回快照与
  ``created_attempt`` 布尔；非本人一律 404（含管理员）。
"""

from __future__ import annotations

import json

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.auth import get_admin_user, get_current_user
from app.db.connection import get_db_connection, run_db
from app.services.upload_lifecycle import UploadRestoreError, restore_upload

router = APIRouter()


def _error_dto(code, message, *, status=None, credential_scope="user", is_admin=False):
    """错误码 → DTO（AC-013）：action/retryable 由统一错误策略映射。"""

    from app.models.upload_contracts import ErrorCode
    from app.services.upload_retry_budget import ERROR_POLICY

    try:
        ErrorCode(code)
    except ValueError:
        code = ErrorCode.INTERNAL_ERROR.value
    policy = ERROR_POLICY.get(code, {})
    scope = policy.get("scope")
    action = policy.get("action")
    if status == "failed" and policy.get("retryable"):
        action = "retry"
    elif status == "partial_failed" and policy.get("retryable"):
        action = "retry_failed_steps"
    elif status in ("queued", "running"):
        action = "view_progress"
    if code in ("MODEL_AUTH_INVALID", "MODEL_CONFIG_MISSING"):
        if credential_scope in ("user", "global"):
            scope = credential_scope
        if scope == "global":
            action = "configure_system_model" if is_admin else "wait_for_global_model"
    return {
        "code": code,
        "message": message or code,
        "retryable": bool(policy.get("retryable", False)),
        "action": action,
        "scope": scope,
    }


def _stage_counts(conn, import_id: str) -> dict:
    """按实际问题结果统计根任务，绝不把阶段检查点行数当题目数。

    - extracted/retained/excluded/needs_review 来自 extract 阶段
      result_json 的「提取计数」（AC-019 守恒计数，节点已持久化）；
    - resolved 是逐题当前 resolution（matched/created）成功数；
    - answered/failed 来自逐题 answer 检查点与旧版答案子 job；
    - total 只有提取计数可用时才有值。
    """

    import json as _json

    # extract 阶段检查点保留的守恒计数（AC-019）；无则回退 0
    extract_row = conn.execute(
        "SELECT result_json FROM upload_stage_results "
        "WHERE import_id = ? AND stage = 'extract' AND status = 'succeeded' "
        "ORDER BY id DESC LIMIT 1",
        (import_id,),
    ).fetchone()
    extracted = retained = excluded = needs_review = 0
    has_extract_count = False
    if extract_row and extract_row["result_json"]:
        try:
            payload = _json.loads(extract_row["result_json"])
            counts = (payload or {}).get("提取计数") or {}
            has_extract_count = "extracted" in counts
            extracted = int(counts.get("extracted", 0))
            retained = int(counts.get("retained", 0))
            excluded = int(counts.get("excluded", 0))
            needs_review = int(counts.get("needs_review", 0))
        except (ValueError, TypeError):
            pass

    # resolved：逐题当前 resolution 成功数（matched/created）
    resolution_rows = conn.execute(
        "SELECT qd.id AS detail_id, qr.canonical_id, qr.status "
        "FROM question_resolutions qr JOIN questions_detail qd ON qd.id = qr.detail_id "
        "WHERE qd.import_id = ? AND qr.invalidated_at IS NULL",
        (import_id,),
    ).fetchall()
    resolved = sum(1 for row in resolution_rows if row["status"] in ("matched", "created"))

    answer_rows = conn.execute(
        "SELECT unit_key, status FROM upload_stage_results "
        "WHERE import_id = ? AND stage = 'answer'",
        (import_id,),
    ).fetchall()
    answered_units = {
        str(row["unit_key"]).removeprefix("answer:")
        for row in answer_rows
        if row["status"] == "succeeded" and str(row["unit_key"]).startswith("answer:")
    }
    failed_units = {
        str(row["unit_key"]).removeprefix("answer:")
        for row in answer_rows
        if row["status"] == "failed" and str(row["unit_key"]).startswith("answer:")
    }
    # Pre-v2 answer jobs did not create root-bound stage rows. Resolve their
    # parent through the durable payload so old in-flight roots remain visible.
    legacy_answer_rows = conn.execute(
        "SELECT json_extract(answer_payload.payload, '$.question_id') AS question_id, "
        "answer_job.status FROM jobs AS answer_job "
        "JOIN job_payloads AS answer_payload ON answer_payload.job_id = answer_job.id "
        "JOIN jobs AS parent_job "
        "ON parent_job.id = json_extract(answer_payload.payload, '$.parent_job_id') "
        "WHERE parent_job.root_import_id = ? AND answer_job.job_type = 'generate_answer' "
        "AND answer_job.status IN ('completed','failed')",
        (import_id,),
    ).fetchall()
    for row in legacy_answer_rows:
        unit = str(row["question_id"])
        if row["status"] == "completed":
            answered_units.add(unit)
            failed_units.discard(unit)
        elif unit not in answered_units:
            failed_units.add(unit)

    failed_resolution_units = {
        f"detail:{row['detail_id']}"
        for row in resolution_rows
        if row["status"] == "failed"
    }
    answered = len(answered_units)
    failed = len(failed_units | failed_resolution_units)

    answer_question_ids = answered_units | failed_units
    resolved_without_answer = sum(
        1
        for row in resolution_rows
        if row["status"] in ("matched", "created")
        and row["canonical_id"] is not None
        and str(row["canonical_id"]) not in answer_question_ids
    )
    completed = answered + failed + resolved_without_answer + excluded
    if has_extract_count:
        completed = min(completed, extracted)
    else:
        completed = 0

    return {
        "total": extracted if has_extract_count else None,
        "completed": completed,
        "answered": answered,
        "failed": failed,
        "extracted": extracted,
        "retained": retained,
        "excluded": excluded,
        "needs_review": needs_review,
        "resolved": int(resolved),
    }


def _snapshot(row, counts=None, conn=None, actor_is_admin=False) -> dict:
    """完整根快照（R04/AC-011）：列表/详情/by-key/retry 共用同一构造。

    GET 与 SSE 统一用 ``snapshot_from_parts``，allowed_actions 由服务端算，
    前端只按服务端授权渲染按钮（无暂停能力绝不出现暂停）。
    ``conn`` 存在时从绑定的公共化申请计算 review_status（AC-010）。
    """

    from app.services.upload_retry_budget import snapshot_from_parts
    from app.services.upload_status import allowed_actions
    from app.services.upload_lifecycle import upload_action_credential_scope

    try:
        policy = json.loads(row["policy_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        policy = {}
    action_scope = upload_action_credential_scope(
        conn,
        import_id=row["id"],
        fallback=policy.get("credential_scope", "user"),
    ) if conn is not None else policy.get("credential_scope", "user")

    review_status = None
    contribution_public_interview_id = None
    if conn is not None and row["contribution_request_id"]:
        review_row = conn.execute(
            "SELECT status, public_interview_id FROM public_contribution_requests WHERE id = ?",
            (row["contribution_request_id"],),
        ).fetchone()
        if review_row:
            review_status = review_row["status"]
            contribution_public_interview_id = review_row["public_interview_id"]

    result_target = None
    if conn is not None and row["interview_id"] is not None:
        result_row = conn.execute(
            "SELECT owner_id, status, publish_status, deleted_at FROM interview WHERE id = ?",
            (row["interview_id"],),
        ).fetchone()
        if result_row and result_row["deleted_at"] is None:
            if result_row["owner_id"] == row["requester_id"]:
                result_target = {
                    "entity_type": "interview",
                    "entity_id": int(row["interview_id"]),
                    "scope": "private",
                }
            elif (
                result_row["owner_id"] is None
                and result_row["status"] == "approved"
                and result_row["publish_status"] == "published"
            ):
                result_target = {
                    "entity_type": "interview",
                    "entity_id": int(row["interview_id"]),
                    "scope": "public",
                }

    if (
        conn is not None
        and contribution_public_interview_id is not None
        and review_status in ("published", "partially_published")
    ):
        public_row = conn.execute(
            "SELECT owner_id, status, publish_status, deleted_at FROM interview WHERE id = ?",
            (contribution_public_interview_id,),
        ).fetchone()
        if (
            public_row
            and public_row["owner_id"] is None
            and public_row["status"] == "approved"
            and public_row["publish_status"] == "published"
            and public_row["deleted_at"] is None
        ):
            result_target = {
                "entity_type": "interview",
                "entity_id": int(contribution_public_interview_id),
                "scope": "public",
            }

    count_values = counts or {
        "total": None,
        "completed": 0,
        "answered": 0,
        "failed": 0,
        "extracted": 0,
        "retained": 0,
        "excluded": 0,
        "needs_review": 0,
        "resolved": 0,
    }
    completed_questions = int(count_values.get("completed", 0) or 0)
    total_questions = count_values.get("total")
    current_stage = None
    if conn is not None:
        active_job = conn.execute(
            "SELECT j.job_type, j.progress_phase FROM jobs j "
            "LEFT JOIN upload_attempts a ON a.id = j.upload_attempt_id "
            "WHERE j.root_import_id = ? AND (a.attempt_no = ? OR j.upload_attempt_id IS NULL) "
            "AND j.status IN ('pending','queued','running') "
            "ORDER BY CASE j.status WHEN 'running' THEN 0 ELSE 1 END, j.id DESC LIMIT 1",
            (row["id"], int(row["current_attempt_no"] or 0)),
        ).fetchone()
        if active_job:
            if active_job["job_type"] == "credential_preflight":
                current_stage = "preflight"
            elif active_job["job_type"] == "cluster_batch":
                current_stage = "cluster"
            elif active_job["job_type"] == "submit_import":
                current_stage = active_job["progress_phase"] or "extract"
        if current_stage is None:
            stage_row = conn.execute(
                "SELECT stage FROM upload_stage_results WHERE import_id = ? "
                "ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'pending' THEN 1 "
                "WHEN 'needs_action' THEN 2 WHEN 'failed' THEN 3 ELSE 4 END, id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            current_stage = stage_row["stage"] if stage_row else None

    try:
        recovery_payload = json.loads(row["payload_json"] or "{}")
    except (json.JSONDecodeError, TypeError):
        recovery_payload = None
    recovery_available = isinstance(recovery_payload, dict) and bool(recovery_payload)
    if recovery_available and row["payload_expires_at"] and conn is not None:
        recovery_available = not bool(
            conn.execute(
                "SELECT datetime(?) <= datetime('now')", (row["payload_expires_at"],)
            ).fetchone()[0]
        )
    recovery_message = None if recovery_available else (
        "原稿已过期，无法从原稿重新处理；请重新提交材料。"
    )
    snapshot_actions = allowed_actions(
        row["status"],
        error_code=row["error_code"],
        has_result=row["interview_id"] is not None,
        credential_scope=action_scope,
        is_admin=bool(actor_is_admin),
    )
    if not recovery_available:
        # AC-007: an owner may retry only while the original input is still
        # available. Expired/cleared payloads must offer a fresh submission,
        # never a retry action that is guaranteed to fail or enqueue nothing.
        snapshot_actions = [
            action for action in snapshot_actions
            if action not in {"retry", "retry_failed_steps", "retry_after_configuration"}
        ]
    if not recovery_available and "resubmit_source" not in snapshot_actions:
        snapshot_actions.append("resubmit_source")
    snapshot = snapshot_from_parts(
        import_id=row["id"],
        revision=int(row["revision"]),
        status=row["status"],
        review_status=review_status,
        target_intent=row["target_intent"],
        attempt_no=int(row["current_attempt_no"]),
        stage=current_stage,
        progress={
            "unit": "questions",
            "completed": completed_questions,
            "total": total_questions,
        },
        counts={
            "extracted": int(count_values.get("extracted", 0)),
            "retained": int(count_values.get("retained", 0)),
            "excluded": int(count_values.get("excluded", 0)),
            "needs_review": int(count_values.get("needs_review", 0)),
            "resolved": int(count_values.get("resolved", 0)),
            "answered": int(count_values.get("answered", 0)),
            "failed": int(count_values.get("failed", 0)),
            "total": total_questions,
        },
        result={
            # contracts §4.2：result 只含 interview_id/position_id/question_ids，
            # 多传字段会被 UploadResultDTO(extra="forbid") 拒绝，导致已完成任务
            # 的列表/详情/by-key/SSE/retry 全部 500。
            "interview_id": row["interview_id"],
            "position_id": row["position_id"],
        }
        if row["interview_id"] is not None
        else None,
        result_target=result_target,
        error=(
            _error_dto(
                row["error_code"],
                row["error_message"] or "",
                status=row["status"],
                credential_scope=action_scope,
                is_admin=bool(actor_is_admin),
            )
            if row["error_code"]
            else None
        ),
        allowed_actions=snapshot_actions,
        recovery_available=recovery_available,
        recovery_message=recovery_message,
        updated_at=row["updated_at"],
    )
    data = snapshot.model_dump(mode="json")
    data.update(
        {
            "import_id": row["id"],
            "position_id": row["position_id"],
            "position_name": row["position_name"],
            "source_type": row["source_type"],
            "resolved_type": row["resolved_type"],
            "input_version": row["input_version"],
            "pipeline_version": row["pipeline_version"],
            "contribution_request_id": row["contribution_request_id"],
            "error": data.get("error"),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }
    )
    return data


def _loads(raw, default=None):
    import json as _json

    try:
        return _json.loads(raw or "null")
    except Exception:
        return default


def _load_owned(conn, import_id: str, user_id: int):
    row = conn.execute(
        "SELECT * FROM upload_imports WHERE id = ? AND requester_id = ?",
        (import_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


@router.get("/api/upload-imports")
async def list_upload_imports(
    user: dict = Depends(get_current_user),
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
):
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    offset = (page - 1) * page_size

    def _query():
        with get_db_connection() as conn:
            where = "requester_id = ?"
            params: list = [user["id"]]
            if status:
                where += " AND status = ?"
                params.append(status)
            total = conn.execute(
                f"SELECT COUNT(*) FROM upload_imports WHERE {where}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM upload_imports WHERE {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (*params, page_size, offset),
            ).fetchall()
            return {
                "items": [
                    _snapshot(
                        row,
                        counts=_stage_counts(conn, str(row["id"])),
                        conn=conn,
                        actor_is_admin=bool(user.get("is_admin")),
                    )
                    for row in rows
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    return await run_db(_query)


# 注意：静态路径必须先于 /{id} 注册，否则 "by-key" 会被当作 import_id。
@router.get("/api/upload-imports/by-key/{idempotency_key}")
async def get_upload_import_by_key(idempotency_key: str, user: dict = Depends(get_current_user)):
    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM upload_imports WHERE requester_id = ? AND idempotency_key = ?",
                (user["id"], idempotency_key),
            ).fetchone()
            return (
                _snapshot(
                    row,
                    counts=_stage_counts(conn, str(row["id"])),
                    conn=conn,
                    actor_is_admin=bool(user.get("is_admin")),
                )
                if row is not None
                else None
            )

    snapshot = await run_db(_query)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return snapshot


@router.get("/api/upload-imports/{import_id}")
async def get_upload_import(import_id: str, user: dict = Depends(get_current_user)):
    def _query():
        with get_db_connection() as conn:
            return _snapshot(
                _load_owned(conn, import_id, user["id"]),
                counts=_stage_counts(conn, import_id),
                conn=conn,
                actor_is_admin=bool(user.get("is_admin")),
            )

    return await run_db(_query)


OPERATION_FIELDS = (
    "import_id",
    "job_type",
    "scope",
    "status",
    "stage",
    "attempt_no",
    "duration_ms",
    "error_code",
    "next_retry_at",
    "credential_scope",
    "provider",
    "model",
    "created_at",
    "updated_at",
)


@router.get("/api/admin/upload-operations")
async def list_upload_operations(
    user: dict = Depends(get_admin_user),
    page: int = 1,
    page_size: int = 20,
):
    """运维白名单：只暴露状态与配置指纹，绝不返回正文/公司/来源/Key（AC-018）。"""

    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    offset = (page - 1) * page_size

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT i.id AS import_id,
                       COALESCE(j.job_type, 'submit_import') AS job_type,
                       CASE WHEN json_extract(i.policy_json, '$.write_scope') = 'public'
                            THEN 'public' ELSE 'user' END AS scope,
                       i.status AS status,
                       COALESCE(j.progress_phase, '') AS stage,
                       i.current_attempt_no AS attempt_no,
                       CAST((julianday(COALESCE(i.completed_at, i.updated_at))
                             - julianday(i.created_at)) * 86400000 AS INTEGER) AS duration_ms,
                       COALESCE(i.error_code, '') AS error_code,
                       COALESCE(j.available_at, '') AS next_retry_at,
                       COALESCE(json_extract(i.policy_json, '$.credential_scope'), '') AS credential_scope,
                       COALESCE((SELECT c.provider FROM upload_llm_calls c
                                 WHERE c.root_import_id = i.id ORDER BY c.id DESC LIMIT 1), '') AS provider,
                       COALESCE((SELECT c.model FROM upload_llm_calls c
                                 WHERE c.root_import_id = i.id ORDER BY c.id DESC LIMIT 1), '') AS model,
                       i.created_at AS created_at,
                       i.updated_at AS updated_at
                FROM upload_imports i
                LEFT JOIN jobs j ON j.root_import_id = i.id
                ORDER BY i.created_at DESC, i.id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0]
            return {
                "items": [{field: row[field] for field in OPERATION_FIELDS} for row in rows],
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    return await run_db(_query)


TERMINAL_STATUSES = ("completed", "failed", "partial_failed", "needs_action", "waiting_review")
SNAPSHOT_POLL_SECONDS = 2
SNAPSHOT_HEARTBEAT_SECONDS = 15


@router.get("/api/upload-imports/{import_id}/stream")
async def stream_upload_import(import_id: str, user: dict = Depends(get_current_user)):
    """SSE 快照流（AC-010/013）：先发完整快照，2 秒轮询、15 秒心跳。

    授权在响应流开始前检查；非终态由客户端决定是否重连。
    """

    def _authorize():
        with get_db_connection() as conn:
            return _load_owned(conn, import_id, user["id"])

    await run_db(_authorize)  # 无权立即 404，不进入流

    from app.models.upload_contracts import UploadSnapshot
    from app.services.upload_retry_budget import build_snapshot_event

    def _snapshot_stream():
        with get_db_connection() as conn:
            row = _load_owned(conn, import_id, user["id"])
            return _snapshot(
                row,
                counts=_stage_counts(conn, import_id),
                conn=conn,
                actor_is_admin=bool(user.get("is_admin")),
            )

    async def event_stream():
        last_revision = -1
        beats = 0
        while True:
            snap_data = await run_db(_snapshot_stream)
            revision = int(snap_data["revision"])
            if revision > last_revision:
                last_revision = revision
                snapshot_payload = {
                    field: snap_data[field]
                    for field in UploadSnapshot.model_fields
                    if field in snap_data
                }
                snapshot_obj = UploadSnapshot(**snapshot_payload)
                event = build_snapshot_event(snapshot_obj)
                yield (
                    f"event: snapshot\nid: {event['id']}\n"
                    f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                )
            status = snap_data["status"]
            if status in TERMINAL_STATUSES:
                return
            beats += 1
            if beats % (SNAPSHOT_HEARTBEAT_SECONDS // SNAPSHOT_POLL_SECONDS) == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(SNAPSHOT_POLL_SECONDS)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@router.post("/api/upload-imports/{import_id}/retry")
async def retry_upload_import(import_id: str, user: dict = Depends(get_current_user)):
    """恢复剩余工作（contracts §4.1）：返回根快照与 ``created_attempt`` 布尔。

    只重建未完成/失败/失效的工作；已成功阶段由 worker 复用检查点。
    非本人一律 404（含管理员，AC-018）；原文已删除返回 409 SOURCE_DELETED。
    """

    def _retry():
        with get_db_connection() as conn:
            # 权限即“归属即存在”：非本人一律 404，不泄露他人任务存在性
            _load_owned(conn, import_id, user["id"])
            conn.execute("BEGIN IMMEDIATE")
            try:
                restored = restore_upload(
                    conn,
                    actor_id=user["id"],
                    import_id=import_id,
                )
                row = conn.execute(
                    "SELECT * FROM upload_imports WHERE id = ?", (import_id,)
                ).fetchone()
                conn.commit()
            except UploadRestoreError as exc:
                conn.rollback()
                status_code = (
                    409
                    if exc.code
                    in (
                        "SOURCE_DELETED",
                        "SOURCE_EXPIRED",
                        "POSITION_RETIRED",
                        "TAXONOMY_CHANGED",
                        "PIPELINE_VERSION_UNSUPPORTED",
                        "LEGACY_MAPPING_AMBIGUOUS",
                    )
                    else 404
                )
                raise HTTPException(
                    status_code=status_code,
                    detail=f"{exc.code}: {exc}",
                ) from None
            except Exception:
                conn.rollback()
                raise

            snapshot = _snapshot(
                row,
                counts=_stage_counts(conn, import_id),
                conn=conn,
                actor_is_admin=bool(user.get("is_admin")),
            )
            snapshot.update(
                {
                    "created_attempt": restored["created_attempt"],
                    "status_url": restored["status_url"],
                }
            )
            return snapshot

    return await run_db(_retry)

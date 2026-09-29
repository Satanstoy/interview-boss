"""上传根任务查询 API（contracts §4.1）。

- ``GET /api/upload-imports``：本人任务分页，按 created_at DESC。
- ``GET /api/upload-imports/by-key/{key}``：本人按幂等键查询（响应丢失后恢复）；
  **必须注册在 ``/api/upload-imports/{id}`` 之前**。
- ``GET /api/upload-imports/{id}``：本人完整快照；非本人一律 404（含管理员）。
"""

from __future__ import annotations

import json

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.auth import get_admin_user, get_current_user
from app.db.connection import get_db_connection, run_db

router = APIRouter()


def _snapshot(row) -> dict:
    return {
        "import_id": row["id"],
        "revision": row["revision"],
        "status": row["status"],
        "target_intent": row["target_intent"],
        "source_type": row["source_type"],
        "resolved_type": row["resolved_type"],
        "position_id": row["position_id"],
        "position_name": row["position_name"],
        "input_version": row["input_version"],
        "pipeline_version": row["pipeline_version"],
        "attempt_no": row["current_attempt_no"],
        "interview_id": row["interview_id"],
        "contribution_request_id": row["contribution_request_id"],
        "error": (
            {"code": row["error_code"], "message": row["error_message"]}
            if row["error_code"]
            else None
        ),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


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
                "items": [_snapshot(row) for row in rows],
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
            return _snapshot(row) if row is not None else None

    snapshot = await run_db(_query)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return snapshot


@router.get("/api/upload-imports/{import_id}")
async def get_upload_import(import_id: str, user: dict = Depends(get_current_user)):
    def _query():
        with get_db_connection() as conn:
            return _snapshot(_load_owned(conn, import_id, user["id"]))

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

    from app.services.upload_retry_budget import build_snapshot_event, snapshot_from_parts

    def _snapshot():
        with get_db_connection() as conn:
            row = _load_owned(conn, import_id, user["id"])
            counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS answered, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed "
                "FROM upload_stage_results WHERE import_id = ?",
                (import_id,),
            ).fetchone()
            return snapshot_from_parts(
                import_id=row["id"],
                revision=int(row["revision"]),
                status=row["status"],
                target_intent=row["target_intent"],
                attempt_no=int(row["current_attempt_no"]),
                counts={
                    "total": int(counts["total"] or 0),
                    "answered": int(counts["answered"] or 0),
                    "failed": int(counts["failed"] or 0),
                },
                error=(
                    {"code": row["error_code"], "message": row["error_message"] or "", "retryable": False}
                    if row["error_code"]
                    else None
                ),
                updated_at=row["updated_at"],
            )

    async def event_stream():
        last_revision = -1
        beats = 0
        while True:
            snapshot = await run_db(_snapshot)
            if int(snapshot.revision) > last_revision:
                last_revision = int(snapshot.revision)
                event = build_snapshot_event(snapshot)
                yield (
                    f"event: snapshot\nid: {event['id']}\n"
                    f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                )
            if snapshot.status.value in TERMINAL_STATUSES:
                return
            beats += 1
            if beats % (SNAPSHOT_HEARTBEAT_SECONDS // SNAPSHOT_POLL_SECONDS) == 0:
                yield ": heartbeat\n\n"
            await asyncio.sleep(SNAPSHOT_POLL_SECONDS)

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )

"""上传根任务查询 API（contracts §4.1）。

- ``GET /api/upload-imports``：本人任务分页，按 created_at DESC。
- ``GET /api/upload-imports/by-key/{key}``：本人按幂等键查询（响应丢失后恢复）；
  **必须注册在 ``/api/upload-imports/{id}`` 之前**。
- ``GET /api/upload-imports/{id}``：本人完整快照；非本人一律 404（含管理员）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
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

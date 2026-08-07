"""来源健康 API（管理员）：同签名重复公共面经的列表与合并。

检测逻辑在 `app.services.source_health`，合并逻辑在
`app.services.interview_merge_service`，本路由仅做 HTTP 感知。

只处理公共面经（owner_id IS NULL）；私有面经不展示、不合并。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_admin_user
from app.db.connection import get_db_connection
from app.services.interview_merge_service import (
    list_duplicate_groups,
    merge_duplicate_group,
)

logger = logging.getLogger("interview-boss")

router = APIRouter(prefix="/api/admin/source-health", tags=["admin-source-health"])


@router.get("/duplicate-groups")
async def duplicate_groups(
    table: str = Query("interview", pattern="^(interview|jd)$"),
    admin: dict = Depends(get_admin_user),
):
    """列出同签名重复的公共面经组（signature/count/keep_id/records）。"""

    def _query():
        conn = get_db_connection()
        return list_duplicate_groups(conn, table)

    return await run_in_threadpool(_query)


@router.post("/duplicate-groups/merge")
async def merge_group(
    body: dict,
    admin: dict = Depends(get_admin_user),
):
    """合并指定签名的重复公共记录组（默认 dry_run 预览，前端确认后 dry_run=false）。"""
    signature = (body.get("signature") or "").strip()
    table = body.get("table", "interview")
    dry_run = bool(body.get("dry_run", True))

    if not signature:
        raise HTTPException(status_code=400, detail="signature 不能为空")
    if table not in ("interview", "jd"):
        raise HTTPException(status_code=400, detail="不支持的表类型，仅支持 interview 和 jd")

    def _merge():
        conn = get_db_connection()
        return merge_duplicate_group(conn, signature, table=table, dry_run=dry_run)

    return await run_in_threadpool(_merge)

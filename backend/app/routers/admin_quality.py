"""聚合质量审查清单 API（管理员）：清单查询 / 审批 / 批量审批。

清单数据固化在 quality_issue 表（审查生成，永不删除），管理员审批后
执行对应操作（split/dedupe/refine_representative），状态流转留痕。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_admin_user
from app.db.connection import get_db_connection

logger = logging.getLogger("interview-boss")

router = APIRouter(prefix="/api/admin/quality-issues", tags=["admin-quality"])

# issue_type → 操作名映射（供前端展示）
ISSUE_TYPE_LABELS = {
    "mismerge": "误合并",
    "duplicate": "重复变体",
    "weak_representative": "代表题过弱",
}
ACTION_LABELS = {
    "split": "拆出变体",
    "dedupe": "去重变体",
    "refine_representative": "精炼代表题",
}


def _serialize_issue(row, conn) -> dict:
    qb = conn.execute(
        "SELECT question, cat2, original_questions FROM question_bank WHERE id = ?",
        (row["qb_id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "qb_id": row["qb_id"],
        "question": qb["question"] if qb else "",
        "cat2": qb["cat2"] if qb else "",
        "variant_index": row["variant_index"],
        "variant": (
            None
            if (not qb or row["variant_index"] is None)
            else (
                json_loads(qb["original_questions"])[row["variant_index"]]
                if qb["original_questions"]
                else None
            )
        ),
        "issue_type": row["issue_type"],
        "issue_type_label": ISSUE_TYPE_LABELS.get(row["issue_type"], row["issue_type"]),
        "suggested_action": row["suggested_action"],
        "action_label": ACTION_LABELS.get(row["suggested_action"], row["suggested_action"]),
        "reason": row["reason"],
        "suggested_value": row["suggested_value"],
        "confidence": row["confidence"],
        "status": row["status"],
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }


def json_loads(raw):
    import json

    try:
        return json.loads(raw)
    except Exception:
        return []


@router.get("")
async def list_issues(
    status: str = Query("pending", pattern="^(pending|approved|rejected|done)$"),
    admin: dict = Depends(get_admin_user),
):
    """查询审查清单（默认 pending 待审批；done/rejected 历史审计）"""

    def _query():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM quality_issue WHERE status = ? ORDER BY confidence DESC, id",
            (status,),
        ).fetchall()
        return [_serialize_issue(r, conn) for r in rows]

    return await run_in_threadpool(_query)


def _execute_issue(conn, issue) -> None:
    """按 issue 建议执行操作（执行前重检：数据可能已被其他审批修改）。"""
    from app.services.clustering_maintenance import (
        split_variant,
        dedupe_variant,
        refine_representative,
    )

    action = issue["suggested_action"]
    if action == "split":
        new_id = split_variant(conn, issue["qb_id"], issue["variant_index"])
        if new_id is None:
            raise HTTPException(status_code=409, detail="变体已不存在（可能已被处理）")
    elif action == "dedupe":
        removed = dedupe_variant(conn, issue["qb_id"], [issue["variant_index"]])
        if removed == 0:
            raise HTTPException(status_code=409, detail="变体已不存在（可能已被处理）")
    elif action == "refine_representative":
        ok = refine_representative(conn, issue["qb_id"], issue["suggested_value"])
        if not ok:
            raise HTTPException(status_code=409, detail="代表题已变更（可能已被处理）")
    else:
        raise HTTPException(status_code=400, detail=f"未知操作: {action}")


@router.post("/{issue_id}/approve")
async def approve_issue(
    issue_id: int,
    admin: dict = Depends(get_admin_user),
):
    """批准 issue：执行对应操作，状态 pending → done（记录审批人）"""

    def _approve():
        conn = get_db_connection()
        issue = conn.execute(
            "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending'",
            (issue_id,),
        ).fetchone()
        if not issue:
            raise HTTPException(status_code=404, detail="issue 不存在或已处理")
        _execute_issue(conn, issue)
        conn.execute(
            "UPDATE quality_issue SET status = 'done', reviewed_at = datetime('now'), "
            "reviewed_by = ? WHERE id = ?",
            (admin["id"], issue_id),
        )
        conn.commit()
        return {"id": issue_id, "status": "done"}

    return await run_in_threadpool(_approve)


@router.post("/{issue_id}/reject")
async def reject_issue(
    issue_id: int,
    admin: dict = Depends(get_admin_user),
):
    """拒绝 issue：记录拒绝（保留为负样本），不执行操作"""

    def _reject():
        conn = get_db_connection()
        cur = conn.execute(
            "UPDATE quality_issue SET status = 'rejected', reviewed_at = datetime('now'), "
            "reviewed_by = ? WHERE id = ? AND status = 'pending'",
            (admin["id"], issue_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="issue 不存在或已处理")
        return {"id": issue_id, "status": "rejected"}

    return await run_in_threadpool(_reject)


@router.post("/batch-approve")
async def batch_approve_issues(
    body: dict,
    admin: dict = Depends(get_admin_user),
):
    """批量批准高置信 issue（>0.85）：逐个执行，失败的跳过并返回结果。"""
    issue_ids = body.get("issue_ids", [])
    min_confidence = float(body.get("min_confidence", 0.85))
    if not isinstance(issue_ids, list) or not issue_ids:
        raise HTTPException(status_code=400, detail="issue_ids 不能为空")

    def _batch():
        conn = get_db_connection()
        done, failed = [], []
        for iid in issue_ids:
            issue = conn.execute(
                "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending' "
                "AND confidence >= ?",
                (iid, min_confidence),
            ).fetchone()
            if not issue:
                failed.append({"id": iid, "reason": "不存在/已处理/置信度不足"})
                continue
            try:
                _execute_issue(conn, issue)
                conn.execute(
                    "UPDATE quality_issue SET status = 'done', reviewed_at = datetime('now'), "
                    "reviewed_by = ? WHERE id = ?",
                    (admin["id"], iid),
                )
                conn.commit()
                done.append(iid)
            except HTTPException as e:
                conn.rollback()
                failed.append({"id": iid, "reason": e.detail})
            except Exception as e:
                conn.rollback()
                logger.warning(f"[清单] 批量审批 {iid} 失败: {e}")
                failed.append({"id": iid, "reason": str(e)[:100]})
        return {"approved": done, "failed": failed}

    return await run_in_threadpool(_batch)

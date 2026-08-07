"""聚合质量审查清单业务逻辑（quality_issue 表）。

从 `routers/admin_quality.py` 抽出的共享逻辑：清单序列化、执行分派、
单条/批量审批（管理员确认后落库并留痕 reviewed_by）。

本模块是 `admin_quality` 路由与「管理员 AI 助手」确认路径共用的一份实现，
避免重复实现导致行为漂移。改动时两处调用方同步受益。
"""
import json
import logging

from fastapi import HTTPException

logger = logging.getLogger("interview-boss")

# issue_type → 操作名映射（供前端/助手展示，人话命名，避免内部术语）
ISSUE_TYPE_LABELS = {
    "mismerge": "误合并",
    "duplicate": "重复问法",
    "weak_representative": "代表题不规范",
}
ACTION_LABELS = {
    "split": "拆成独立题",
    "dedupe": "移除重复问法",
    "refine_representative": "换成规范题面",
    "merge": "并入到其他题",
}


def json_loads(raw):
    try:
        return json.loads(raw)
    except Exception:
        return []


def serialize_issue(row, conn) -> dict:
    qb = conn.execute(
        "SELECT question, cat2, original_questions FROM question_bank WHERE id = ?",
        (row["qb_id"],),
    ).fetchone()
    # 并入目标题（target_qb_id）对应的代表题（用于卡片「目标题」对照）
    target_qb = None
    if row["target_qb_id"] is not None:
        target_qb = conn.execute(
            "SELECT question FROM question_bank WHERE id = ?", (row["target_qb_id"],)
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
        "target_qb_id": row["target_qb_id"],
        "target_question": target_qb["question"] if target_qb else None,
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
    }


def execute_issue(conn, issue) -> None:
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


def list_issues(conn, status: str = "pending") -> list[dict]:
    """列出指定状态的审查清单（默认 pending 待审批）。"""
    rows = conn.execute(
        "SELECT * FROM quality_issue WHERE status = ? ORDER BY confidence DESC, id",
        (status,),
    ).fetchall()
    return [serialize_issue(r, conn) for r in rows]


def review_issue(conn, issue_id: int) -> dict | None:
    """单个问题完整详情（不存在返回 None）。"""
    row = conn.execute(
        "SELECT * FROM quality_issue WHERE id = ?", (issue_id,)
    ).fetchone()
    if not row:
        return None
    return serialize_issue(row, conn)


def approve_issue(conn, admin_id: int, issue_id: int, min_confidence: float | None = None) -> dict:
    """批准 issue：执行对应操作，状态 pending → done（记录审批人）。

    min_confidence 给定则 SQL 加置信度下限（管理员助手确认路径传 0.85；
    现有单条审批接口传 None 保持「不过滤置信度」的既有行为）。
    """
    sql = "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending'"
    params: list = [issue_id]
    if min_confidence is not None:
        sql += " AND confidence >= ?"
        params.append(min_confidence)
    issue = conn.execute(sql, params).fetchone()
    if not issue:
        raise HTTPException(status_code=404, detail="issue 不存在或已处理")
    execute_issue(conn, issue)
    conn.execute(
        "UPDATE quality_issue SET status = 'done', reviewed_at = datetime('now'), "
        "reviewed_by = ? WHERE id = ?",
        (admin_id, issue_id),
    )
    conn.commit()
    return {
        "id": issue_id,
        "status": "done",
        "suggested_action": issue["suggested_action"],
        "issue_type": issue["issue_type"],
        "confidence": issue["confidence"],
    }


def reject_issue(conn, admin_id: int, issue_id: int) -> dict:
    """拒绝 issue：记录拒绝（保留为负样本），不执行操作。"""
    cur = conn.execute(
        "UPDATE quality_issue SET status = 'rejected', reviewed_at = datetime('now'), "
        "reviewed_by = ? WHERE id = ? AND status = 'pending'",
        (admin_id, issue_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="issue 不存在或已处理")
    return {"id": issue_id, "status": "rejected"}


def batch_approve(conn, admin_id: int, issue_ids: list[int], min_confidence: float = 0.85) -> dict:
    """批量批准高置信 issue：置信度下限强制 max(0.85, 传入)，逐个执行，失败跳过。"""
    floor = max(0.85, float(min_confidence or 0.85))
    done, failed = [], []
    for iid in issue_ids:
        issue = conn.execute(
            "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending' "
            "AND confidence >= ?",
            (iid, floor),
        ).fetchone()
        if not issue:
            failed.append({"id": iid, "reason": "不存在/已处理/置信度不足"})
            continue
        try:
            execute_issue(conn, issue)
            conn.execute(
                "UPDATE quality_issue SET status = 'done', reviewed_at = datetime('now'), "
                "reviewed_by = ? WHERE id = ?",
                (admin_id, iid),
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

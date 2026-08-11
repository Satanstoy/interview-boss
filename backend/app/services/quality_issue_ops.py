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
    "unmerged": "漏合并",
    "duplicate": "重复问法",
    "weak_representative": "代表题不规范",
    "new_representative": "代表题不规范",
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


def _historical_merged_question(
    conn, source_qb_id: int, target_qb_id: int | None
) -> str | None:
    """从合并历史恢复旧 issue 的来源题文本。

    migration 073 之前的 issue 没有保存原题快照；漏合并执行时，
    ``merge_history.merged_questions`` 仍保留被删除来源题的文本。
    """
    if target_qb_id is None:
        return None
    try:
        rows = conn.execute(
            "SELECT merged_ids, merged_questions FROM merge_history "
            "WHERE survivor_id = ? ORDER BY id DESC",
            (target_qb_id,),
        ).fetchall()
    except Exception:
        return None

    for history in rows:
        merged_ids = json_loads(history["merged_ids"])
        merged_questions = json_loads(history["merged_questions"])
        if not isinstance(merged_ids, list) or not isinstance(merged_questions, list):
            continue
        for index, merged_id in enumerate(merged_ids):
            if str(merged_id) == str(source_qb_id) and index < len(merged_questions):
                question = str(merged_questions[index] or "").strip()
                if question:
                    return question
    return None


def serialize_issue(row, conn) -> dict:
    qb = conn.execute(
        "SELECT question, cat2, original_questions FROM question_bank WHERE id = ?",
        (row["qb_id"],),
    ).fetchone()
    # 并入目标题（target_qb_id）对应的代表题（用于卡片「目标题」对照）
    target_qb = None
    if row["target_qb_id"] is not None:
        target_qb = conn.execute(
            "SELECT question, cat2 FROM question_bank WHERE id = ?", (row["target_qb_id"],)
        ).fetchone()
    source_question = (
        row["source_question"]
        if "source_question" in row.keys() and row["source_question"]
        else None
    )
    source_cat2 = (
        row["source_cat2"]
        if "source_cat2" in row.keys() and row["source_cat2"] is not None
        else None
    )
    historical_question = None
    if not qb:
        historical_question = _historical_merged_question(
            conn, row["qb_id"], row["target_qb_id"]
        )
    variants = json_loads(qb["original_questions"]) if qb and qb["original_questions"] else []
    variant_index = row["variant_index"]
    variant_stale = bool(
        qb
        and variant_index is not None
        and not (0 <= variant_index < len(variants))
    )

    return {
        "id": row["id"],
        "qb_id": row["qb_id"],
        "question": (
            qb["question"] if qb else (source_question or historical_question or "")
        ),
        "cat2": qb["cat2"] if qb else (source_cat2 or ""),
        "source_question": source_question or historical_question,
        "source_cat2": source_cat2,
        "new_cat2": row["new_cat2"] if "new_cat2" in row.keys() else None,
        "original_questions": (
            json_loads(qb["original_questions"]) if qb and qb["original_questions"] else []
        ),
        "variant_index": row["variant_index"],
        "variant": (
            None
            if (not qb or variant_index is None or variant_stale)
            else (variants[variant_index] if variants else None)
        ),
        "variant_stale": variant_stale,
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
        "target_cat2": target_qb["cat2"] if target_qb else None,
        "created_at": row["created_at"],
        "reviewed_at": row["reviewed_at"],
        "review_version": row["review_version"] if "review_version" in row.keys() else None,
        "review_task_id": row["review_task_id"] if "review_task_id" in row.keys() else None,
        "trigger_reason": row["trigger_reason"] if "trigger_reason" in row.keys() else None,
    }


def _assert_issue_version_current(conn, issue) -> None:
    """Reject a versioned stale suggestion before any cluster mutation."""
    review_version = issue["review_version"] if "review_version" in issue.keys() else None
    if not review_version:
        # Legacy rows predate version tracking.  They remain reviewable for
        # backwards compatibility; their mutation itself creates a new version.
        return
    from app.services.cluster_review_lifecycle import get_current_cluster_version

    current = get_current_cluster_version(conn, issue["qb_id"])
    if current != review_version:
        raise HTTPException(status_code=409, detail="审核建议已过期，请刷新后重新审核")


def execute_issue(conn, issue, operator_id: int | None = None) -> None:
    """按 issue 建议执行操作（执行前重检：数据可能已被其他审批修改）。"""
    from app.services.clustering_maintenance import (
        split_variant,
        dedupe_variant,
        refine_representative,
        merge_variant,
    )
    from app.services.unmerged_quality import merge_question

    _assert_issue_version_current(conn, issue)

    action = issue["suggested_action"]
    if action == "split":
        # split 时新题代表题用 LLM 预生成的重写题面（suggested_value），原问法降为新题问法；
        # 新题分类用 LLM 判定的 new_cat2（不继承原题，误合并常因跨领域）
        try:
            new_id = split_variant(
                conn, issue["qb_id"], issue["variant_index"],
                new_representative=issue["suggested_value"],
                new_cat2=issue["new_cat2"],
            )
        except Exception as exc:
            from app.services.question_variant_reconciliation import (
                VariantOwnershipConflict,
            )

            if isinstance(exc, VariantOwnershipConflict):
                raise HTTPException(
                    status_code=409,
                    detail="该原始题目已存在其他独立题簇，请使用归属修复而不是再次拆分",
                ) from exc
            raise
        if new_id is None:
            raise HTTPException(status_code=409, detail="变体已不存在（可能已被处理）")
    elif action == "merge":
        # variant_index 为空表示漏合并清单：整道来源题并入目标题；
        # 有 index 则保持原有误合并变体迁移语义。
        if issue["variant_index"] is None:
            ok = merge_question(
                conn,
                issue["qb_id"],
                issue["target_qb_id"],
                confidence=issue["confidence"] or 0,
                operator_id=operator_id,
            )
        else:
            ok = merge_variant(
                conn, issue["qb_id"], issue["variant_index"], issue["target_qb_id"]
            )
        if not ok:
            raise HTTPException(status_code=409, detail="变体/目标题不存在（可能已被处理）")
    elif action == "dedupe":
        removed = dedupe_variant(conn, issue["qb_id"], [issue["variant_index"]])
        if removed == 0:
            raise HTTPException(status_code=409, detail="变体已不存在（可能已被处理）")
    elif action == "refine_representative":
        try:
            ok = refine_representative(conn, issue["qb_id"], issue["suggested_value"])
        except Exception as exc:
            from app.services.question_variant_reconciliation import (
                VariantOwnershipConflict,
            )

            if isinstance(exc, VariantOwnershipConflict):
                raise HTTPException(
                    status_code=409,
                    detail="代表题修订会重新占用已归属其他题簇的原始题目，请先执行归属修复",
                ) from exc
            raise
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
    try:
        execute_issue(conn, issue, operator_id=admin_id)
        conn.execute(
            "UPDATE quality_issue SET status = 'done', reviewed_at = datetime('now'), "
            "reviewed_by = ? WHERE id = ?",
            (admin_id, issue_id),
        )
        conn.commit()
    except Exception:
        # Approval is one logical mutation: a partial split/merge must never
        # remain open on the thread-local SQLite connection for the next task.
        conn.rollback()
        raise
    return {
        "id": issue_id,
        "status": "done",
        "suggested_action": issue["suggested_action"],
        "issue_type": issue["issue_type"],
        "confidence": issue["confidence"],
    }


def reject_issue(conn, admin_id: int, issue_id: int) -> dict:
    """拒绝 issue：记录拒绝（保留为负样本），不执行操作。"""
    issue_before = conn.execute(
        "SELECT * FROM quality_issue WHERE id = ? AND status = 'pending'",
        (issue_id,),
    ).fetchone()
    if not issue_before:
        raise HTTPException(status_code=404, detail="issue 不存在或已处理")
    _assert_issue_version_current(conn, issue_before)
    try:
        cur = conn.execute(
            "UPDATE quality_issue SET status = 'rejected', reviewed_at = datetime('now'), "
            "reviewed_by = ? WHERE id = ? AND status = 'pending'",
            (admin_id, issue_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="issue 不存在或已处理")
        # 拒绝是对当前版本的人工作答复；只有该聚类没有其它待审建议时，
        # 才把状态推进到 passed。若它仍有其他清单项，则继续 needs_human。
        issue = conn.execute(
            "SELECT qb_id, review_version FROM quality_issue WHERE id = ?", (issue_id,)
        ).fetchone()
        if issue:
            from app.services.cluster_review_lifecycle import get_current_cluster_version

            current = get_current_cluster_version(conn, issue["qb_id"])
            pending = conn.execute(
                "SELECT COUNT(*) FROM quality_issue WHERE qb_id = ? "
                "AND status IN ('pending', 'approved')",
                (issue["qb_id"],),
            ).fetchone()[0]
            if current and not pending:
                conn.execute(
                    "UPDATE cluster_review_state SET status = 'passed', reviewed_version = ?, "
                    "last_reviewed_at = datetime('now'), updated_at = datetime('now') "
                    "WHERE cluster_id = ? AND current_version = ?",
                    (current, issue["qb_id"], current),
                )
    except Exception:
        conn.rollback()
        raise
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
            execute_issue(conn, issue, operator_id=admin_id)
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

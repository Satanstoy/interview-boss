import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/master-bank")


@router.get("/analysis-status")
async def analysis_status(user: dict = Depends(get_admin_user)):
    """检查面经分析完整性：返回已分析和未分析的面经数量及详情。"""

    def _check():
        with get_db_connection() as conn:
            # 已分析：有 detail 记录的面经
            analyzed = conn.execute(
                "SELECT i.id, i.company, i.round FROM interview i "
                "WHERE i.deleted_at IS NULL AND EXISTS (SELECT 1 FROM questions_detail qd WHERE qd.url = i.url)"
            ).fetchall()
            # 未分析：没有 detail 记录的面经
            unanalyzed = conn.execute(
                "SELECT i.id, i.company, i.round, LENGTH(i.questions_list) as ql_len FROM interview i "
                "WHERE i.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM questions_detail qd WHERE qd.url = i.url)"
            ).fetchall()
            return {
                "analyzed_count": len(analyzed),
                "unanalyzed_count": len(unanalyzed),
                "unanalyzed": [
                    {
                        "id": r["id"],
                        "company": r["company"],
                        "round": r["round"],
                        "has_content": (r["ql_len"] or 0) > 10,
                    }
                    for r in unanalyzed
                ],
            }

    return await run_db(_check)


@router.get("/pending")
async def get_pending_questions(admin: dict = Depends(get_admin_user)):
    """获取待审核题目列表"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, qb.created_at, u.username as submitted_by_name "
                "FROM question_bank qb LEFT JOIN users u ON qb.submitted_by = u.id "
                "WHERE qb.owner_id IS NULL AND qb.status = 'pending' ORDER BY qb.created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    items = await run_db(_query)
    return {"items": items, "total": len(items)}


def _approve_cleanup_private_copy(conn, pending_id: int) -> None:
    """审核批准后清理：删除分享者同题的私有副本（分享时保留的）。

    匹配条件：owner_id = pending.submitted_by 且归一化文本相同。
    """
    pending = conn.execute(
        "SELECT id, question, submitted_by FROM question_bank WHERE id = ?",
        (pending_id,),
    ).fetchone()
    if not pending or not pending["submitted_by"]:
        return
    from app.routers.questions_pkg.share import _normalize_question_text

    target_norm = _normalize_question_text(pending["question"])
    if not target_norm:
        return
    rows = conn.execute(
        "SELECT id, question FROM question_bank "
        "WHERE owner_id = ? AND deleted_at IS NULL",
        (pending["submitted_by"],),
    ).fetchall()
    for r in rows:
        if _normalize_question_text(r["question"]) == target_norm:
            conn.execute(
                "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (r["id"],),
            )
            break


@router.post("/approve/{question_id}")
async def approve_question(question_id: int, admin: dict = Depends(get_admin_user)):
    """审核通过题目（批准后清理分享者的私有副本，duplicate_of 镜像机制已废除）"""

    def _approve():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, status, cat2, job_position, submitted_by FROM question_bank WHERE id = ? AND owner_id IS NULL",
                (question_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该待审核题目")
            conn.execute(
                "UPDATE question_bank SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (question_id,),
            )
            # 分享链路：批准后删除分享者保留的私有副本
            if row["submitted_by"]:
                _approve_cleanup_private_copy(conn, question_id)
            conn.commit()
            return dict(row)

    question = await run_db(_approve)
    return {"status": "success", "message": "已通过审核"}


@router.post("/reject/{question_id}")
async def reject_question(question_id: int, admin: dict = Depends(get_admin_user)):
    """拒绝题目"""

    def _reject():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, status FROM question_bank WHERE id = ? AND owner_id IS NULL",
                (question_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该待审核题目")
            conn.execute(
                "UPDATE question_bank SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (question_id,),
            )
            conn.commit()

    await run_db(_reject)
    return {"status": "success", "message": "已拒绝"}


# ──────────────────────────── 合并历史与回滚 API ────────────────────────────


@router.get("/merge-history")
async def get_merge_history(
    limit: int = 50,
    offset: int = 0,
    cat2: str = None,
    is_rolled_back: int = None,
    admin: dict = Depends(get_admin_user),
):
    """获取合并历史列表（管理员）"""

    def _query():
        with get_db_connection() as conn:
            where = ["1=1"]
            params = []
            if cat2:
                where.append("mh.cat2 = ?")
                params.append(cat2)
            if is_rolled_back is not None:
                where.append("mh.is_rolled_back = ?")
                params.append(is_rolled_back)

            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"SELECT mh.id, mh.survivor_id, mh.merged_ids, mh.merged_questions, "
                f"mh.operation_type, mh.phase, mh.confidence, mh.cat2, "
                f"mh.is_rolled_back, mh.rolled_back_at, mh.created_at, "
                f"qb.question as survivor_question, "
                f"u.username as operator_name "
                f"FROM merge_history mh "
                f"LEFT JOIN question_bank qb ON mh.survivor_id = qb.id "
                f"LEFT JOIN users u ON mh.operator_id = u.id "
                f"WHERE {where_clause} "
                f"ORDER BY mh.created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

            total = conn.execute(
                f"SELECT COUNT(*) FROM merge_history mh WHERE {where_clause}", params
            ).fetchone()[0]

            items = []
            for r in rows:
                item = dict(r)
                try:
                    item["merged_ids"] = json.loads(item["merged_ids"])
                except Exception:
                    item["merged_ids"] = []
                try:
                    item["merged_questions"] = json.loads(item["merged_questions"])
                except Exception:
                    item["merged_questions"] = []
                items.append(item)

            return {"items": items, "total": total}

    return await run_db(_query)


@router.get("/merge-history/{history_id}")
async def get_merge_history_detail(
    history_id: int, admin: dict = Depends(get_admin_user)
):
    """获取单条合并历史详情（含前后快照）"""

    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT mh.*, qb.question as survivor_question, "
                "u.username as operator_name, "
                "rb.username as rollback_by_name "
                "FROM merge_history mh "
                "LEFT JOIN question_bank qb ON mh.survivor_id = qb.id "
                "LEFT JOIN users u ON mh.operator_id = u.id "
                "LEFT JOIN users rb ON mh.rolled_back_by = rb.id "
                "WHERE mh.id = ?",
                (history_id,),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            for field in [
                "merged_ids",
                "merged_questions",
                "pre_snapshot",
                "post_snapshot",
            ]:
                try:
                    item[field] = (
                        json.loads(item[field])
                        if item[field]
                        else ([] if "merged" in field else {})
                    )
                except Exception:
                    pass
            return item

    result = await run_db(_query)
    if not result:
        raise HTTPException(status_code=404, detail="未找到该合并记录")
    return result


@router.post("/merge-rollback/{history_id}")
async def rollback_merge(history_id: int, admin: dict = Depends(get_admin_user)):
    """回滚一次合并操作（管理员）

    从 pre_snapshot 恢复 survivor 题目，并重建被合并删除的题目。
    """

    def _rollback():
        with get_db_connection() as conn:
            # 获取合并历史
            mh = conn.execute(
                "SELECT * FROM merge_history WHERE id = ?", (history_id,)
            ).fetchone()
            if not mh:
                raise HTTPException(status_code=404, detail="未找到该合并记录")
            if mh["is_rolled_back"]:
                raise HTTPException(status_code=400, detail="该合并已经回滚过了")

            pre_snapshot = json.loads(mh["pre_snapshot"]) if mh["pre_snapshot"] else {}
            merged_ids = json.loads(mh["merged_ids"]) if mh["merged_ids"] else []
            merged_questions = (
                json.loads(mh["merged_questions"]) if mh["merged_questions"] else []
            )

            conn.execute("BEGIN")
            try:
                survivor_id = mh["survivor_id"]

                # 恢复 survivor 到合并前状态
                if pre_snapshot:
                    conn.execute(
                        "UPDATE question_bank SET "
                        "question = ?, cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, "
                        "frequency = ?, ai_answer = ?, sources = ?, "
                        "original_questions = ?, original_question_sources = ?, "
                        "status = ?, job_position = ?, "
                        "updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (
                            pre_snapshot.get("question", ""),
                            pre_snapshot.get("cat1", ""),
                            pre_snapshot.get("cat2", ""),
                            pre_snapshot.get("tags", ""),
                            pre_snapshot.get("difficulty", ""),
                            pre_snapshot.get("frequency", 1),
                            pre_snapshot.get("ai_answer", ""),
                            pre_snapshot.get("sources", "[]"),
                            pre_snapshot.get("original_questions", "[]"),
                            pre_snapshot.get("original_question_sources", "[]"),
                            pre_snapshot.get("status", "approved"),
                            pre_snapshot.get("job_position", ""),
                            survivor_id,
                        ),
                    )

                # 重建被合并删除的题目（简化版：创建为 frequency=1 的独立题）
                for i, mid in enumerate(merged_ids):
                    q_text = merged_questions[i] if i < len(merged_questions) else ""
                    # 检查该 ID 是否已被重建
                    existing = conn.execute(
                        "SELECT id FROM question_bank WHERE id = ?", (mid,)
                    ).fetchone()
                    if not existing:
                        conn.execute(
                            "INSERT INTO question_bank "
                            "(id, question, cat1, cat2, frequency, status, "
                            "sources, original_questions, original_question_sources, "
                            "job_position, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, 1, 'approved', '[]', '[]', '[]', ?, "
                            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                            (
                                mid,
                                q_text,
                                pre_snapshot.get("cat1", ""),
                                pre_snapshot.get("cat2", ""),
                                pre_snapshot.get("job_position", ""),
                            ),
                        )

                # 标记已回滚
                conn.execute(
                    "UPDATE merge_history SET is_rolled_back = 1, "
                    "rolled_back_at = CURRENT_TIMESTAMP, rolled_back_by = ? "
                    "WHERE id = ?",
                    (admin["id"], history_id),
                )

                conn.execute("COMMIT")
                logger.info(
                    f"[回滚] merge_history#{history_id} 已回滚, "
                    f"恢复 survivor={survivor_id}, 重建={merged_ids}"
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise

            return {
                "status": "success",
                "message": f"已回滚合并记录 #{history_id}",
                "restored_survivor": survivor_id,
                "rebuilt_ids": merged_ids,
            }

    return await run_db(_rollback)


@router.post("/merge-feedback")
async def submit_merge_feedback(
    merge_history_id: int = None,
    question_bank_id: int = None,
    feedback_type: str = "wrong_merge",
    comment: str = "",
    admin: dict = Depends(get_admin_user),
):
    """提交合并质量反馈

    Args:
        merge_history_id: 合并历史记录 ID
        question_bank_id: 相关题目 ID
        feedback_type: wrong_merge（误合并）, correct_merge（正确合并）, other
        comment: 附加说明
    """
    if feedback_type not in ("wrong_merge", "correct_merge", "other"):
        raise HTTPException(
            status_code=400,
            detail="feedback_type 必须为 wrong_merge/correct_merge/other",
        )

    def _insert():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO merge_feedback "
                "(merge_history_id, question_bank_id, feedback_type, comment, user_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    merge_history_id,
                    question_bank_id,
                    feedback_type,
                    comment,
                    admin["id"],
                ),
            )
            conn.commit()

    await run_db(_insert)
    logger.info(
        f"[反馈] admin={admin['id']}, type={feedback_type}, "
        f"merge_history={merge_history_id}, qb={question_bank_id}"
    )
    return {"status": "success", "message": "反馈已记录"}


@router.get("/merge-stats")
async def get_merge_stats(admin: dict = Depends(get_admin_user)):
    """获取合并统计信息（管理员）"""

    def _query():
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM merge_history").fetchone()[0]
            rolled_back = conn.execute(
                "SELECT COUNT(*) FROM merge_history WHERE is_rolled_back = 1"
            ).fetchone()[0]
            by_type = conn.execute(
                "SELECT operation_type, COUNT(*) as cnt FROM merge_history GROUP BY operation_type"
            ).fetchall()
            by_phase = conn.execute(
                "SELECT phase, COUNT(*) as cnt FROM merge_history GROUP BY phase"
            ).fetchall()
            by_cat2 = conn.execute(
                "SELECT cat2, COUNT(*) as cnt FROM merge_history "
                "WHERE cat2 != '' GROUP BY cat2 ORDER BY cnt DESC LIMIT 20"
            ).fetchall()

            # 反馈统计
            feedback_stats = conn.execute(
                "SELECT feedback_type, COUNT(*) as cnt FROM merge_feedback GROUP BY feedback_type"
            ).fetchall()

            wrong_merges = next(
                (
                    r["cnt"]
                    for r in feedback_stats
                    if r["feedback_type"] == "wrong_merge"
                ),
                0,
            )
            correct_merges = next(
                (
                    r["cnt"]
                    for r in feedback_stats
                    if r["feedback_type"] == "correct_merge"
                ),
                0,
            )
            feedback_total = wrong_merges + correct_merges
            wrong_rate = (
                (wrong_merges / feedback_total * 100) if feedback_total > 0 else 0
            )

            return {
                "total_merges": total,
                "rolled_back": rolled_back,
                "rollback_rate": round(rolled_back / total * 100, 1)
                if total > 0
                else 0,
                "by_type": {r["operation_type"]: r["cnt"] for r in by_type},
                "by_phase": {r["phase"]: r["cnt"] for r in by_phase},
                "by_cat2": {r["cat2"]: r["cnt"] for r in by_cat2},
                "feedback": {
                    "wrong_merge": wrong_merges,
                    "correct_merge": correct_merges,
                    "wrong_rate_percent": round(wrong_rate, 1),
                },
            }

    return await run_db(_query)


@router.post("/clustering-maintenance")
async def clustering_maintenance(
    dry_run: bool = True,
    merge_exact_duplicates: bool = True,
    admin: dict = Depends(get_admin_user),
):
    """审计/修复聚类元数据。

    只自动执行确定性修复；语义相似题只应作为候选，不在这里自动合并。
    """
    from app.services.clustering_maintenance import run_clustering_maintenance

    def _run():
        with get_db_connection() as conn:
            return run_clustering_maintenance(
                conn,
                execute=not dry_run,
                merge_exact_duplicates=merge_exact_duplicates,
            )

    return await run_db(_run)


@router.post("/fix-lone-islands")
async def fix_lone_islands(
    similarity_threshold: float = 0.85,
    max_merges: int = 50,
    dry_run: bool = True,
    admin: dict = Depends(get_admin_user),
):
    """列出孤岛候选。

    历史 embedding 阈值方案质量不稳定，因此该端点默认不再用 embedding
    自动合并。dry_run=false 时也只执行精确重复修复。

    Args:
        similarity_threshold: 兼容旧参数，仅用于返回候选标注，不作为自动合并依据
        max_merges: 最大候选数
        dry_run: 默认 True；False 时执行确定性精确重复维护
    """
    from app.services.clustering_maintenance import (
        audit_clustering_state,
        run_clustering_maintenance,
    )

    def _fix():
        with get_db_connection() as conn:
            if dry_run:
                audit = audit_clustering_state(conn)
                return {
                    "mode": "dry_run",
                    "message": "embedding 阈值不再用于自动合并；这里只返回确定性候选",
                    "similarity_threshold_ignored": similarity_threshold,
                    "max_candidates": max_merges,
                    "exact_duplicate_groups": audit["exact_duplicate_groups"][
                        :max_merges
                    ],
                    "merged": 0,
                }
            return run_clustering_maintenance(
                conn, execute=True, merge_exact_duplicates=True
            )

    return await run_db(_fix)

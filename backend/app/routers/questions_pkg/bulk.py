"""批量删除与上传操作"""

import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.core.cache import invalidate_master_bank_cache
from app.db.question_bank_sources import delete_original_item
from app.db.connection import (
    get_db_connection,
    run_db,
    get_current_job_position,
    get_user_job_position,
)
from app.models.schemas import (
    BatchDeleteRequest,
    DeleteOriginalQuestionRequest,
    UploadToBankRequest,
)
from app.services.clustering import generate_unified_question

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.post("/api/master-bank/delete-original-question/{question_id}")
async def delete_original_question(
    question_id: int,
    req: DeleteOriginalQuestionRequest,
    user: dict = Depends(get_current_user),
):
    """从聚类中删除指定的原始题目（不创建独立题目），并清理相关数据"""
    original_q = req.original_question.strip()
    if not original_q:
        raise HTTPException(status_code=400, detail="original_question 不能为空")

    is_admin = user.get("is_admin", 0)
    uid = user["id"]

    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                row = cursor.execute(
                    "SELECT id, owner_id, original_questions, original_question_sources, sources FROM question_bank WHERE id = ?",
                    (question_id,),
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="未找到该题目")

                # 权限检查：管理员可删任何，普通用户只能删自己的
                if not is_admin:
                    if row["owner_id"] is None:
                        raise HTTPException(
                            status_code=403, detail="无权删除公共题目中的问题"
                        )
                    if str(row["owner_id"]) != str(uid):
                        raise HTTPException(
                            status_code=403, detail="无权删除他人题目中的问题"
                        )

                orig_qs = (
                    json.loads(row["original_questions"])
                    if row["original_questions"]
                    else []
                )
                orig_qs_src = (
                    json.loads(row["original_question_sources"])
                    if row["original_question_sources"]
                    else []
                )

                if original_q not in orig_qs:
                    raise HTTPException(
                        status_code=400, detail="该原始题目不在此聚类中"
                    )

                # 从聚类中移除
                new_orig = [q for q in orig_qs if q != original_q]
                new_orig_src = [
                    item for item in orig_qs_src if item.get("question") != original_q
                ]

                # 重新计算 sources
                remaining_sources = []
                seen = set()
                for item in new_orig_src:
                    for s in item.get("sources", []):
                        key = (
                            s.get("url", ""),
                            s.get("company", ""),
                            s.get("round", ""),
                        )
                        if key not in seen:
                            seen.add(key)
                            remaining_sources.append(s)

                # 删除 questions_detail 中对应的记录
                from app.db.operations import (
                    _mark_distribution_refresh_for_detail_ids_txn,
                )

                detail_ids = cursor.execute(
                    "SELECT id FROM questions_detail WHERE question = ? AND deleted_at IS NULL",
                    (original_q,),
                ).fetchall()
                _mark_distribution_refresh_for_detail_ids_txn(
                    cursor, [detail["id"] for detail in detail_ids]
                )
                cursor.execute(
                    "DELETE FROM questions_detail WHERE question = ? AND deleted_at IS NULL",
                    (original_q,),
                )

                if len(new_orig) == 0:
                    # 聚类清空，删除整个条目
                    cursor.execute(
                        "DELETE FROM question_bank WHERE id = ?", (question_id,)
                    )
                    cursor.execute(
                        "DELETE FROM user_question_view WHERE question_bank_id = ?",
                        (question_id,),
                    )
                    cursor.execute(
                        "DELETE FROM question_position WHERE question_id = ?",
                        (question_id,),
                    )
                    cursor.execute(
                        "DELETE FROM user_practice_history WHERE question_bank_id = ?",
                        (question_id,),
                    )
                elif len(new_orig) == 1:
                    # 只剩一个，简化为独立题目
                    cursor.execute(
                        "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = 1, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            new_orig[0],
                            json.dumps(remaining_sources, ensure_ascii=False),
                            question_id,
                        ),
                    )
                else:
                    cursor.execute(
                        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            json.dumps(new_orig, ensure_ascii=False),
                            json.dumps(new_orig_src, ensure_ascii=False),
                            len(new_orig),
                            json.dumps(remaining_sources, ensure_ascii=False),
                            question_id,
                        ),
                    )

                # Dual-write: delete removed item from normalized tables (if cluster not fully deleted)
                if len(new_orig) >= 1:
                    try:
                        delete_original_item(cursor, question_id, original_q)
                    except Exception:
                        pass

                if row["owner_id"] is None and len(new_orig) >= 1:
                    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                    mark_cluster_review_pending(conn, question_id, "delete_variant")

                conn.commit()
                return new_orig, new_orig_src, question_id
            except Exception:
                conn.rollback()
                raise

    try:
        remaining_orig, remaining_orig_src, old_id = await run_db(_delete)
        await invalidate_master_bank_cache()

        # 如果聚类还有多题，重新生成统一问题（跳过手动编辑过的）
        if len(remaining_orig) >= 2:

            def _check_manual():
                with get_db_connection() as conn:
                    r = conn.execute(
                        "SELECT question_manually_edited FROM question_bank WHERE id = ?",
                        (old_id,),
                    ).fetchone()
                    return r and r["question_manually_edited"]

            is_manual = await run_db(_check_manual)
            if not is_manual:
                try:
                    sources_ctx = []
                    for item in remaining_orig_src:
                        s = item.get("sources", [{}])[0] if item.get("sources") else {}
                        sources_ctx.append(
                            {
                                "question": item.get("question", ""),
                                "company": s.get("company", ""),
                                "round": s.get("round", ""),
                            }
                        )
                    unified = await generate_unified_question(
                        remaining_orig, sources_context=sources_ctx, user_id=uid
                    )

                    def _update_unified():
                        with get_db_connection() as conn:
                            conn.execute(
                                "UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (unified, old_id),
                            )
                            from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                            mark_cluster_review_pending(conn, old_id, "representative_changed")
                            conn.commit()

                    await run_db(_update_unified)
                except Exception as e:
                    logger.warning(f"删除后重新生成统一问题失败: {e}")

        msg = "题目已从聚类中删除" if remaining_orig else "聚类已完全删除"
        return {"status": "success", "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("删除原始题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.delete("/api/master-bank/{question_id}")
async def delete_master_question(
    question_id: int, user: dict = Depends(get_current_user)
):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id, question, sources, owner_id FROM question_bank WHERE id = ? AND deleted_at IS NULL",
                (question_id,),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404, detail="未找到该题目，可能已被删除"
                )

            # 权限检查：公共题目仅管理员可删，个人题目仅本人可删
            is_admin = user.get("is_admin", 0)
            if row["owner_id"] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除公共题目")
            if (
                row["owner_id"] is not None
                and row["owner_id"] != user["id"]
                and not is_admin
            ):
                raise HTTPException(status_code=403, detail="无权删除他人的个人题目")

            cursor.execute(
                "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND deleted_at IS NULL",
                (question_id,),
            )
            conn.commit()

    try:
        await run_db(_delete)
        await invalidate_master_bank_cache()
        return {"status": "success", "message": "题目已移入回收站"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="删除失败，请查看服务端日志")


@router.post("/api/master-bank/batch-delete")
async def batch_delete_master_bank(
    req: BatchDeleteRequest, user: dict = Depends(get_current_user)
):
    """批量删除题库题目，单事务完成"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                f"SELECT id, question, owner_id FROM question_bank WHERE id IN ({placeholders}) AND deleted_at IS NULL",
                req.ids,
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            # 权限检查
            is_admin = user.get("is_admin", 0)
            for r in rows:
                if r["owner_id"] is None and not is_admin:
                    raise HTTPException(
                        status_code=403, detail=f"无权删除公共题目 (id={r['id']})"
                    )
                if (
                    r["owner_id"] is not None
                    and r["owner_id"] != user["id"]
                    and not is_admin
                ):
                    raise HTTPException(
                        status_code=403, detail=f"无权删除他人的个人题目 (id={r['id']})"
                    )

            found_ids = [r["id"] for r in rows]
            ph2 = ",".join("?" * len(found_ids))
            cursor.execute(
                f"UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
                f"WHERE id IN ({ph2}) AND deleted_at IS NULL",
                found_ids,
            )
            conn.commit()
            return len(found_ids)

    try:
        deleted = await run_db(_batch_delete)
        await invalidate_master_bank_cache()
        return {"status": "success", "deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量删除失败")
        raise HTTPException(status_code=500, detail="批量删除失败，请查看服务端日志")


@router.get("/api/master-bank/trash")
async def get_master_bank_trash(user: dict = Depends(get_current_user)):
    """查询题库回收站。管理员可看公共题，普通用户只看自己的个人题。"""

    def _query():
        with get_db_connection() as conn:
            if user.get("is_admin", 0):
                # 管理员仅见公共题回收站（个人题回收站仅本人可见）
                rows = conn.execute(
                    "SELECT id, question, cat1, cat2, tags, difficulty, owner_id, job_position, deleted_at "
                    "FROM question_bank WHERE owner_id IS NULL AND deleted_at IS NOT NULL ORDER BY deleted_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, question, cat1, cat2, tags, difficulty, owner_id, job_position, deleted_at "
                    "FROM question_bank WHERE owner_id = ? AND deleted_at IS NOT NULL ORDER BY deleted_at DESC",
                    (user["id"],),
                ).fetchall()
            return [dict(row) for row in rows]

    return {"items": await run_db(_query)}


@router.post("/api/master-bank/restore/{question_id}")
async def restore_master_question(
    question_id: int, user: dict = Depends(get_current_user)
):
    """恢复回收站中的题目。"""

    def _restore():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, owner_id FROM question_bank WHERE id = ? AND deleted_at IS NOT NULL",
                (question_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到回收站中的题目")
            is_admin = user.get("is_admin", 0)
            if row["owner_id"] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权恢复公共题目")
            if (
                row["owner_id"] is not None
                and row["owner_id"] != user["id"]
                and not is_admin
            ):
                raise HTTPException(status_code=403, detail="无权恢复他人的个人题目")
            conn.execute(
                "UPDATE question_bank SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (question_id,),
            )
            if row["owner_id"] is None:
                from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                mark_cluster_review_pending(conn, question_id, "cluster_restored", force=True)
            conn.commit()

    await run_db(_restore)
    await invalidate_master_bank_cache()
    return {"status": "success", "message": "题目已恢复"}


@router.post("/api/master-bank/batch-restore")
async def batch_restore_master_bank(
    req: BatchDeleteRequest, user: dict = Depends(get_current_user)
):
    """批量恢复题库题目。"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _restore():
        with get_db_connection() as conn:
            placeholders = ",".join("?" * len(req.ids))
            rows = conn.execute(
                f"SELECT id, owner_id FROM question_bank WHERE id IN ({placeholders}) AND deleted_at IS NOT NULL",
                req.ids,
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到回收站中的题目")
            is_admin = user.get("is_admin", 0)
            for row in rows:
                if row["owner_id"] is None and not is_admin:
                    raise HTTPException(
                        status_code=403, detail=f"无权恢复公共题目 (id={row['id']})"
                    )
                if (
                    row["owner_id"] is not None
                    and row["owner_id"] != user["id"]
                    and not is_admin
                ):
                    raise HTTPException(
                        status_code=403,
                        detail=f"无权恢复他人的个人题目 (id={row['id']})",
                    )
            found_ids = [row["id"] for row in rows]
            ph2 = ",".join("?" * len(found_ids))
            conn.execute(
                f"UPDATE question_bank SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP WHERE id IN ({ph2})",
                found_ids,
            )
            public_ids = [row["id"] for row in rows if row["owner_id"] is None]
            if public_ids:
                from app.services.cluster_review_lifecycle import mark_clusters_review_pending

                for public_id in public_ids:
                    mark_clusters_review_pending(
                        conn, [public_id], "cluster_restored", priority=50, force=True
                    )
            conn.commit()
            return len(found_ids)

    restored = await run_db(_restore)
    await invalidate_master_bank_cache()
    return {"status": "success", "restored": restored}


@router.post("/api/master-bank/upload")
async def upload_to_bank(
    req: UploadToBankRequest, user: dict = Depends(get_current_user)
):
    """上传题目到题库"""
    if req.target not in ("public", "personal"):
        raise HTTPException(status_code=400, detail="target 可选: public / personal")

    def _insert():
        with get_db_connection() as conn:
            _, current_pos = get_user_job_position(user["id"])
            current_pos = current_pos or get_current_job_position()
            if req.target == "personal":
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?)",
                    (
                        req.question_text,
                        req.cat1,
                        req.cat2,
                        req.tags,
                        req.difficulty,
                        user["id"],
                        user["id"],
                        current_pos,
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, NULL, ?, 'pending', ?)",
                    (
                        req.question_text,
                        req.cat1,
                        req.cat2,
                        req.tags,
                        req.difficulty,
                        user["id"],
                        current_pos,
                    ),
                )
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # 同步 question_position 关联表
            pos_row = conn.execute(
                "SELECT id FROM job_positions WHERE name = ?", (current_pos,)
            ).fetchone()
            if pos_row:
                conn.execute(
                    "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                    (new_id, pos_row[0]),
                )
            conn.commit()

    await run_db(_insert)
    await invalidate_master_bank_cache()
    status_msg = (
        "已加入个人题库"
        if req.target == "personal"
        else "已提交到公共题库，等待管理员审核"
    )
    return {"status": "success", "message": status_msg}

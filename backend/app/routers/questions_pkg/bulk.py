"""批量删除与上传操作"""
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.question_bank_sources import delete_original_item
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_user_job_position
from app.models.schemas import BatchDeleteRequest, DeleteOriginalQuestionRequest, UploadToBankRequest
from app.services.clustering import generate_unified_question

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.post("/api/master-bank/delete-original-question/{question_id}")
async def delete_original_question(question_id: int, req: DeleteOriginalQuestionRequest, user: dict = Depends(get_current_user)):
    """从聚类中删除指定的原始题目（不创建独立题目），并清理相关数据"""
    original_q = req.original_question.strip()
    if not original_q:
        raise HTTPException(status_code=400, detail="original_question 不能为空")

    is_admin = user.get('is_admin', 0)
    uid = user['id']

    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                row = cursor.execute(
                    "SELECT id, owner_id, original_questions, original_question_sources, sources FROM question_bank WHERE id = ?",
                    (question_id,)
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="未找到该题目")

                # 权限检查：管理员可删任何，普通用户只能删自己的
                if not is_admin:
                    if row['owner_id'] is None:
                        raise HTTPException(status_code=403, detail="无权删除公共题目中的问题")
                    if str(row['owner_id']) != str(uid):
                        raise HTTPException(status_code=403, detail="无权删除他人题目中的问题")

                orig_qs = json.loads(row['original_questions']) if row['original_questions'] else []
                orig_qs_src = json.loads(row['original_question_sources']) if row['original_question_sources'] else []

                if original_q not in orig_qs:
                    raise HTTPException(status_code=400, detail="该原始题目不在此聚类中")

                # 从聚类中移除
                new_orig = [q for q in orig_qs if q != original_q]
                new_orig_src = [item for item in orig_qs_src if item.get('question') != original_q]

                # 重新计算 sources
                remaining_sources = []
                seen = set()
                for item in new_orig_src:
                    for s in item.get('sources', []):
                        key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                        if key not in seen:
                            seen.add(key)
                            remaining_sources.append(s)

                # 删除 questions_detail 中对应的记录
                cursor.execute("DELETE FROM questions_detail WHERE question = ? AND deleted_at IS NULL", (original_q,))

                if len(new_orig) == 0:
                    # 聚类清空，删除整个条目
                    cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                    cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))
                    cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
                    cursor.execute("DELETE FROM user_practice_history WHERE question_bank_id = ?", (question_id,))
                elif len(new_orig) == 1:
                    # 只剩一个，简化为独立题目
                    cursor.execute(
                        "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = 1, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_orig[0], json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(new_orig, ensure_ascii=False), json.dumps(new_orig_src, ensure_ascii=False),
                         len(new_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )

                # Dual-write: delete removed item from normalized tables (if cluster not fully deleted)
                if len(new_orig) >= 1:
                    try:
                        delete_original_item(cursor, question_id, original_q)
                    except Exception:
                        pass

                conn.commit()
                return new_orig, new_orig_src, question_id
            except Exception:
                conn.rollback()
                raise

    try:
        remaining_orig, remaining_orig_src, old_id = await run_db(_delete)

        # 如果聚类还有多题，重新生成统一问题（跳过手动编辑过的）
        if len(remaining_orig) >= 2:
            def _check_manual():
                with get_db_connection() as conn:
                    r = conn.execute("SELECT question_manually_edited FROM question_bank WHERE id = ?", (old_id,)).fetchone()
                    return r and r['question_manually_edited']
            is_manual = await run_db(_check_manual)
            if not is_manual:
                try:
                    sources_ctx = []
                    for item in remaining_orig_src:
                        s = item.get("sources", [{}])[0] if item.get("sources") else {}
                        sources_ctx.append({"question": item.get("question", ""), "company": s.get("company", ""), "round": s.get("round", "")})
                    unified = await generate_unified_question(remaining_orig, sources_context=sources_ctx, user_id=uid)
                    def _update_unified():
                        with get_db_connection() as conn:
                            conn.execute("UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unified, old_id))
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
async def delete_master_question(question_id: int, user: dict = Depends(get_current_user)):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT id, question, sources, owner_id FROM question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")

            # 权限检查：公共题目仅管理员可删，个人题目仅本人可删
            is_admin = user.get('is_admin', 0)
            if row['owner_id'] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除公共题目")
            if row['owner_id'] is not None and row['owner_id'] != user['id'] and not is_admin:
                raise HTTPException(status_code=403, detail="无权删除他人的个人题目")

            # 联动清理 questions_detail 中对应的记录
            question_text = row['question']
            if question_text:
                cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))

            # BUG-020: 清理其他 QB 记录中对该题目文本的 stale original_questions 引用
            if question_text:
                other_qb = cursor.execute(
                    "SELECT id, original_questions, original_question_sources FROM question_bank WHERE id != ? AND original_questions LIKE ?",
                    (question_id, f'%{question_text[:80]}%')
                ).fetchall()
                for qb in other_qb:
                    try:
                        oq = json.loads(qb['original_questions']) if qb['original_questions'] else []
                        oqs = json.loads(qb['original_question_sources']) if qb['original_question_sources'] else []
                    except Exception:
                        continue
                    if question_text in oq:
                        oq = [q for q in oq if q != question_text]
                        oqs = [item for item in oqs if item.get('question') != question_text]
                        cursor.execute(
                            "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (json.dumps(oq, ensure_ascii=False), json.dumps(oqs, ensure_ascii=False), qb['id'])
                        )
                        # Dual-write: also remove from normalized tables
                        try:
                            delete_original_item(cursor, qb['id'], question_text)
                        except Exception:
                            pass

            # Bug #14: 级联清理 user_question_view 和 question_position
            cursor.execute("DELETE FROM user_question_view WHERE question_bank_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
            cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
            cursor.execute("DELETE FROM user_practice_history WHERE question_bank_id = ?", (question_id,))
            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success", "message": "题目删除成功（已联动清理 questions_detail 和练习历史）"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="删除失败，请查看服务端日志")


@router.post("/api/master-bank/batch-delete")
async def batch_delete_master_bank(req: BatchDeleteRequest, user: dict = Depends(get_current_user)):
    """批量删除题库题目，单事务完成"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                f"SELECT id, question, owner_id FROM question_bank WHERE id IN ({placeholders})", req.ids
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            # 权限检查
            is_admin = user.get('is_admin', 0)
            for r in rows:
                if r['owner_id'] is None and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权删除公共题目 (id={r['id']})")
                if r['owner_id'] is not None and r['owner_id'] != user['id'] and not is_admin:
                    raise HTTPException(status_code=403, detail=f"无权删除他人的个人题目 (id={r['id']})")

            question_texts = [r["question"] for r in rows if r["question"]]
            if question_texts:
                qph = ",".join("?" * len(question_texts))
                cursor.execute(f"DELETE FROM questions_detail WHERE question IN ({qph})", question_texts)

            # 清理其他 QB 记录中对被删除题目的 stale oqs/oqs_sources 引用
            found_ids = [r["id"] for r in rows]
            if question_texts:
                for q_text in question_texts:
                    others = cursor.execute(
                        "SELECT id, original_questions, original_question_sources FROM question_bank "
                        "WHERE id NOT IN ({}) AND original_questions LIKE ?".format(",".join("?" * len(found_ids))),
                        [*found_ids, f'%{q_text}%']
                    ).fetchall()
                    for qb in others:
                        try:
                            oq = json.loads(qb['original_questions']) if qb['original_questions'] else []
                            oqs_src = json.loads(qb['original_question_sources']) if qb['original_question_sources'] else []
                        except Exception:
                            continue
                        if q_text in oq:
                            oq = [q for q in oq if q != q_text]
                            oqs_src = [item for item in oqs_src if item.get('question') != q_text]
                            cursor.execute(
                                "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (json.dumps(oq, ensure_ascii=False), json.dumps(oqs_src, ensure_ascii=False), qb['id'])
                            )
                            # Dual-write: also remove from normalized tables
                            try:
                                delete_original_item(cursor, qb['id'], q_text)
                            except Exception:
                                pass
            ph2 = ",".join("?" * len(found_ids))
            # Bug #14: 级联清理 user_question_view 和 question_position
            cursor.execute(f"DELETE FROM user_question_view WHERE question_bank_id IN ({ph2})", found_ids)
            cursor.execute(f"DELETE FROM question_position WHERE question_id IN ({ph2})", found_ids)
            cursor.execute(f"DELETE FROM question_bank WHERE id IN ({ph2})", found_ids)
            cursor.execute(f"DELETE FROM user_practice_history WHERE question_bank_id IN ({ph2})", found_ids)
            conn.commit()
            return len(found_ids)

    try:
        deleted = await run_db(_batch_delete)
        return {"status": "success", "deleted": deleted}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("批量删除失败")
        raise HTTPException(status_code=500, detail="批量删除失败，请查看服务端日志")


@router.post("/api/master-bank/upload")
async def upload_to_bank(req: UploadToBankRequest, user: dict = Depends(get_current_user)):
    """上传题目到题库"""
    if req.target not in ('public', 'personal'):
        raise HTTPException(status_code=400, detail="target 可选: public / personal")

    def _insert():
        with get_db_connection() as conn:
            _, current_pos = get_user_job_position(user['id'])
            current_pos = current_pos or get_current_job_position()
            if req.target == 'personal':
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?)",
                    (req.question_text, req.cat1, req.cat2, req.tags, req.difficulty, user['id'], user['id'], current_pos)
                )
            else:
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, NULL, ?, 'pending', ?)",
                    (req.question_text, req.cat1, req.cat2, req.tags, req.difficulty, user['id'], current_pos)
                )
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            # 同步 question_position 关联表
            pos_row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (current_pos,)).fetchone()
            if pos_row:
                conn.execute("INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)", (new_id, pos_row[0]))
            conn.commit()

    await run_db(_insert)
    status_msg = "已加入个人题库" if req.target == 'personal' else "已提交到公共题库，等待管理员审核"
    return {"status": "success", "message": status_msg}

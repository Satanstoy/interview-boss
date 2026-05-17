import os
import json
import time
import random as _random
import shutil
import logging
import asyncio
import openai
from collections import Counter
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from app.core.config import DB_PATH, LLM_MODEL
from app.core.prompts import TAGGING_PROMPT, ANSWER_PROMPT, EVAL_PROMPT, build_tagging_prompt
from app.core.auth import get_current_user, get_admin_user
from app.db.question_bank_sources import insert_source, delete_original_item, insert_original_item, get_sources, build_api_shapes_batch_filtered
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_taxonomy_for_position, get_dynamic_frequency_sql
from app.models.schemas import BatchDeleteRequest, BatchGenerateAnswersRequest, EvaluateAnswerRequest, SplitQuestionRequest, DeleteOriginalQuestionRequest, MergeOriginalQuestionRequest, UploadToBankRequest, UpdateQuestionRequest
from app.services.llm import client, _call_llm_with_retry, _extract_json, _should_use_response_format, get_llm_client_for_user, raw_llm_call
from app.services.clustering import generate_unified_question, match_new_questions
from app.services.utils import normalize_category

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _build_bank_where_clause(user: dict, table_alias: str = "qb"):
    """根据用户 bank_mode 和当前岗位构建查询子句

    Returns:
        (from_clause, where_clause, params)
        - from_clause: 含 question_position JOIN 的 FROM 子句
        - where_clause: 含 bank_mode 过滤的 WHERE 子句
        - params: 参数列表
    """
    from app.db.connection import get_user_job_position
    prefix = f"{table_alias}." if table_alias else ""
    mode = user.get('bank_mode', 'public')
    uid = user['id']
    pos_id, pos_name = get_user_job_position(uid)

    # 使用 question_position 关联表进行岗位过滤
    from_clause = f"FROM question_bank {table_alias} JOIN question_position qp ON {prefix}id = qp.question_id AND qp.position_id = ?"
    from_params = [pos_id] if pos_id else []

    if not pos_id:
        # fallback: 如果没有 position_id，用旧的 job_position 列
        from_clause = f"FROM question_bank {table_alias}"
        pos_fallback = pos_name
        if mode == 'personal':
            return from_clause, f"WHERE {prefix}owner_id = ? AND {prefix}job_position = ?", [uid, pos_fallback]
        elif mode == 'mixed':
            return from_clause, f"WHERE (({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?) AND {prefix}job_position = ?", [uid, pos_fallback]
        else:
            return from_clause, f"WHERE {prefix}owner_id IS NULL AND {prefix}status = 'approved' AND {prefix}job_position = ?", [pos_fallback]

    if mode == 'personal':
        return from_clause, f"WHERE {prefix}owner_id = ?", from_params + [uid]
    elif mode == 'mixed':
        return from_clause, f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?", from_params + [uid]
    else:  # 'public'
        return from_clause, f"WHERE {prefix}owner_id IS NULL AND {prefix}status = 'approved'", from_params


@router.get("/api/master-bank")
async def get_master_bank(
    sort: str = "frequency_desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: dict = Depends(get_current_user)
):
    bank_mode = user.get('bank_mode', 'public')
    dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user['id'])
    order_clause = f"ORDER BY ({dyn_freq_sql}) DESC" if sort != "recent" else "ORDER BY qb.id DESC"
    offset = (page - 1) * page_size
    from_clause, where_clause, params = _build_bank_where_clause(user)

    def _query():
        with get_db_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) {from_clause} {where_clause}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, ({dyn_freq_sql}) as dyn_frequency, qb.ai_answer, qb.sources, qb.original_questions, qb.original_question_sources, COALESCE(uqv.is_starred, 0) as is_starred, COALESCE(uqv.user_answer, '') as user_answer, qb.owner_id, qb.status, qb.job_position "
                f"{from_clause} LEFT JOIN user_question_view uqv ON uqv.question_bank_id = qb.id AND uqv.user_id = ? {where_clause} {order_clause} LIMIT ? OFFSET ?",
                params + [user['id'], page_size, offset]
            ).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    # Collect all qb_ids for batch fetching from normalized tables
    qb_ids = [r['id'] for r in rows]
    def _fetch_normalized():
        with get_db_connection() as conn2:
            try:
                return build_api_shapes_batch_filtered(conn2, qb_ids, bank_mode, user['id'])
            except Exception:
                return {}
    normalized_map = await run_db(_fetch_normalized)

    result = []
    for r in rows:
        d = dict(r)
        d['frequency'] = d.pop('dyn_frequency', d.get('frequency', 0))
        norm = normalized_map.get(d['id'], {})
        d['sources'] = norm.get('sources', [])
        d['original_questions'] = norm.get('original_questions', [])
        d['original_question_sources'] = norm.get('original_question_sources', [])
        d['frequency'] = norm.get('frequency', d['frequency'])
        d['is_personal'] = d.get('owner_id') is not None
        d['has_reference_answer'] = bool(d.get('ai_answer') and '生成失败' not in d['ai_answer'])
        d['user_answer'] = d.get('user_answer', '')
        result.append(d)

    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.get("/api/master-bank/search")
async def search_master_bank(
    q: str = Query("", min_length=0, max_length=200),
    exclude_id: int = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user)
):
    """搜索题库（用于合并时选择目标题目）"""
    from_clause, where_clause, params = _build_bank_where_clause(user)
    conditions = []
    search_params = list(params)

    if q.strip():
        conditions.append("qb.question LIKE ?")
        search_params.append(f"%{q.strip()}%")
    if exclude_id is not None:
        conditions.append("qb.id != ?")
        search_params.append(exclude_id)

    if conditions:
        where_with_extra = f"{where_clause} AND {' AND '.join(conditions)}"
    else:
        where_with_extra = where_clause

    def _query():
        bank_mode = user.get('bank_mode', 'public')
        dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user['id'])
        with get_db_connection() as conn:
            rows = conn.execute(
                f"SELECT qb.id, qb.question, ({dyn_freq_sql}) as frequency, qb.cat1, qb.cat2 {from_clause} {where_with_extra} ORDER BY ({dyn_freq_sql}) DESC LIMIT ?",
                search_params + [limit]
            ).fetchall()
            return [dict(r) for r in rows]

    items = await run_db(_query)
    return {"items": items}


@router.get("/api/master-bank/analysis-status")
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
                "unanalyzed": [{"id": r['id'], "company": r['company'], "round": r['round'], "has_content": (r['ql_len'] or 0) > 10} for r in unanalyzed]
            }
    return await run_db(_check)


@router.post("/api/master-bank/build")
async def build_master_bank(admin: dict = Depends(get_admin_user)):
    """基于现有分类重新聚类（SSE 流式推送进度）"""

    async def event_stream():
        try:
            # ── 立即反馈 ──
            yield f"data: {json.dumps({'type': 'init', 'total': 0, 'step': 'prepare', 'message': '正在备份数据库...'})}\n\n"

            # ── 备份 ──
            backup_path = f"{DB_PATH}.bak.build.{int(time.time())}"
            try:
                shutil.copy2(DB_PATH, backup_path)
            except Exception as e:
                logger.warning(f"创建备份失败: {e}")
            try:
                import glob
                backups = sorted(glob.glob(f"{DB_PATH}.bak.build.*"), key=os.path.getmtime, reverse=True)
                for old in backups[3:]:
                    os.remove(old)
            except Exception:
                pass

            current_pos = get_current_job_position()

            def _load():
                with get_db_connection() as conn:
                    raw = conn.execute(
                        "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
                        "FROM questions_detail qd WHERE qd.question IS NOT NULL AND qd.question != '' AND qd.deleted_at IS NULL AND qd.job_position = ?",
                        (current_pos,)
                    ).fetchall()
                    existing = conn.execute(
                        "SELECT question, ai_answer FROM question_bank WHERE ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
                        (current_pos,)
                    ).fetchall()
                    return raw, {r['question']: r['ai_answer'] for r in existing}

            raw_questions, existing_answers_map = await run_db(_load)
            if not raw_questions:
                yield f"data: {json.dumps({'type': 'done', 'error': '没有数据'})}\n\n"
                return

            total = len(raw_questions)
            yield f"data: {json.dumps({'type': 'init', 'total': total, 'step': 'prepare', 'message': f'共 {total} 道题目，准备聚类...'})}\n\n"

            # ── 保存已有 AI 答案（跳过重标注，直接使用现有分类） ──

            # ── 清空公共题库 + 关联数据 ──
            yield f"data: {json.dumps({'type': 'progress', 'step': 'save', 'current': 0, 'total': 0, 'message': '清空旧题库...'})}\n\n"

            def _clear_bank():
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("BEGIN")
                    try:
                        cursor.execute(
                            "DELETE FROM user_question_view WHERE question_bank_id IN "
                            "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                            (current_pos,)
                        )
                        cursor.execute(
                            "DELETE FROM user_practice_history WHERE question_bank_id IN "
                            "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                            (current_pos,)
                        )
                        cursor.execute(
                            "DELETE FROM question_position WHERE question_id IN "
                            "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                            (current_pos,)
                        )
                        cursor.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", (current_pos,))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise

            await run_db(_clear_bank)

            # ── 入队所有问题（基本单位：单个问题） ──
            def _enqueue_all():
                with get_db_connection() as conn:
                    # 清空旧队列（包括 processing，因为全量重建会清空 question_bank，旧的 processing 无意义）
                    conn.execute("DELETE FROM analysis_queue")
                    # 获取所有 questions_detail（每题一条队列记录）
                    qd_rows = conn.execute(
                        "SELECT qd.id, i.id as interview_id FROM questions_detail qd "
                        "JOIN interview i ON qd.url = i.url "
                        "WHERE qd.deleted_at IS NULL AND i.deleted_at IS NULL AND qd.job_position = ?",
                        (current_pos,)
                    ).fetchall()
                    for row in qd_rows:
                        conn.execute(
                            "INSERT OR IGNORE INTO analysis_queue (interview_id, question_detail_id, status) VALUES (?, ?, 'pending')",
                            (row['interview_id'], row['id'])
                        )
                    conn.commit()
                    return len(qd_rows)

            enqueued = await run_db(_enqueue_all)
            yield f"data: {json.dumps({'type': 'progress', 'step': 'cluster', 'current': 0, 'total': enqueued, 'message': f'已入队 {enqueued} 道题目，开始批量聚类...'})}\n\n"
            logger.info(f"重建题库: 已入队 {enqueued} 道题目")

            # ── 分批聚类（复用 pipeline） ──
            from app.services.pipeline import dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed, BATCH_SIZE

            total_new = 0
            batch_num = 0
            while True:
                batch = dequeue_batch(BATCH_SIZE)
                if not batch:
                    break
                batch_num += 1
                try:
                    new_count = await cluster_batch(batch, user_id=admin['id'], skip_clean=True)
                    queue_ids = [item['queue_id'] for item in batch]
                    mark_batch_done(queue_ids)
                    total_new += new_count
                    yield f"data: {json.dumps({'type': 'progress', 'step': 'cluster', 'current': batch_num * BATCH_SIZE, 'total': enqueued, 'message': f'批次 {batch_num}: 新增 {new_count} 个聚类（累计 {total_new}）'})}\n\n"
                except Exception as e:
                    logger.error(f"重建聚类批次 {batch_num} 失败: {e}")
                    queue_ids = [item['queue_id'] for item in batch]
                    mark_batch_failed(queue_ids)
                    yield f"data: {json.dumps({'type': 'error', 'message': f'聚类批次 {batch_num} 失败: {str(e)[:100]}'})}\n\n"
                    raise

            # ── 恢复 AI 答案 ──
            def _restore_answers():
                with get_db_connection() as conn:
                    restored = 0
                    rows = conn.execute(
                        "SELECT id, question, original_questions FROM question_bank "
                        "WHERE job_position = ? AND owner_id IS NULL AND (ai_answer IS NULL OR ai_answer = '')",
                        (current_pos,)
                    ).fetchall()
                    for r in rows:
                        ai_answer = existing_answers_map.get(r['question'])
                        if not ai_answer:
                            try:
                                oqs = json.loads(r['original_questions'] or '[]')
                                for oq in oqs:
                                    ai_answer = existing_answers_map.get(oq)
                                    if ai_answer:
                                        break
                            except Exception:
                                pass
                        if ai_answer:
                            conn.execute("UPDATE question_bank SET ai_answer = ? WHERE id = ?", (ai_answer, r['id']))
                            restored += 1
                    conn.commit()
                    return restored

            restored = await run_db(_restore_answers)
            logger.info(f"全量重建完成: {total_new} 个聚类，恢复 {restored} 个 AI 答案")
            yield f"data: {json.dumps({'type': 'done', 'total_unique': total_new, 'restored': restored})}\n\n"
        except Exception as e:
            logger.exception("全量重建失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'重建失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/master-bank/compact")
async def compact_singletons(admin: dict = Depends(get_admin_user)):
    """孤岛碎片整理：对独立题做二次合并（SSE 流式推送）"""
    async def event_stream():
        try:
            from app.services.pipeline import compact_singletons_in_db
            yield f"data: {json.dumps({'type': 'init', 'step': 'compact', 'message': '开始孤岛碎片整理...'})}\n\n"
            result = await compact_singletons_in_db(user_id=admin['id'])
            yield f"data: {json.dumps({'type': 'done', **result})}\n\n"
        except Exception as e:
            logger.exception("孤岛碎片整理失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'整理失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.put("/api/master-bank/{question_id}")
async def edit_question(question_id: int, req: UpdateQuestionRequest, user: dict = Depends(get_current_user)):
    """编辑题目内容（question, cat1, cat2, tags, difficulty）"""

    def _edit():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, owner_id, job_position "
                "FROM question_bank WHERE id = ? AND deleted_at IS NULL",
                (question_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目")

            # 权限校验
            is_admin = user.get('is_admin', 0)
            if row['owner_id'] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权编辑公共题目")
            if row['owner_id'] is not None and row['owner_id'] != user['id'] and not is_admin:
                raise HTTPException(status_code=403, detail="无权编辑他人的个人题目")

            # 构建更新字段（只更新非 None 的字段）
            updates = {}
            if req.question is not None:
                updates['question'] = req.question
            if req.cat1 is not None:
                updates['cat1'] = req.cat1
            if req.cat2 is not None:
                updates['cat2'] = req.cat2
            if req.tags is not None:
                updates['tags'] = req.tags
            if req.difficulty is not None:
                updates['difficulty'] = req.difficulty

            if not updates:
                return dict(row)

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [question_id]
            # 编辑代表题时标记为手动编辑，防止被自动重新生成覆盖
            if 'question' in updates:
                conn.execute(
                    f"UPDATE question_bank SET {set_clause}, question_manually_edited = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values
                )
            else:
                conn.execute(
                    f"UPDATE question_bank SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values
                )

            # 同步 questions_detail
            if 'question' in updates:
                conn.execute(
                    "UPDATE questions_detail SET question = ? WHERE question = ?",
                    (updates['question'], row['question'])
                )

            conn.commit()

            # 返回更新后的数据
            updated = dict(row)
            updated.update(updates)
            return updated

    try:
        result = await run_db(_edit)
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("编辑题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误")


@router.post("/api/master-bank/build-personal")
async def build_personal_bank(user: dict = Depends(get_current_user)):
    """个人题库与公共题库聚类合并（SSE 流式推送进度）"""

    async def event_stream():
        try:
            uid = user['id']
            yield f"data: {json.dumps({'type': 'init', 'total': 0, 'step': 'prepare', 'message': '正在加载数据...'})}\n\n"

            from app.db.connection import get_user_job_position
            _, current_pos = get_user_job_position(uid)
            if not current_pos:
                current_pos = get_current_job_position()

            def _load():
                with get_db_connection() as conn:
                    # 加载用户的个人题目
                    personal = conn.execute(
                        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, job_position "
                        "FROM question_bank WHERE owner_id = ? AND job_position = ?",
                        (uid, current_pos)
                    ).fetchall()
                    # 加载公共题库（含 original_questions 用于匹配上下文）
                    public = conn.execute(
                        "SELECT id, question, cat2, sources, original_questions FROM question_bank "
                        "WHERE owner_id IS NULL AND status = 'approved' AND job_position = ?",
                        (current_pos,)
                    ).fetchall()
                    return [dict(r) for r in personal], [dict(r) for r in public]

            personal_rows, public_rows = await run_db(_load)

            if not personal_rows:
                yield f"data: {json.dumps({'type': 'done', 'error': '没有个人题目需要合并'})}\n\n"
                return

            if not public_rows:
                yield f"data: {json.dumps({'type': 'done', 'error': '公共题库为空，无法合并'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'init', 'total': len(personal_rows), 'message': f'开始合并: {len(personal_rows)} 道个人题目 vs {len(public_rows)} 道公共题目'})}\n\n"

            # 按 cat2 构建公共题库聚类上下文
            existing_by_cat2 = {}
            for r in public_rows:
                cat2 = r.get('cat2') or ''
                if cat2 not in existing_by_cat2:
                    existing_by_cat2[cat2] = []
                all_qs = [r['question']]
                try:
                    orig = json.loads(r.get('original_questions') or '[]')
                    all_qs.extend([q for q in orig if q and q != r['question']])
                except Exception:
                    pass
                existing_by_cat2[cat2].append({
                    "question_bank_id": r['id'],
                    "question": r['question'],
                    "all_questions": all_qs,
                })

            # 为个人题目分配临时 id 用于匹配
            new_rows_for_match = []
            for idx, row in enumerate(personal_rows):
                new_rows_for_match.append({
                    "id": idx,
                    "question": row['question'],
                    "cat2": row.get('cat2') or '',
                })

            yield f"data: {json.dumps({'type': 'progress', 'step': 'match', 'current': 0, 'total': 1, 'message': 'LLM 匹配中...'})}\n\n"

            match_result = await match_new_questions(new_rows_for_match, existing_by_cat2, user_id=user['id'])
            matched = match_result["matched"]
            unmatched = match_result["unmatched"]

            # 执行合并：匹配到的个人题目 → 增加公共题目的 frequency，追加 sources
            merged_count = 0

            def _merge():
                nonlocal merged_count
                with get_db_connection() as conn:
                    for m in matched:
                        new_id = m["new_id"]
                        qb_id = m["question_bank_id"]
                        personal_row = personal_rows[new_id]
                        existing = conn.execute("SELECT sources, original_questions, original_question_sources FROM question_bank WHERE id = ?", (qb_id,)).fetchone()
                        if existing:
                            try:
                                sources = json.loads(existing['sources']) if existing['sources'] else []
                            except (json.JSONDecodeError, TypeError):
                                sources = []
                            personal_sources = []
                            try:
                                personal_sources = json.loads(personal_row.get('sources', '[]')) if personal_row.get('sources') else []
                            except (json.JSONDecodeError, TypeError):
                                pass
                            # BUG-012: URL-based 去重
                            existing_urls = {s.get('url') for s in sources}
                            for s in personal_sources:
                                if s.get('url') not in existing_urls:
                                    sources.append(s)
                                    existing_urls.add(s.get('url'))
                            # BUG-013: 回写 original_questions
                            try:
                                orig_qs = json.loads(existing['original_questions']) if existing['original_questions'] else []
                                orig_qs_src = json.loads(existing['original_question_sources']) if existing['original_question_sources'] else []
                            except (json.JSONDecodeError, TypeError):
                                orig_qs, orig_qs_src = [], []
                            personal_q_text = personal_row['question']
                            if personal_q_text and personal_q_text not in orig_qs:
                                orig_qs.append(personal_q_text)
                                orig_qs_src.append({"question": personal_q_text, "sources": personal_sources})
                            conn.execute(
                                "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (len(orig_qs), json.dumps(sources, ensure_ascii=False), json.dumps(orig_qs, ensure_ascii=False), json.dumps(orig_qs_src, ensure_ascii=False), qb_id)
                            )
                            # Dual-write: insert personal question's sources into target's normalized tables
                            # INSERT OR IGNORE handles dedup with existing sources
                            for s in personal_sources:
                                try:
                                    insert_source(conn, qb_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                                except Exception:
                                    pass
                            try:
                                insert_original_item(conn, qb_id, personal_q_text, personal_sources)
                            except Exception:
                                pass
                        merged_count += 1
                        # 删除已合并的个人题目
                        conn.execute("DELETE FROM question_bank WHERE id = ?", (personal_row['id'],))
                    conn.commit()

            await run_db(_merge)

            yield f"data: {json.dumps({'type': 'progress', 'step': 'done', 'current': 0, 'total': 0, 'message': '合并完成'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'merged': merged_count, 'kept': len(unmatched), 'total_personal': len(personal_rows)})}\n\n"
        except Exception as e:
            logger.exception("个人题库构建失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'构建失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/master-bank/toggle-star/{question_id}")
async def toggle_star(question_id: int, user: dict = Depends(get_current_user)):
    """切换题目收藏状态（per-user，存储在 user_question_view 表）"""
    def _toggle():
        with get_db_connection() as conn:
            # 检查题目是否在用户可见范围内
            from_clause, where_clause, params = _build_bank_where_clause(user)
            row = conn.execute(
                f"SELECT qb.id {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id]
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目或无权操作")

            existing = conn.execute(
                "SELECT id, is_starred FROM user_question_view WHERE user_id = ? AND question_bank_id = ?",
                (user['id'], question_id)
            ).fetchone()

            if existing:
                new_val = 0 if existing['is_starred'] else 1
                conn.execute(
                    "UPDATE user_question_view SET is_starred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_val, existing['id'])
                )
            else:
                new_val = 1
                conn.execute(
                    "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) VALUES (?, ?, 1)",
                    (user['id'], question_id)
                )
            conn.commit()
            return new_val

    try:
        new_val = await run_db(_toggle)
        return {"status": "success", "is_starred": bool(new_val)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.post("/api/master-bank/split-question/{question_id}")
async def split_question(question_id: int, req: SplitQuestionRequest, admin: dict = Depends(get_admin_user)):
    """从聚类中拆出指定的原始题目，成为独立题目"""
    from app.services.clustering import generate_unified_question

    original_q = req.original_question.strip()
    if not original_q:
        raise HTTPException(status_code=400, detail="original_question 不能为空")

    def _split():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                row = cursor.execute(
                    "SELECT id, question, sources, original_questions, original_question_sources, cat1, cat2, tags, difficulty, job_position FROM question_bank WHERE id = ?",
                    (question_id,)
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="未找到该题目")

                orig_qs = json.loads(row['original_questions']) if row['original_questions'] else []
                orig_qs_src = json.loads(row['original_question_sources']) if row['original_question_sources'] else []

                if not orig_qs:
                    raise HTTPException(status_code=400, detail="该题目是独立题目，无需拆分")

                if original_q not in orig_qs:
                    raise HTTPException(status_code=400, detail="该原始题目不在此聚类中")

                # 找到该题的来源
                split_sources = []
                for item in orig_qs_src:
                    if item.get('question') == original_q:
                        split_sources = item.get('sources', [])
                        break

                # 如果来源为空，从 questions_detail 查询原始来源
                if not split_sources:
                    qd_row = cursor.execute(
                        "SELECT url, company, round, cat1, cat2, tags, diff_tag FROM questions_detail WHERE question = ? AND deleted_at IS NULL LIMIT 1",
                        (original_q,)
                    ).fetchone()
                    if qd_row:
                        split_sources = [{"url": qd_row['url'], "company": qd_row['company'], "round": qd_row['round']}]
                        # 如果分类也为空，使用 questions_detail 的分类
                        if not row['cat1'] and qd_row['cat1']:
                            row = dict(row)
                            row['cat1'] = qd_row['cat1']
                            row['cat2'] = qd_row['cat2']
                            row['tags'] = qd_row['tags'] or row['tags']

                # 创建新的独立题目（继承原题的 job_position）
                admin_id = admin['id'] if isinstance(admin, dict) else admin.id
                orig_job_position = row['job_position'] if 'job_position' in row.keys() else get_current_job_position()
                cursor.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, original_questions, original_question_sources, ai_answer, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, '[]', '[]', NULL, ?, ?, 'approved', ?)",
                    (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'],
                     json.dumps(split_sources, ensure_ascii=False), admin_id, admin_id, orig_job_position)
                )
                new_id = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]

                # Dual-write: insert sources into normalized tables
                for s in split_sources:
                    try:
                        insert_source(cursor, new_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                    except Exception:
                        pass
                try:
                    insert_original_item(cursor, new_id, original_q, split_sources)
                except Exception:
                    pass

                # 同步 question_position 关联表
                pos_row = cursor.execute("SELECT id FROM job_positions WHERE name = ?", (orig_job_position,)).fetchone()
                if pos_row:
                    cursor.execute(
                        "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                        (new_id, pos_row[0])
                    )

                # 从原聚类中移除该题
                new_orig = [q for q in orig_qs if q != original_q]
                new_orig_src = [item for item in orig_qs_src if item.get('question') != original_q]

                # 重新计算原聚类的 sources
                remaining_sources = []
                seen = set()
                for item in new_orig_src:
                    for s in item.get('sources', []):
                        key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                        if key not in seen:
                            seen.add(key)
                            remaining_sources.append(s)

                if len(new_orig) == 0:
                    cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                elif len(new_orig) == 1:
                    cursor.execute(
                        "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_orig[0], 1, json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(new_orig, ensure_ascii=False), json.dumps(new_orig_src, ensure_ascii=False),
                         len(new_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )

                # Dual-write: delete moved item from parent cluster's normalized tables
                if len(new_orig) >= 1:
                    try:
                        delete_original_item(cursor, question_id, original_q)
                    except Exception:
                        pass

                conn.commit()
                return new_id, new_orig, new_orig_src, question_id
            except Exception:
                conn.rollback()
                raise

    try:
        new_id, remaining_orig, remaining_orig_src, old_id = await run_db(_split)

        # 如果原聚类还有多题，重新生成统一问题（跳过手动编辑过的）
        if len(remaining_orig) >= 2:
            def _check_manual():
                with get_db_connection() as conn:
                    row = conn.execute("SELECT question_manually_edited FROM question_bank WHERE id = ?", (old_id,)).fetchone()
                    return row and row['question_manually_edited']
            is_manual = await run_db(_check_manual)
            if is_manual:
                logger.info(f"聚类 {old_id} 代表题已手动编辑，跳过自动重新生成")
            else:
                try:
                    # 构建来源上下文
                    sources_ctx = []
                    for item in remaining_orig_src:
                        s = item.get("sources", [{}])[0] if item.get("sources") else {}
                        sources_ctx.append({"question": item.get("question", ""), "company": s.get("company", ""), "round": s.get("round", "")})
                    unified = await generate_unified_question(remaining_orig, sources_context=sources_ctx, user_id=admin['id'])
                    def _update_unified():
                        with get_db_connection() as conn:
                            conn.execute(
                                "UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (unified, old_id)
                            )
                            conn.commit()
                    await run_db(_update_unified)
                except Exception as e:
                    logger.warning(f"拆分后重新生成统一问题失败: {e}")

        return {"status": "success", "new_id": new_id, "message": "题目已拆分为独立题目"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("拆分题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


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
            from app.services.clustering import generate_unified_question
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


@router.post("/api/master-bank/merge-question/{question_id}")
async def merge_question(question_id: int, req: MergeOriginalQuestionRequest, admin: dict = Depends(get_admin_user)):
    """将指定的原始题目从一个聚类移动到另一个聚类"""
    from app.services.clustering import generate_unified_question

    original_q = req.original_question.strip()
    if not original_q:
        raise HTTPException(status_code=400, detail="original_question 不能为空")
    if question_id == req.target_id:
        raise HTTPException(status_code=400, detail="不能合并到同一个聚类")

    def _merge():
        with get_db_connection() as conn:
            source = conn.execute(
                "SELECT id, question, sources, original_questions, original_question_sources, ai_answer FROM question_bank WHERE id = ?",
                (question_id,)
            ).fetchone()
            target = conn.execute(
                "SELECT id, question, sources, original_questions, original_question_sources, ai_answer FROM question_bank WHERE id = ?",
                (req.target_id,)
            ).fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="未找到源聚类")
            if not target:
                raise HTTPException(status_code=404, detail="未找到目标聚类")

            src_orig = json.loads(source['original_questions']) if source['original_questions'] else []
            src_orig_src = json.loads(source['original_question_sources']) if source['original_question_sources'] else []

            is_standalone_merge = not src_orig and original_q == source['question']
            if not is_standalone_merge and original_q not in src_orig:
                raise HTTPException(status_code=400, detail="该原始题目不在源聚类中")

            # 找到要移动的题目的来源
            moving_src = []
            if is_standalone_merge:
                moving_src = json.loads(source['sources']) if source['sources'] else []
            else:
                for item in src_orig_src:
                    if item.get('question') == original_q:
                        moving_src = item.get('sources', [])
                        break

            # 更新目标聚类
            tgt_orig = json.loads(target['original_questions']) if target['original_questions'] else []
            tgt_orig_src = json.loads(target['original_question_sources']) if target['original_question_sources'] else []
            tgt_sources = json.loads(target['sources']) if target['sources'] else []

            tgt_orig.append(original_q)
            tgt_orig_src.append({"question": original_q, "sources": moving_src})

            # 更新目标的 sources
            seen = {(s.get('url', ''), s.get('company', ''), s.get('round', '')) for s in tgt_sources}
            for s in moving_src:
                key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                if key not in seen:
                    seen.add(key)
                    tgt_sources.append(s)

            # 可选：更新目标聚类类别
            cat_set = ""
            cat_params = []
            if req.target_cat1:
                cat_set += ", cat1 = ?"
                cat_params.append(req.target_cat1)
            if req.target_cat2:
                cat_set += ", cat2 = ?"
                cat_params.append(req.target_cat2)

            conn.execute(
                f"UPDATE question_bank SET original_questions = ?, original_question_sources = ?, sources = ?, frequency = ?, updated_at = CURRENT_TIMESTAMP{cat_set} WHERE id = ?",
                [json.dumps(tgt_orig, ensure_ascii=False), json.dumps(tgt_orig_src, ensure_ascii=False),
                 json.dumps(tgt_sources, ensure_ascii=False), len(tgt_orig), *cat_params, req.target_id]
            )

            # Dual-write: insert moved item into target's normalized tables
            for s in moving_src:
                try:
                    insert_source(conn, req.target_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                except Exception:
                    pass
            try:
                insert_original_item(conn, req.target_id, original_q, moving_src)
            except Exception:
                pass

            # 转移 ai_answer（目标没有答案时才转移）
            if source['ai_answer'] and not target['ai_answer']:
                conn.execute("UPDATE question_bank SET ai_answer = ? WHERE id = ?", (source['ai_answer'], req.target_id))

            # 转移收藏记录（跳过用户已在目标题目上的记录）
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, is_starred, personal_tags, note) "
                "SELECT uqv.user_id, ?, uqv.is_starred, uqv.personal_tags, uqv.note "
                "FROM user_question_view uqv WHERE uqv.question_bank_id = ? "
                "AND NOT EXISTS (SELECT 1 FROM user_question_view t WHERE t.user_id = uqv.user_id AND t.question_bank_id = ?)",
                (req.target_id, question_id, req.target_id)
            )

            # 转移练习记录（跳过用户已在目标题目上的记录）
            conn.execute(
                "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, evaluation_result, score, created_at) "
                "SELECT uph.user_id, ?, uph.user_answer, uph.evaluation_result, uph.score, uph.created_at "
                "FROM user_practice_history uph WHERE uph.question_bank_id = ? "
                "AND NOT EXISTS (SELECT 1 FROM user_practice_history t WHERE t.user_id = uph.user_id AND t.question_bank_id = ?)",
                (req.target_id, question_id, req.target_id)
            )

            # 从源聚类中移除
            new_src_orig = [q for q in src_orig if q != original_q]
            new_src_orig_src = [item for item in src_orig_src if item.get('question') != original_q]

            remaining_sources = []
            seen2 = set()
            for item in new_src_orig_src:
                for s in item.get('sources', []):
                    key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                    if key not in seen2:
                        seen2.add(key)
                        remaining_sources.append(s)

            if is_standalone_merge:
                # 独立题合并后删除源（已完整并入目标）
                conn.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                conn.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
            elif len(new_src_orig) == 0:
                conn.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                conn.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
            elif len(new_src_orig) == 1:
                conn.execute(
                    "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_src_orig[0], 1, json.dumps(remaining_sources, ensure_ascii=False), question_id)
                )
            else:
                conn.execute(
                    "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(new_src_orig, ensure_ascii=False), json.dumps(new_src_orig_src, ensure_ascii=False),
                     len(new_src_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                )

            # Dual-write: cleanup source's normalized tables
            if is_standalone_merge or len(new_src_orig) == 0:
                # CASCADE handles cleanup when entire row is deleted
                pass
            else:
                # Delete the moved item, then rebuild source's normalized sources
                try:
                    delete_original_item(conn, question_id, original_q)
                except Exception:
                    pass
                conn.execute("DELETE FROM question_sources WHERE question_bank_id = ?", (question_id,))
                for s in remaining_sources:
                    try:
                        insert_source(conn, question_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                    except Exception:
                        pass

            conn.commit()
            return new_src_orig, new_src_orig_src, question_id, tgt_orig, tgt_orig_src, req.target_id

    def _build_sources_ctx(orig_src_list):
        """从 original_question_sources 格式构建 generate_unified_question 所需的 sources_context"""
        ctx = []
        for item in orig_src_list:
            s = item.get("sources", [{}])[0] if item.get("sources") else {}
            ctx.append({"question": item.get("question", ""), "company": s.get("company", ""), "round": s.get("round", "")})
        return ctx

    try:
        src_remaining, src_remaining_src, src_id, tgt_all, tgt_all_src, tgt_id = await run_db(_merge)

        # 检查哪些聚类被手动编辑过
        def _check_manual_flags():
            with get_db_connection() as conn:
                flags = {}
                for qid in [src_id, tgt_id]:
                    row = conn.execute("SELECT question_manually_edited FROM question_bank WHERE id = ?", (qid,)).fetchone()
                    flags[qid] = bool(row and row['question_manually_edited'])
                return flags
        manual_flags = await run_db(_check_manual_flags)

        # 重新生成源聚类的统一问题（跳过手动编辑过的）
        if len(src_remaining) >= 2:
            if manual_flags.get(src_id):
                logger.info(f"源聚类 {src_id} 代表题已手动编辑，跳过自动重新生成")
            else:
                try:
                    sources_ctx = _build_sources_ctx(src_remaining_src)
                    unified = await generate_unified_question(src_remaining, sources_context=sources_ctx, user_id=admin['id'])
                    def _update_src():
                        with get_db_connection() as conn:
                            conn.execute("UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unified, src_id))
                            conn.commit()
                    await run_db(_update_src)
                except Exception as e:
                    logger.warning(f"合并后重新生成源聚类统一问题失败: {e}")

        # 重新生成目标聚类的统一问题（跳过手动编辑过的）
        if len(tgt_all) >= 2:
            if manual_flags.get(tgt_id):
                logger.info(f"目标聚类 {tgt_id} 代表题已手动编辑，跳过自动重新生成")
            else:
                try:
                    sources_ctx = _build_sources_ctx(tgt_all_src)
                    unified = await generate_unified_question(tgt_all, sources_context=sources_ctx, user_id=admin['id'])
                    def _update_tgt():
                        with get_db_connection() as conn:
                            conn.execute("UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unified, tgt_id))
                            conn.commit()
                    await run_db(_update_tgt)
                except Exception as e:
                    logger.warning(f"合并后重新生成目标聚类统一问题失败: {e}")

        return {"status": "success", "message": "题目已移动到目标聚类"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("合并题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/api/master-bank/use-reference-answer/{question_id}")
async def use_reference_answer(question_id: int, user: dict = Depends(get_current_user)):
    """将管理员的参考答案复制为用户的个人答案"""
    def _get_question():
        with get_db_connection() as conn:
            return conn.execute("SELECT id, question, ai_answer FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get_question)
    if not row:
        raise HTTPException(status_code=404, detail="题目不存在")
    if not row['ai_answer'] or '生成失败' in row['ai_answer']:
        raise HTTPException(status_code=404, detail="该题目暂无参考答案")

    def _upsert_user_answer():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                (user['id'], question_id, row['ai_answer'], row['ai_answer'])
            )
            conn.commit()

    await run_db(_upsert_user_answer)
    return {"status": "success", "answer": row['ai_answer']}


@router.put("/api/master-bank/save-user-answer/{question_id}")
async def save_user_answer(question_id: int, body: dict, user: dict = Depends(get_current_user)):
    """保存用户的个人答案（手动编辑）"""
    answer = body.get("answer", "")
    def _upsert():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                (user['id'], question_id, answer, answer)
            )
            conn.commit()
    await run_db(_upsert)
    return {"status": "success"}


@router.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int, user: dict = Depends(get_current_user)):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, ai_answer FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)

    is_admin = user.get('is_admin', False)

    # 管理员：如果已有有效答案，直接返回（兼容旧行为）
    if is_admin and row['ai_answer'] and '生成失败' not in row['ai_answer']:
        return {"status": "success", "answer": row['ai_answer']}

    try:
        prompt = ANSWER_PROMPT.replace("{question}", row['question'])
        answer = await _call_llm_with_retry(prompt, user_id=user['id'])

        if is_admin:
            # 管理员：存入 question_bank.ai_answer（全局）
            def _update():
                with get_db_connection() as conn:
                    conn.execute("UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                    conn.commit()
            await run_db(_update)
        else:
            # 普通用户：存入 user_question_view.user_answer（个人）
            def _upsert():
                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                        (user['id'], question_id, answer, answer)
                    )
                    conn.commit()
            await run_db(_upsert)

        return {"status": "success", "answer": answer}
    except openai.AuthenticationError:
        raise HTTPException(status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。")
    except openai.APITimeoutError:
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。")
    except Exception as e:
        logger.error(f"手动生成答案失败（已重试3次）[ID:{question_id}]: {e}")
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


@router.post("/api/master-bank/batch-generate-answers")
async def batch_generate_answers(req: BatchGenerateAnswersRequest, user: dict = Depends(get_current_user)):
    """批量生成答案（SSE 流式推送进度）"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _load():
        with get_db_connection() as conn:
            placeholders = ",".join("?" * len(req.ids))
            return conn.execute(
                f"SELECT id, question, ai_answer FROM question_bank WHERE id IN ({placeholders})", req.ids
            ).fetchall()

    rows = await run_db(_load)
    if not rows:
        raise HTTPException(status_code=404, detail="未找到任何匹配题目")

    questions = [(r["id"], r["question"]) for r in rows
                 if r["question"] and (not r["ai_answer"] or '生成失败' in r["ai_answer"])]
    skipped = len(rows) - len(questions)

    async def event_stream():
        try:
            if not questions:
                yield f"data: {json.dumps({'type': 'done', 'generated': 0, 'failed': 0, 'skipped': skipped})}\n\n"
                return

            total = len(questions)
            generated = 0
            failed = 0
            done_count = 0
            results_lock = asyncio.Lock()

            # 先发送 init 事件
            yield f"data: {json.dumps({'type': 'init', 'total': total, 'skipped': skipped})}\n\n"

            semaphore = asyncio.Semaphore(3)

            async def _gen_one(idx, qid, question_text):
                nonlocal generated, failed, done_count
                async with semaphore:
                    try:
                        prompt = ANSWER_PROMPT.replace("{question}", question_text)
                        answer = await _call_llm_with_retry(prompt, user_id=user['id'])
                        def _update():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (answer, qid)
                                )
                                conn.commit()
                        await run_db(_update)
                        async with results_lock:
                            generated += 1
                            done_count += 1
                            yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': True})
                    except Exception as e:
                        logger.error(f"批量生成答案失败 [ID:{qid}]: {e}")
                        def _mark_failed():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (qid,)
                                )
                                conn.commit()
                        await run_db(_mark_failed)
                        async with results_lock:
                            failed += 1
                            done_count += 1
                            yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': False})
                return yield_event

            # 并发执行但按完成顺序收集事件
            tasks = [_gen_one(i, qid, qtext) for i, (qid, qtext) in enumerate(questions)]

            for coro in asyncio.as_completed(tasks):
                event_data = await coro
                yield f"data: {event_data}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'generated': generated, 'failed': failed, 'skipped': skipped})}\n\n"
        except Exception as e:
            logger.exception("批量生成答案失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/master-bank/re-tag/{question_id}")
async def retag_master_question(question_id: int, user: dict = Depends(get_admin_user)):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, cat1, cat2, tags, difficulty FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)

    if not row or not row['question']:
        raise HTTPException(status_code=404, detail="未找到该题目")

    question_text = row['question']
    current_cat1 = row['cat1'] or '未分类'
    current_cat2 = row['cat2'] or '未分类'
    current_tags = row['tags'] or ''
    current_diff = row['difficulty'] or '未知'

    # 读取当前岗位的分类体系
    taxonomy_config = await run_db(get_taxonomy_for_position)

    # 在 prompt 中告知当前分类，要求 LLM 重新审视并给出更准确的分类
    input_data = [{"id": question_id, "题目": question_text}]
    q_json = json.dumps(input_data, ensure_ascii=False)
    prompt = build_tagging_prompt(taxonomy_config) if taxonomy_config else TAGGING_PROMPT
    user_msg = prompt.replace("{questions}", q_json)
    user_msg += f"""

## ⚠️ 重要：重新审视请求
该题目当前的分类结果如下，请仔细重新审视是否准确：
- 当前一级大类：{current_cat1}
- 当前二级子类：{current_cat2}
- 当前考点标签：{current_tags}
- 当前难度：{current_diff}

如果当前分类不准确，请给出更合适的分类。如果当前分类已经准确，请保持不变。
请特别注意：
1. 一级大类和二级子类必须严格匹配（如选了A则二级必须是A1-A4）
2. 考点标签应选择与题目内容最直接相关的技术领域
3. 难度应根据题目实际考察深度判断
"""

    try:
        _c, _m, _t, _bu, _provider = get_llm_client_for_user(admin['id'])
        response_text = await raw_llm_call(
            admin['id'],
            model=_m,
            messages=[
                {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。请仔细分析题目内容，给出最准确的分类。"},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.2,
        )

        parsed_result = _extract_json(response_text)
        items = parsed_result.get("questions", [])

        if not items:
            raise ValueError("大模型未返回有效的分类数据")

        item = items[0]
        cat1 = normalize_category(item.get("一级大类", "未分类"))
        cat2 = normalize_category(item.get("二级子类", "未分类"))
        tags = item.get("考点标签", "")
        diff = item.get("难度标签", "未知")

        def _update():
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE question_bank SET cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (cat1, cat2, tags, diff, question_id)
                )
                conn.execute(
                    "UPDATE questions_detail SET cat1 = ?, cat2 = ?, tags = ?, diff_tag = ?, updated_at = CURRENT_TIMESTAMP WHERE question = ?",
                    (cat1, cat2, tags, diff, question_text)
                )
                conn.commit()

        await run_db(_update)

        return {
            "status": "success",
            "message": "题目重新打标成功",
            "data": {"cat1": cat1, "cat2": cat2, "tags": tags, "difficulty": diff}
        }

    except openai.AuthenticationError:
        raise HTTPException(status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。")
    except openai.APITimeoutError:
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。")
    except Exception as e:
        logger.exception("重新打标失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.get("/api/master-bank/random")
async def get_random_questions(
    count: int = Query(5, ge=1, le=50),
    cat1: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    user: dict = Depends(get_current_user)
):
    """加权随机抽题，避免重复抽取近期练过的题目"""

    from_clause, where_clause, base_params = _build_bank_where_clause(user, "qb")

    def _query():
        with get_db_connection() as conn:
            conditions = []
            params = list(base_params)
            if cat1:
                conditions.append("qb.cat1 LIKE ?")
                params.append(f"%{cat1}%")
            if difficulty:
                conditions.append("qb.difficulty LIKE ?")
                params.append(f"%{difficulty}%")

            if conditions:
                where_with_extra = f"{where_clause} AND {' AND '.join(conditions)}"
            else:
                where_with_extra = where_clause

            dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user['id'])
            candidates = conn.execute(
                f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, ({dyn_freq_sql}) as frequency, qb.ai_answer {from_clause} {where_with_extra}",
                params
            ).fetchall()

            if not candidates:
                return [], {}

            ids = [r['id'] for r in candidates]
            placeholders = ",".join("?" * len(ids))

            # 查询当前用户的练习历史
            uid = user['id'] if user else None
            if uid:
                stats = conn.execute(
                    f"SELECT question_bank_id, COUNT(*) as cnt, MAX(created_at) as last_at FROM user_practice_history WHERE user_id = ? AND question_bank_id IN ({placeholders}) GROUP BY question_bank_id",
                    [uid] + ids
                ).fetchall()
            else:
                stats = []

            practice_map = {}
            now = time.time()
            for s in stats:
                qid = s['question_bank_id']
                try:
                    from datetime import datetime
                    last_dt = datetime.fromisoformat(s['last_at'])
                    hours_ago = (now - last_dt.timestamp()) / 3600
                except Exception:
                    hours_ago = 9999
                practice_map[qid] = {"count": s['cnt'], "hours_ago": hours_ago}

            return candidates, practice_map

    candidates, practice_map = await run_db(_query)

    if not candidates:
        return []

    # 计算每个题目的抽选权重
    weights = []
    for r in candidates:
        qid = r['id']
        if qid not in practice_map:
            w = 1.5  # 未练习过的题目加权
        else:
            info = practice_map[qid]
            w = 1.0 / (1 + info['count'] * 0.3)  # 重复因子
            if info['hours_ago'] < 24:
                w *= 0.3  # 24h 内练过，大幅降权
            elif info['hours_ago'] < 72:
                w *= 0.7  # 1-3 天内，适度降权
        weights.append(max(w, 0.01))

    # 加权无放回采样
    selected_indices = []
    remaining = list(range(len(candidates)))
    remaining_weights = list(weights)
    for _ in range(min(count, len(candidates))):
        total = sum(remaining_weights)
        if total <= 0:
            break
        r = _random.random() * total
        cumulative = 0
        chosen_idx = 0
        for i, w in enumerate(remaining_weights):
            cumulative += w
            if cumulative >= r:
                chosen_idx = i
                break
        selected_indices.append(remaining[chosen_idx])
        remaining.pop(chosen_idx)
        remaining_weights.pop(chosen_idx)

    # Fetch sources from normalized tables for selected questions
    selected_ids = [candidates[idx]['id'] for idx in selected_indices]
    def _fetch_sources():
        with get_db_connection() as conn2:
            try:
                return {qid: get_sources(conn2, qid) for qid in selected_ids}
            except Exception:
                return {}
    sources_map = await run_db(_fetch_sources)

    result = []
    for idx in selected_indices:
        r = candidates[idx]
        d = dict(r)
        d['sources'] = sources_map.get(r['id'], [])
        info = practice_map.get(r['id'])
        d['attempt_count'] = info['count'] if info else 0
        d['last_practiced_at'] = info.get('last_at') if info else None
        result.append(d)

    return result


@router.post("/api/evaluate-answer")
async def evaluate_answer(req: EvaluateAnswerRequest, user: dict = Depends(get_current_user)):
    """对比用户答案与 AI 参考答案，返回多维度评估结果"""
    if not req.user_answer.strip():
        raise HTTPException(status_code=400, detail="用户答案不能为空")
    if not req.reference_answer.strip():
        raise HTTPException(status_code=400, detail="参考答案不能为空")

    prompt = EVAL_PROMPT.format(
        question=req.question_text,
        user_answer=req.user_answer[:3000],
        reference_answer=req.reference_answer[:3000]
    )

    try:
        raw = await _call_llm_with_retry(
            prompt=prompt,
            system_msg="你是一名专业的技术面试评估专家。",
            user_id=user['id'],
        )
        result = _extract_json(raw)

        # 防御性解析：确保必要字段存在
        result.setdefault("overall_score", 0)
        result.setdefault("dimensions", {})
        result.setdefault("strengths", [])
        result.setdefault("weaknesses", [])
        result.setdefault("suggestions", "")

        for dim_key in ("completeness", "depth", "accuracy", "logic"):
            result["dimensions"].setdefault(dim_key, {"score": 0, "comment": ""})

        # 钳制分数范围
        result["overall_score"] = max(0, min(100, int(result["overall_score"])))
        for dim in result["dimensions"].values():
            dim["score"] = max(0, min(100, int(dim.get("score", 0))))

        # 自动记录练习历史（写入 user_practice_history，关联用户）
        if req.question_id:
            def _record():
                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, evaluation_result, score) VALUES (?, ?, ?, ?, ?)",
                        (user['id'], req.question_id, req.user_answer, json.dumps(result, ensure_ascii=False), result["overall_score"])
                    )
                    conn.commit()
            try:
                await run_db(_record)
            except Exception as e:
                logger.warning(f"记录练习历史失败（不影响评估结果）: {e}")

        return result

    except json.JSONDecodeError as e:
        logger.error(f"评估结果 JSON 解析失败: {e}")
        raise HTTPException(status_code=500, detail="评估结果解析失败，LLM 未返回有效 JSON，请重试")
    except openai.AuthenticationError:
        logger.error("评估失败: API Key 无效")
        raise HTTPException(status_code=500, detail="API Key 无效或已过期，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        logger.error("评估失败: LLM 连接失败")
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL 是否正确。")
    except openai.APITimeoutError:
        logger.error("评估失败: LLM 调用超时")
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请在系统配置中增大超时时间或稍后重试。")
    except Exception as e:
        logger.exception("答案评估失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.get("/api/practice-history/{question_id}")
async def get_practice_history(question_id: int, user: dict = Depends(get_current_user)):
    """获取指定题目的练习历史（当前用户的）"""
    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, question_bank_id, user_answer, evaluation_result, score, created_at FROM user_practice_history WHERE question_bank_id = ? AND user_id = ? ORDER BY created_at DESC",
                (question_id, user['id'])
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['evaluation_result'] = json.loads(d['evaluation_result']) if d['evaluation_result'] else None
        except Exception:
            d['evaluation_result'] = None
        result.append(d)
    return result


# ── 上传到题库 ──


@router.post("/api/master-bank/upload")
async def upload_to_bank(req: UploadToBankRequest, user: dict = Depends(get_current_user)):
    """上传题目到题库"""
    if req.target not in ('public', 'personal'):
        raise HTTPException(status_code=400, detail="target 可选: public / personal")

    def _insert():
        with get_db_connection() as conn:
            current_pos = get_current_job_position()
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


# ── 管理员审核 ──

@router.get("/api/master-bank/pending")
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


@router.post("/api/master-bank/approve/{question_id}")
async def approve_question(question_id: int, admin: dict = Depends(get_admin_user)):
    """审核通过题目"""
    def _approve():
        with get_db_connection() as conn:
            row = conn.execute("SELECT id, status FROM question_bank WHERE id = ? AND owner_id IS NULL", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该待审核题目")
            conn.execute("UPDATE question_bank SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
            conn.commit()

    await run_db(_approve)
    return {"status": "success", "message": "已通过审核"}


@router.post("/api/master-bank/reject/{question_id}")
async def reject_question(question_id: int, admin: dict = Depends(get_admin_user)):
    """拒绝题目"""
    def _reject():
        with get_db_connection() as conn:
            row = conn.execute("SELECT id, status FROM question_bank WHERE id = ? AND owner_id IS NULL", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该待审核题目")
            conn.execute("UPDATE question_bank SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
            conn.commit()

    await run_db(_reject)
    return {"status": "success", "message": "已拒绝"}

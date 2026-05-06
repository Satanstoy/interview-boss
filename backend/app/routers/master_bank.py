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
from app.db.connection import get_db_connection, run_db
from app.models.schemas import BatchDeleteRequest, BatchGenerateAnswersRequest, EvaluateAnswerRequest, SplitQuestionRequest, MergeOriginalQuestionRequest
from app.services.llm import client, _call_llm_with_retry, _extract_json, _should_use_response_format
from app.services.clustering import cluster_all_questions, generate_unified_question
from app.services.utils import normalize_category

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _build_bank_where_clause(user: dict, table_alias: str = "qb"):
    """根据用户 bank_mode 构建 WHERE 子句"""
    prefix = f"{table_alias}." if table_alias else ""
    mode = user.get('bank_mode', 'public')
    uid = user['id']

    if mode == 'personal':
        return f"WHERE {prefix}owner_id = ?", [uid]
    elif mode == 'mixed':
        return f"WHERE ({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR {prefix}owner_id = ?", [uid]
    else:  # 'public'
        return f"WHERE {prefix}owner_id IS NULL AND {prefix}status = 'approved'", []


@router.get("/api/master-bank")
async def get_master_bank(
    sort: str = "frequency_desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    user: dict = Depends(get_current_user)
):
    order_clause = "ORDER BY frequency DESC" if sort != "recent" else "ORDER BY id DESC"
    offset = (page - 1) * page_size
    where_clause, params = _build_bank_where_clause(user)

    def _query():
        with get_db_connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM question_bank qb {where_clause}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, qb.frequency, qb.ai_answer, qb.sources, qb.original_questions, qb.original_question_sources, qb.is_starred, qb.owner_id, qb.status "
                f"FROM question_bank qb {where_clause} {order_clause} LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except Exception:
            d['sources'] = []
        try:
            d['original_questions'] = json.loads(d['original_questions']) if d['original_questions'] else []
        except Exception:
            d['original_questions'] = []
        try:
            d['original_question_sources'] = json.loads(d['original_question_sources']) if d['original_question_sources'] else []
        except Exception:
            d['original_question_sources'] = []
        d['is_personal'] = d.get('owner_id') is not None
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
    where_clause, params = _build_bank_where_clause(user)
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
        with get_db_connection() as conn:
            rows = conn.execute(
                f"SELECT qb.id, qb.question, qb.frequency FROM question_bank qb {where_with_extra} ORDER BY qb.frequency DESC LIMIT ?",
                search_params + [limit]
            ).fetchall()
            return [dict(r) for r in rows]

    items = await run_db(_query)
    return {"items": items}


@router.post("/api/master-bank/build")
async def build_master_bank(admin: dict = Depends(get_admin_user)):
    """全量重建题库：保留已有的 AI 答案，使用 LLM 聚类去重"""
    # 重建前自动备份数据库
    backup_path = f"{DB_PATH}.bak.build.{int(time.time())}"
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"全量重建前已创建数据库备份: {backup_path}")
    except Exception as e:
        logger.warning(f"创建备份失败（不影响重建流程）: {e}")

    def _load():
        with get_db_connection() as conn:
            raw = conn.execute(
                "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
                "FROM questions_detail qd WHERE qd.question IS NOT NULL AND qd.question != ''"
            ).fetchall()
            # 保留已有的 ai_answer（纯文本精确匹配恢复）
            existing = conn.execute(
                "SELECT question, ai_answer FROM question_bank WHERE ai_answer IS NOT NULL AND ai_answer != ''"
            ).fetchall()
            existing_answers_map = {r['question']: r['ai_answer'] for r in existing}
            return raw, existing_answers_map

    raw_questions, existing_answers_map = await run_db(_load)

    if not raw_questions:
        return {"status": "error", "detail": "没有数据"}

    logger.info(f"全量重建: 正在对 {len(raw_questions)} 道题目进行 LLM 聚类...")
    all_clusters = await cluster_all_questions(raw_questions)

    # 构建聚类结果的详细信息
    id_map = {r['id']: dict(r) for r in raw_questions}
    cluster_details = []

    # 先收集所有聚类的基本信息，合并组需要生成统一问题
    merge_groups = []  # (index, questions_list)
    for c in all_clusters:
        ids = c.get("ids", [])
        rows_in_cluster = [id_map[qid] for qid in ids if qid in id_map]
        if not rows_in_cluster:
            continue

        # 合并来源（聚类级别）
        sources = []
        seen_sources = set()
        for r in rows_in_cluster:
            src = {"url": r.get('url', ''), "company": r.get('company', ''), "round": r.get('round', '')}
            src_key = (src['url'], src['company'], src['round'])
            if src_key not in seen_sources:
                seen_sources.add(src_key)
                sources.append(src)

        # 每个原始题目的来源（per-question sources）
        orig_q_sources = []
        for r in rows_in_cluster:
            src = {"url": r.get('url', ''), "company": r.get('company', ''), "round": r.get('round', '')}
            orig_q_sources.append({"question": r['question'], "sources": [src]})

        # 合并分类和标签
        cat1_set = set()
        tags_set = set()
        diffs = []
        for r in rows_in_cluster:
            if r.get('cat1'):
                cat1_set.add(normalize_category(r['cat1']))
            if r.get('tags'):
                for t in str(r['tags']).split(','):
                    if t.strip():
                        tags_set.add(t.strip())
            if r.get('diff_tag'):
                diffs.append(r['diff_tag'])

        diff_str = Counter(diffs).most_common(1)[0][0] if diffs else "未知"

        original_qs = [r['question'] for r in rows_in_cluster]

        detail = {
            'question': '',  # 稍后填充
            'original_questions': original_qs,
            'original_question_sources': orig_q_sources,
            'cat1': cat1_set,
            'tags': tags_set,
            'difficulty': diff_str,
            'frequency': len(rows_in_cluster),
            'sources': sources,
        }
        cluster_details.append(detail)

        if len(rows_in_cluster) >= 2:
            merge_groups.append((len(cluster_details) - 1, original_qs))

    # 为合并组生成统一问题（限流并发，避免 429）
    if merge_groups:
        logger.info(f"正在为 {len(merge_groups)} 个合并组生成统一问题...")
        sem = asyncio.Semaphore(8)

        async def _gen_unified(idx, questions):
            async with sem:
                unified = await generate_unified_question(questions)
                return idx, unified

        tasks = [_gen_unified(idx, qs) for idx, qs in merge_groups]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"生成统一问题失败: {result}")
                continue
            idx, unified = result
            cluster_details[idx]['question'] = unified

    # 单题聚类：直接用原始题目，original_questions 为空
    for detail in cluster_details:
        if not detail['question']:
            # 单题聚类，question = 唯一的原始题目
            detail['question'] = detail['original_questions'][0] if detail['original_questions'] else ''
            detail['original_questions'] = []
            detail['original_question_sources'] = []

    def _save():
        with get_db_connection() as conn:
            admin_id = conn.execute("SELECT id FROM users WHERE username = 'sj'").fetchone()
            admin_id = admin_id[0] if admin_id else None

            conn.execute("DELETE FROM question_bank")
            restored_count = 0
            for c in cluster_details:
                # 精确文本匹配恢复答案（统一问题 or 原始题目）
                ai_answer = existing_answers_map.get(c['question'])
                if not ai_answer:
                    for oq in c.get('original_questions', []):
                        ai_answer = existing_answers_map.get(oq)
                        if ai_answer:
                            break
                if ai_answer:
                    restored_count += 1

                orig_qs_json = json.dumps(c.get('original_questions', []), ensure_ascii=False)
                orig_qs_src_json = json.dumps(c.get('original_question_sources', []), ensure_ascii=False)
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, tags, difficulty, frequency, sources, original_questions, original_question_sources, ai_answer, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'approved')",
                    (c['question'], ",".join(c['cat1']), ",".join(c['tags']), c['difficulty'],
                     c['frequency'], json.dumps(c['sources'], ensure_ascii=False), orig_qs_json, orig_qs_src_json, ai_answer, admin_id)
                )
            conn.commit()
            logger.info(f"答案恢复: 精确匹配 {restored_count} 条")

    await run_db(_save)
    logger.info(f"全量重建完成: {len(cluster_details)} 道核心真题")
    return {"status": "success", "total_unique": len(cluster_details)}


@router.post("/api/master-bank/toggle-star/{question_id}")
async def toggle_star(question_id: int, user: dict = Depends(get_current_user)):
    """切换题目收藏状态"""
    def _toggle():
        with get_db_connection() as conn:
            row = conn.execute("SELECT is_starred FROM question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目")
            new_val = 0 if row['is_starred'] else 1
            conn.execute("UPDATE question_bank SET is_starred = ? WHERE id = ?", (new_val, question_id))
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
            row = conn.execute(
                "SELECT id, question, sources, original_questions, original_question_sources, cat1, tags, difficulty FROM question_bank WHERE id = ?",
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

            # 创建新的独立题目
            conn.execute(
                "INSERT INTO question_bank (question, cat1, tags, difficulty, frequency, sources, original_questions, original_question_sources, ai_answer, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, 1, ?, '[]', '[]', NULL, NULL, ?, 'approved')",
                (original_q, row['cat1'], row['tags'], row['difficulty'],
                 json.dumps(split_sources, ensure_ascii=False), admin.id if hasattr(admin, 'id') else None)
            )
            new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

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
                conn.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
            elif len(new_orig) == 1:
                conn.execute(
                    "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = 1, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_orig[0], json.dumps(remaining_sources, ensure_ascii=False), question_id)
                )
            else:
                conn.execute(
                    "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(new_orig, ensure_ascii=False), json.dumps(new_orig_src, ensure_ascii=False),
                     len(new_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                )

            conn.commit()
            return new_id, new_orig, question_id

    try:
        new_id, remaining_orig, old_id = await run_db(_split)

        # 如果原聚类还有多题，重新生成统一问题
        if len(remaining_orig) >= 2:
            try:
                unified = await generate_unified_question(remaining_orig)
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
        raise HTTPException(status_code=500, detail=f"拆分失败: {str(e)[:200]}")


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
                "SELECT id, question, sources, original_questions, original_question_sources FROM question_bank WHERE id = ?",
                (question_id,)
            ).fetchone()
            target = conn.execute(
                "SELECT id, question, sources, original_questions, original_question_sources FROM question_bank WHERE id = ?",
                (req.target_id,)
            ).fetchone()
            if not source:
                raise HTTPException(status_code=404, detail="未找到源聚类")
            if not target:
                raise HTTPException(status_code=404, detail="未找到目标聚类")

            src_orig = json.loads(source['original_questions']) if source['original_questions'] else []
            src_orig_src = json.loads(source['original_question_sources']) if source['original_question_sources'] else []

            if original_q not in src_orig:
                raise HTTPException(status_code=400, detail="该原始题目不在源聚类中")

            # 找到要移动的题目的来源
            moving_src = []
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

            conn.execute(
                "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, sources = ?, frequency = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(tgt_orig, ensure_ascii=False), json.dumps(tgt_orig_src, ensure_ascii=False),
                 json.dumps(tgt_sources, ensure_ascii=False), len(tgt_orig), req.target_id)
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

            if len(new_src_orig) == 0:
                conn.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
            elif len(new_src_orig) == 1:
                conn.execute(
                    "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = 1, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_src_orig[0], json.dumps(remaining_sources, ensure_ascii=False), question_id)
                )
            else:
                conn.execute(
                    "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(new_src_orig, ensure_ascii=False), json.dumps(new_src_orig_src, ensure_ascii=False),
                     len(new_src_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                )

            conn.commit()
            return new_src_orig, question_id, tgt_orig, req.target_id

    try:
        src_remaining, src_id, tgt_all, tgt_id = await run_db(_merge)

        # 重新生成源聚类的统一问题
        if len(src_remaining) >= 2:
            try:
                unified = await generate_unified_question(src_remaining)
                def _update_src():
                    with get_db_connection() as conn:
                        conn.execute("UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unified, src_id))
                        conn.commit()
                await run_db(_update_src)
            except Exception as e:
                logger.warning(f"合并后重新生成源聚类统一问题失败: {e}")

        # 重新生成目标聚类的统一问题
        if len(tgt_all) >= 2:
            try:
                unified = await generate_unified_question(tgt_all)
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
        raise HTTPException(status_code=500, detail=f"合并失败: {str(e)[:200]}")


@router.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int, user: dict = Depends(get_current_user)):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, ai_answer FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)
    # 如果已有有效答案（非失败标记），直接返回
    if row['ai_answer'] and '生成失败' not in row['ai_answer']:
        return {"status": "success", "answer": row['ai_answer']}

    try:
        prompt = ANSWER_PROMPT.replace("{question}", row['question'])
        answer = await _call_llm_with_retry(prompt)

        def _update():
            with get_db_connection() as conn:
                conn.execute("UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                conn.commit()

        await run_db(_update)
        return {"status": "success", "answer": answer}
    except openai.AuthenticationError:
        raise HTTPException(status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。")
    except openai.APITimeoutError:
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。")
    except Exception as e:
        logger.error(f"手动生成答案失败（已重试3次）[ID:{question_id}]: {e}")
        raise HTTPException(status_code=500, detail=f"生成答案失败: {str(e)[:200]}")


@router.delete("/api/master-bank/{question_id}")
async def delete_master_question(question_id: int, user: dict = Depends(get_current_user)):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT id, question, sources FROM question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")

            # 联动清理 questions_detail 中对应的记录
            question_text = row['question']
            if question_text:
                cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))

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
                f"SELECT id, question FROM question_bank WHERE id IN ({placeholders})", req.ids
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            question_texts = [r["question"] for r in rows if r["question"]]
            if question_texts:
                qph = ",".join("?" * len(question_texts))
                cursor.execute(f"DELETE FROM questions_detail WHERE question IN ({qph})", question_texts)

            found_ids = [r["id"] for r in rows]
            ph2 = ",".join("?" * len(found_ids))
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
                    answer = await _call_llm_with_retry(prompt)
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

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/api/master-bank/re-tag/{question_id}")
async def retag_master_question(question_id: int, user: dict = Depends(get_current_user)):
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

    # 读取用户自定义分类体系
    def _get_taxonomy():
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM user_profile WHERE key = 'taxonomy_config'").fetchone()
            if row and row['value']:
                try:
                    return json.loads(row['value'])
                except json.JSONDecodeError:
                    pass
            return None

    taxonomy_config = await run_db(_get_taxonomy)

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
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。请仔细分析题目内容，给出最准确的分类。"},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.2,
        )

        parsed_result = _extract_json(response.choices[0].message.content)
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
                    "UPDATE questions_detail SET cat1 = ?, cat2 = ?, tags = ?, diff_tag = ? WHERE question = ?",
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
        raise HTTPException(status_code=500, detail=f"重新打标失败: {str(e)[:200]}")


@router.get("/api/master-bank/random")
async def get_random_questions(
    count: int = Query(5, ge=1, le=50),
    cat1: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    user: dict = Depends(get_current_user)
):
    """加权随机抽题，避免重复抽取近期练过的题目"""

    where_clause, base_params = _build_bank_where_clause(user, "qb")

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

            candidates = conn.execute(
                f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, qb.frequency, qb.ai_answer, qb.sources FROM question_bank qb {where_with_extra}",
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

    result = []
    for idx in selected_indices:
        r = candidates[idx]
        d = dict(r)
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except Exception:
            d['sources'] = []
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
        raise HTTPException(status_code=500, detail=f"评估失败: {str(e)[:200]}")


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

class UploadToBankRequest(BatchGenerateAnswersRequest):
    """复用 ids 结构，额外字段用 Query"""
    pass


@router.post("/api/master-bank/upload")
async def upload_to_bank(
    question_text: str = Query(..., max_length=5000),
    cat1: str = Query("", max_length=100),
    cat2: str = Query("", max_length=100),
    tags: str = Query("", max_length=500),
    difficulty: str = Query("", max_length=20),
    target: str = Query("public"),  # 'public' or 'personal'
    user: dict = Depends(get_current_user)
):
    """上传题目到题库"""
    if target not in ('public', 'personal'):
        raise HTTPException(status_code=400, detail="target 可选: public / personal")

    def _insert():
        with get_db_connection() as conn:
            if target == 'personal':
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved')",
                    (question_text, cat1, cat2, tags, difficulty, user['id'], user['id'])
                )
            else:
                conn.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, owner_id, submitted_by, status) VALUES (?, ?, ?, ?, ?, NULL, ?, 'pending')",
                    (question_text, cat1, cat2, tags, difficulty, user['id'])
                )
            conn.commit()

    await run_db(_insert)
    status_msg = "已加入个人题库" if target == 'personal' else "已提交到公共题库，等待管理员审核"
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
            conn.execute("UPDATE question_bank SET status = 'approved' WHERE id = ?", (question_id,))
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
            conn.execute("UPDATE question_bank SET status = 'rejected' WHERE id = ?", (question_id,))
            conn.commit()

    await run_db(_reject)
    return {"status": "success", "message": "已拒绝"}


@router.post("/api/master-bank/batch-retag")
async def batch_retag(req: dict, user: dict = Depends(get_current_user)):
    """批量重新标注所有题目（岗位/分类体系变更后使用），SSE 流式返回进度"""

    taxonomy_config = req.get("taxonomy_config")
    if not taxonomy_config or not isinstance(taxonomy_config.get("categories"), list):
        raise HTTPException(status_code=400, detail="taxonomy_config 无效")

    # 先保存新的分类体系
    def _save_taxonomy():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                ("taxonomy_config", json.dumps(taxonomy_config, ensure_ascii=False))
            )
            conn.commit()

    await run_db(_save_taxonomy)

    # 获取所有题目
    def _get_questions():
        with get_db_connection() as conn:
            return conn.execute("SELECT id, question FROM question_bank WHERE question IS NOT NULL AND question != ''").fetchall()

    rows = await run_db(_get_questions)
    prompt = build_tagging_prompt(taxonomy_config)

    async def event_stream():
        if not rows:
            yield f"data: {json.dumps({'type': 'done', 'retagged': 0, 'failed': 0})}\n\n"
            return

        total = len(rows)
        retagged = 0
        failed = 0
        done_count = 0
        results_lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(3)

        yield f"data: {json.dumps({'type': 'init', 'total': total})}\n\n"

        async def _retag_one(idx, qid, question_text):
            nonlocal retagged, failed, done_count
            async with semaphore:
                try:
                    input_data = [{"id": 0, "题目": question_text}]
                    q_json = json.dumps(input_data, ensure_ascii=False)
                    user_msg = prompt.replace("{questions}", q_json)

                    kwargs = dict(
                        model=LLM_MODEL,
                        messages=[
                            {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。"},
                            {"role": "user", "content": user_msg}
                        ],
                        temperature=0.0,
                    )
                    if _should_use_response_format():
                        kwargs["response_format"] = {"type": "json_object"}
                    response = await client.chat.completions.create(**kwargs)
                    items = _extract_json(response.choices[0].message.content).get("questions", [])
                    if items:
                        item = items[0]
                        cat1 = normalize_category(item.get("一级大类", "未分类"))
                        cat2 = normalize_category(item.get("二级子类", "未分类"))
                        tags = item.get("考点标签", "")
                        diff = item.get("难度标签", "未知")

                        def _update():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (cat1, cat2, tags, diff, qid)
                                )
                                conn.commit()
                        await run_db(_update)
                        async with results_lock:
                            retagged += 1
                            done_count += 1
                        return json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'cat1': cat1, 'success': True})
                    else:
                        raise ValueError("LLM 未返回有效数据")
                except Exception as e:
                    logger.error(f"批量重标失败 [ID:{qid}]: {e}")
                    async with results_lock:
                        failed += 1
                        done_count += 1
                    return json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': False})

        tasks = [_retag_one(i, r['id'], r['question']) for i, r in enumerate(rows)]
        for coro in asyncio.as_completed(tasks):
            event_data = await coro
            yield f"data: {event_data}\n\n"

        yield f"data: {json.dumps({'type': 'done', 'retagged': retagged, 'failed': failed})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

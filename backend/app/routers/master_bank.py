import os
import json
import time
import shutil
import logging
import asyncio
import numpy as np
from collections import Counter
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from app.core.config import DB_PATH, LLM_MODEL, EMBEDDING_MODEL, SIMILARITY_THRESHOLD
from app.core.prompts import TAGGING_PROMPT, ANSWER_PROMPT
from app.db.connection import get_db_connection, run_db
from app.services.llm import client, client_of_embedding, _call_llm_with_retry
from app.services.embedding import cosine_similarity, cosine_similarity_batch
from app.services.utils import normalize_category

logger = logging.getLogger("multimodal-parser")

router = APIRouter()


@router.get("/api/master-bank")
async def get_master_bank(sort: str = "frequency_desc", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=1000)):
    order_clause = "ORDER BY frequency DESC" if sort != "recent" else "ORDER BY id DESC"
    offset = (page - 1) * page_size

    def _query():
        with get_db_connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM master_question_bank").fetchone()[0]
            rows = conn.execute(f"SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, sources, is_starred FROM master_question_bank {order_clause} LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except Exception:
            d['sources'] = []
        result.append(d)

    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.post("/api/master-bank/build")
async def build_master_bank():
    """全量重建题库：保留已有的 AI 答案，使用 Embedding 语义聚类"""
    # 重建前自动备份数据库
    backup_path = f"{DB_PATH}.bak.build.{int(time.time())}"
    try:
        shutil.copy2(DB_PATH, backup_path)
        logger.info(f"全量重建前已创建数据库备份: {backup_path}")
    except Exception as e:
        logger.warning(f"创建备份失败（不影响重建流程）: {e}")

    def _load():
        with get_db_connection() as conn:
            raw = conn.execute("SELECT * FROM questions_detail").fetchall()
            # 保留已有的 ai_answer 及其向量，用于重建后按语义匹配恢复
            existing = conn.execute(
                "SELECT question, ai_answer, vector FROM master_question_bank WHERE ai_answer IS NOT NULL AND ai_answer != ''"
            ).fetchall()
            existing_answers_map = {}
            for r in existing:
                vec = None
                if r['vector']:
                    try:
                        vec = json.loads(r['vector'])
                    except Exception:
                        pass
                existing_answers_map[r['question']] = {
                    "ai_answer": r['ai_answer'],
                    "vector": vec
                }
            return raw, existing_answers_map

    raw_questions, existing_answers_map = await run_db(_load)

    if not raw_questions:
        return {"status": "error", "detail": "没有数据"}
    texts = [q['question'] for q in raw_questions if q['question'].strip()]

    logger.info(f"全量重建: 正在提取 {len(texts)} 道题目特征...")
    semaphore = asyncio.Semaphore(5)

    async def _fetch_batch(batch_texts):
        async with semaphore:
            resp = await client_of_embedding.embeddings.create(input=batch_texts, model=EMBEDDING_MODEL)
            return [d.embedding for d in resp.data]

    batches = []
    for i in range(0, len(texts), 100):
        batch_texts = [t.replace("\n", " ") for t in texts[i:i+100]]
        batches.append(_fetch_batch(batch_texts))

    batch_results = await asyncio.gather(*batches)
    embeddings = [emb for batch in batch_results for emb in batch]

    clusters = []
    cluster_matrix = None  # numpy matrix of cluster vectors, built incrementally

    for idx, text in enumerate(texts):
        vec = embeddings[idx]
        row = raw_questions[idx]
        new_source = {"url": row['url'], "company": row['company'], "round": row['round']}

        best_cluster = None
        best_score = 0.0

        if cluster_matrix is not None and len(clusters) > 0:
            query = np.asarray(vec)
            scores = cosine_similarity_batch(query, cluster_matrix)
            best_idx = int(np.argmax(scores))
            best_score = float(scores[best_idx])
            if best_score >= SIMILARITY_THRESHOLD:
                best_cluster = clusters[best_idx]

        if best_cluster:
            best_cluster['frequency'] += 1
            if row['cat1']:
                best_cluster['cat1'].add(normalize_category(row['cat1']))
            if row['tags']:
                for t in str(row['tags']).split(','):
                    if t.strip():
                        best_cluster['tags'].add(t.strip())
            if row['diff_tag']:
                best_cluster['diffs'].append(row['diff_tag'])
            if len(text) > len(best_cluster['question']):
                best_cluster['question'] = text
                best_cluster['vector'] = vec
                # Update cluster_matrix row
                cluster_matrix[clusters.index(best_cluster)] = np.asarray(vec)
            if new_source not in best_cluster['sources']:
                best_cluster['sources'].append(new_source)
        else:
            clusters.append({
                'question': text, 'cat1': {normalize_category(row['cat1'])} if row['cat1'] else set(),
                'tags': {t.strip() for t in str(row['tags']).split(',') if t.strip()},
                'diffs': [row['diff_tag']] if row['diff_tag'] else [],
                'frequency': 1, 'vector': vec,
                'sources': [new_source]
            })
            new_row = np.asarray(vec).reshape(1, -1)
            cluster_matrix = new_row if cluster_matrix is None else np.vstack([cluster_matrix, new_row])

    # 预构建旧答案向量矩阵，用于批量语义匹配恢复
    old_answer_items = [(q, info) for q, info in existing_answers_map.items() if info['vector']]
    old_answer_matrix = np.array([info['vector'] for _, info in old_answer_items]) if old_answer_items else None

    def _save():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM master_question_bank")
            restored_count = 0
            for c in clusters:
                diff_str = Counter(c['diffs']).most_common(1)[0][0] if c['diffs'] else "未知"
                ai_answer = None
                if c['question'] in existing_answers_map:
                    ai_answer = existing_answers_map[c['question']]['ai_answer']
                elif old_answer_matrix is not None and c['vector']:
                    query = np.asarray(c['vector'])
                    scores = cosine_similarity_batch(query, old_answer_matrix)
                    best_idx = int(np.argmax(scores))
                    best_sim = float(scores[best_idx])
                    if best_sim >= 0.95:
                        ai_answer = old_answer_items[best_idx][1]['ai_answer']
                        restored_count += 1
                        logger.info(f"通过向量匹配恢复答案 (sim={best_sim:.4f}): {c['question'][:40]}...")

                conn.execute(
                    "INSERT INTO master_question_bank (question, cat1, tags, difficulty, frequency, vector, sources, ai_answer) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (c['question'], ",".join(c['cat1']), ",".join(c['tags']), diff_str, c['frequency'], json.dumps(c['vector']), json.dumps(c['sources']), ai_answer)
                )
            conn.commit()
            logger.info(f"答案恢复统计: 精确匹配 {len(clusters) - restored_count} 条, 向量匹配恢复 {restored_count} 条")

    await run_db(_save)
    logger.info(f"全量重建完成: {len(clusters)} 道核心真题")
    return {"status": "success", "total_unique": len(clusters)}


@router.post("/api/master-bank/toggle-star/{question_id}")
async def toggle_star(question_id: int):
    """切换题目收藏状态"""
    def _toggle():
        with get_db_connection() as conn:
            row = conn.execute("SELECT is_starred FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目")
            new_val = 0 if row['is_starred'] else 1
            conn.execute("UPDATE master_question_bank SET is_starred = ? WHERE id = ?", (new_val, question_id))
            conn.commit()
            return new_val

    try:
        new_val = await run_db(_toggle)
        return {"status": "success", "is_starred": bool(new_val)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/master-bank/generate-answer/{question_id}")
async def generate_master_answer(question_id: int):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, ai_answer FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()

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
                conn.execute("UPDATE master_question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                conn.commit()

        await run_db(_update)
        return {"status": "success", "answer": answer}
    except Exception as e:
        logger.error(f"手动生成答案失败（已重试3次）[ID:{question_id}]: {e}")
        raise HTTPException(status_code=500, detail="生成答案失败，请稍后重试")


@router.delete("/api/master-bank/{question_id}")
async def delete_master_question(question_id: int):
    def _delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT id, question, sources FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目，可能已被删除")

            # 联动清理 questions_detail 中对应的记录
            question_text = row['question']
            if question_text:
                cursor.execute("DELETE FROM questions_detail WHERE question = ?", (question_text,))

            cursor.execute("DELETE FROM master_question_bank WHERE id = ?", (question_id,))
            conn.commit()

    try:
        await run_db(_delete)
        return {"status": "success", "message": "题目删除成功（已联动清理 questions_detail）"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.post("/api/master-bank/re-tag/{question_id}")
async def retag_master_question(question_id: int):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, cat1, cat2, tags, difficulty FROM master_question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)

    if not row or not row['question']:
        raise HTTPException(status_code=404, detail="未找到该题目")

    question_text = row['question']
    current_cat1 = row['cat1'] or '未分类'
    current_cat2 = row['cat2'] or '未分类'
    current_tags = row['tags'] or ''
    current_diff = row['difficulty'] or '未知'

    # 在 prompt 中告知当前分类，要求 LLM 重新审视并给出更准确的分类
    input_data = [{"id": question_id, "题目": question_text}]
    q_json = json.dumps(input_data, ensure_ascii=False)
    user_msg = TAGGING_PROMPT.replace("{questions}", q_json)
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
            response_format={"type": "json_object"}
        )

        parsed_result = json.loads(response.choices[0].message.content.strip())
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
                    "UPDATE master_question_bank SET cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
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

    except Exception as e:
        logger.exception("重新打标失败")
        raise HTTPException(status_code=500, detail=f"重新打标失败: {str(e)}")


@router.get("/api/master-bank/random")
async def get_random_questions(
    count: int = Query(5, ge=1, le=20),
    cat1: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None)
):
    """随机抽题接口，支持按分类和难度筛选"""
    def _query():
        with get_db_connection() as conn:
            conditions = []
            params = []
            if cat1:
                conditions.append("cat1 LIKE ?")
                params.append(f"%{cat1}%")
            if difficulty:
                conditions.append("difficulty LIKE ?")
                params.append(f"%{difficulty}%")

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            rows = conn.execute(
                f"SELECT id, question, cat1, cat2, tags, difficulty, frequency, ai_answer, sources FROM master_question_bank {where_clause} ORDER BY RANDOM() LIMIT ?",
                params + [count]
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['sources'] = json.loads(d['sources']) if d['sources'] else []
        except Exception:
            d['sources'] = []
        result.append(d)
    return result

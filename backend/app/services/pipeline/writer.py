"""
数据库写入：将聚类结果写入 question_bank 及关联表
"""
import json
import logging
from typing import List, Dict

from app.db.connection import get_db_connection, run_db
from app.db.question_bank_sources import insert_source, insert_original_item

logger = logging.getLogger("interview-boss")


async def _run_db(func):
    """Resolve run_db at call time so the test database stays in this thread."""
    import app.db.connection as db_module

    return await db_module.run_db(func)


async def tag_and_write_details(
    url: str, company: str, round_: str, questions_list: str,
    job_position: str = "", user_id: int = None, *, interview_id: int | None = None
) -> List[List[str]]:
    """阶段1：调用 LLM 打标签并写入 questions_detail"""
    import re as _re
    raw_lines = [q.strip() for q in questions_list.split("\n") if q.strip()]
    questions = []
    for line in raw_lines:
        cleaned = _re.sub(r'^[\d]+[.、)\]\s]+', '', line).strip()
        if cleaned:
            questions.append(cleaned)
    if not questions:
        return []

    from app.services.submit_service import tag_questions_batch
    tagged_rows = await tag_questions_batch(url, company, round_, questions, user_id=user_id)

    def _write_details():
        conn = get_db_connection()
        conn.execute("BEGIN")
        try:
            from app.db.operations import _replace_details_txn
            resolved_interview_id = interview_id
            if resolved_interview_id is None:
                matches = conn.execute(
                    "SELECT id FROM interview WHERE url = ? AND deleted_at IS NULL",
                    (url,),
                ).fetchall()
                if len(matches) == 1:
                    resolved_interview_id = matches[0]["id"]
            if resolved_interview_id is None:
                # Compatibility-only utility use.  An unlinked detail cannot enter
                # distribution statistics, so it cannot contaminate their default.
                conn.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
                from app.db.operations import _insert_details_txn
                _insert_details_txn(conn.cursor(), tagged_rows, job_position)
            else:
                _replace_details_txn(cursor=conn.cursor(), interview_id=resolved_interview_id, url=url,
                                 tagged_rows=tagged_rows, job_position=job_position)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    await _run_db(_write_details)
    return tagged_rows


def apply_matched(conn, matched, job_position, saved_answers):
    """将匹配到已有聚类的题追加到对应聚类"""
    for item in matched:
        cluster_id = item['cluster_id']
        existing = conn.execute(
            "SELECT id, frequency, sources, original_questions, original_question_sources, ai_answer "
            "FROM question_bank WHERE id = ?",
            (cluster_id,)
        ).fetchone()
        if not existing:
            continue

        try:
            sources = json.loads(existing['sources']) if existing['sources'] else []
        except Exception:
            sources = []
        try:
            oqs = json.loads(existing['original_questions']) if existing['original_questions'] else []
        except Exception:
            oqs = []
        try:
            oqs_src = json.loads(existing['original_question_sources']) if existing['original_question_sources'] else []
        except Exception:
            oqs_src = []

        url = item.get('url', '')
        existing_urls = {s.get('url') for s in sources}
        url_is_new = bool(url and url not in existing_urls)
        if url_is_new:
            sources.append({"url": url, "company": item.get('company', ''), "round": item.get('round', '')})

        q = item.get('question', '')
        q_is_new = bool(q and q not in oqs)
        if q_is_new:
            oqs.append(q)
            oqs_src.append({
                "question": q,
                "sources": [{"url": url, "company": item.get('company', ''), "round": item.get('round', '')}]
            })
        elif q and url_is_new:
            # 原题文本已存在但来源 URL 是新的 → 追加来源到已有原题的 sources 映射
            for oqs_entry in oqs_src:
                if oqs_entry.get('question') == q:
                    oqs_entry.setdefault('sources', []).append({
                        "url": url, "company": item.get('company', ''), "round": item.get('round', '')
                    })
                    break

        ai_answer = existing['ai_answer']
        if not ai_answer:
            ai_answer = saved_answers.get(q)

        conn.execute(
            "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, "
            "original_question_sources = ?, ai_answer = COALESCE(?, ai_answer), "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (len(oqs), json.dumps(sources, ensure_ascii=False),
             json.dumps(oqs, ensure_ascii=False),
             json.dumps(oqs_src, ensure_ascii=False),
             ai_answer, cluster_id)
        )

        if url_is_new:
            try:
                insert_source(conn, cluster_id, url, item.get('company', ''), item.get('round', ''))
            except Exception:
                pass
        if q_is_new:
            try:
                insert_original_item(conn, cluster_id, q, [{"url": url, "company": item.get('company', ''), "round": item.get('round', '')}])
            except Exception:
                pass


def insert_new_clusters(conn, new_clusters, job_position, saved_answers):
    """插入新聚类到 question_bank"""
    new_qb_ids = []
    pos_rows_cache = conn.execute("SELECT id FROM job_positions WHERE name = ?",
                                  (job_position,)).fetchall()
    for cluster in new_clusters:
        entry = _build_new_entry(cluster, job_position)
        cursor = conn.execute(
            "INSERT INTO question_bank "
            "(question, cat1, cat2, tags, difficulty, frequency, sources, "
            "original_questions, original_question_sources, owner_id, job_position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (entry['question'], entry['cat1'], entry['cat2'], entry['tags'],
             entry['difficulty'], entry['frequency'],
             json.dumps(entry['sources'], ensure_ascii=False),
             json.dumps(entry['original_questions'], ensure_ascii=False),
             json.dumps(entry['original_question_sources'], ensure_ascii=False),
             job_position)
        )
        new_id = cursor.lastrowid
        # 设置 cluster_id = 自身 id（新建聚类自己就是代表）
        conn.execute("UPDATE question_bank SET cluster_id = ? WHERE id = ?", (new_id, new_id))
        # 写入 embedding（供后续 prefilter_centroids 使用）
        try:
            from app.services.embedding_service import encode_texts
            import numpy as np
            emb = encode_texts([entry['question']])
            if emb.shape[0] > 0:
                conn.execute("UPDATE question_bank SET embedding = ? WHERE id = ?", (emb[0].tobytes(), new_id))
        except Exception as e:
            logger.warning(f"[写入] embedding 编码失败 (id={new_id}): {e}")
        new_qb_ids.append(new_id)

        for s in entry['sources']:
            try:
                insert_source(conn, new_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
            except Exception:
                pass
        for oqs in entry['original_question_sources']:
            try:
                insert_original_item(conn, new_id, oqs.get('question', ''), oqs.get('sources', []))
            except Exception:
                pass

        for pr in pos_rows_cache:
            conn.execute(
                "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                (new_id, pr['id'])
            )

        ai_answer = None
        for oq in entry['original_questions']:
            if oq in saved_answers:
                ai_answer = saved_answers[oq]
                break
        if ai_answer:
            conn.execute("UPDATE question_bank SET ai_answer = ? WHERE id = ?", (ai_answer, new_id))

    return new_qb_ids


def _build_new_entry(cluster, job_position):
    """为新聚类构建 question_bank 写入数据"""
    items = cluster.get("items", [])

    cat1 = items[0].get('cat1', '') if items else ''
    cat2 = items[0].get('cat2', '') if items else ''

    all_tags = set()
    for item in items:
        for t in (item.get('tags') or '').split(','):
            t = t.strip()
            if t:
                all_tags.add(t)

    diffs = [item.get('diff_tag', '') for item in items if item.get('diff_tag')]
    difficulty = max(set(diffs), key=diffs.count) if diffs else 'L2-中等'

    sources = []
    original_questions = []
    original_question_sources = []
    seen_urls = set()

    for item in items:
        url = item.get('url', '')
        if url and url not in seen_urls:
            sources.append({"url": url, "company": item.get('company', ''), "round": item.get('round', '')})
            seen_urls.add(url)
        q = item.get('question', '')
        if q and q not in original_questions:
            original_questions.append(q)
            original_question_sources.append({
                "question": q,
                "sources": [{"url": url, "company": item.get('company', ''), "round": item.get('round', '')}]
            })

    return {
        'question': cluster['representative'],
        'cat1': cat1,
        'cat2': cat2,
        'tags': ', '.join(sorted(all_tags)),
        'difficulty': difficulty,
        'frequency': len(original_questions),
        'sources': sources,
        'original_questions': original_questions,
        'original_question_sources': original_question_sources,
    }

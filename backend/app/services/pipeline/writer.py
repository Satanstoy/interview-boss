"""
数据库写入：将聚类结果写入 question_bank 及关联表
"""
import json
import logging
from typing import List, Dict

from app.db.connection import get_db_connection, run_db
from app.services.question_bank_integrity import (
    canonicalize_question_bank_payload,
    claim_public_original_questions,
    sync_question_bank_projections,
)
from app.services.question_variant_reconciliation import normalize_original_question

logger = logging.getLogger("interview-boss")


def _mark_review_pending_if_available(conn, cluster_id: int, reason: str) -> None:
    """Keep the writer usable on legacy/lightweight schemas."""

    required = {"quality_issue", "cluster_review_state", "cluster_review_tasks"}
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not required.issubset(tables):
        return
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    mark_cluster_review_pending(conn, cluster_id, reason)


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
            "SELECT id, owner_id, frequency, sources, original_questions, original_question_sources, ai_answer, answer_sources "
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
        source = {
            "url": url,
            "company": item.get('company', ''),
            "round": item.get('round', ''),
        }
        old_urls = {
            source.get("url")
            for source in sources
            if isinstance(source, dict) and source.get("url")
        }
        old_questions = {
            normalize_original_question(question) for question in oqs
        }
        sources.append(source)

        q = item.get('question', '')
        if q:
            # Add the raw occurrence first.  Canonicalization below merges only
            # exact normalized variants and unions their source URLs.
            oqs.append(q)
            oqs_src.append({"question": q, "sources": [source]})

        sources, oqs, oqs_src = canonicalize_question_bank_payload(
            sources, oqs, oqs_src
        )
        url_is_new = bool(url and url not in old_urls)
        q_is_new = bool(
            q and normalize_original_question(q) not in old_questions
        )
        claim_public_original_questions(
            conn, cluster_id, existing["owner_id"], "approved", oqs
        )

        ai_answer = existing['ai_answer']
        answer_sources = existing['answer_sources']
        if not ai_answer:
            saved = saved_answers.get(q)
            if saved:
                ai_answer = saved['answer']
                answer_sources = saved.get('sources')

        conn.execute(
            "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, "
            "original_question_sources = ?, ai_answer = COALESCE(?, ai_answer), "
            "answer_sources = COALESCE(?, answer_sources), "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (len(oqs), json.dumps(sources, ensure_ascii=False),
             json.dumps(oqs, ensure_ascii=False),
             json.dumps(oqs_src, ensure_ascii=False),
             ai_answer, answer_sources, cluster_id)
        )

        sync_question_bank_projections(
            conn.cursor(), cluster_id, sources, oqs, oqs_src
        )

        if existing["owner_id"] is None:
            _mark_review_pending_if_available(conn, cluster_id, "new_variant_matched")


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

        claim_public_original_questions(
            conn, new_id, entry.get("owner_id"), "approved", entry["original_questions"]
        )
        sync_question_bank_projections(
            conn.cursor(),
            new_id,
            entry["sources"],
            entry["original_questions"],
            entry["original_question_sources"],
        )

        for pr in pos_rows_cache:
            conn.execute(
                "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                (new_id, pr['id'])
            )

        ai_answer = None
        answer_sources = None
        for oq in entry['original_questions']:
            saved = saved_answers.get(oq)
            if saved:
                ai_answer = saved['answer']
                answer_sources = saved.get('sources')
                break
        if ai_answer:
            conn.execute(
                "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                (ai_answer, answer_sources, new_id),
            )

        # The new cluster and its durable review outbox row are committed by
        # the caller's single atomic cluster-batch transaction.
        if entry.get("owner_id") is None:
            _mark_review_pending_if_available(conn, new_id, "new_cluster")

    return new_qb_ids


def _dedupe_variants(variants: list[str]) -> list[str]:
    """变体归一化（根因 #2）：规范化相等 + 子串包含去重，保留较长者。

    重复变体（同题多表述，21.5%）会虚高 frequency 并污染 oq；
    文本规则是零成本第一层，语义级重复由维护工具（LLM 判重）补充。
    """
    from app.services.clustering.clusterer import _normalize_question_text

    norm_list = []
    for v in variants:
        n = _normalize_question_text(v)
        if n:
            norm_list.append((v, n))
    kept = []
    for v, n in norm_list:
        dup = False
        for i, (kv, kn) in enumerate(kept):
            if n == kn:
                dup = True
                break
            longer, shorter = (n, kn) if len(n) >= len(kn) else (kn, n)
            if len(shorter) >= 4 and shorter in longer:
                dup = True
                if len(n) > len(kn):
                    kept[i] = (v, n)
                break
        if not dup:
            kept.append((v, n))
    return [v for v, _ in kept]


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

    for item in items:
        url = item.get('url', '')
        if url:
            sources.append({"url": url, "company": item.get('company', ''), "round": item.get('round', '')})
        q = item.get('question', '')
        if q:
            original_questions.append(q)
            original_question_sources.append({
                "question": q,
                "sources": [{"url": url, "company": item.get('company', ''), "round": item.get('round', '')}]
            })

    sources, original_questions, original_question_sources = (
        canonicalize_question_bank_payload(
            sources, original_questions, original_question_sources
        )
    )

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

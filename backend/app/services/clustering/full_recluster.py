"""全量聚类：full_recluster_hybrid"""
import logging
from typing import Dict, Any

from app.db.connection import get_db_connection
from app.services.clustering.clusterer import cluster_three_stage_v2, _V2_SIMILARITY_THRESHOLD

logger = logging.getLogger("interview-boss")


async def _scan_async(func):
    """将同步 DB 操作包装为异步。"""
    import asyncio
    return await asyncio.to_thread(func)


async def full_recluster_hybrid(
    user_id=None,
    similarity_threshold: float = _V2_SIMILARITY_THRESHOLD,
) -> Dict[str, Any]:
    """全量聚类：V2 三阶段聚类（按 cat2 分组 + LLM 语义分组）。

    Args:
        user_id: 用户 ID
        similarity_threshold: Embedding 余弦相似度阈值

    Returns:
        {"total": int, "merged": int, "remaining": int}
    """
    def _load_all():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question, cat1, cat2, tags, frequency "
            "FROM question_bank "
            "WHERE deleted_at IS NULL AND status = 'approved' AND duplicate_of IS NULL "
            "ORDER BY frequency DESC, id"
        ).fetchall()
        return [dict(r) for r in rows]

    questions = await _scan_async(_load_all)
    if not questions:
        return {"total": 0, "merged": 0, "remaining": 0}

    logger.info(f"全量聚类开始: {len(questions)} 题")

    result = await cluster_three_stage_v2(
        questions, user_id=user_id, similarity_threshold=similarity_threshold
    )

    # 构建 lookup 避免 O(N*M) 线性扫描
    question_lookup = {q['id']: q['question'] for q in questions}

    # 执行合并
    for survivor_id, merged_id, confidence in result['merged']:
        def _do_merge(s=survivor_id, m=merged_id, c=confidence):
            conn = get_db_connection()
            conn.execute("BEGIN")
            try:
                entry = conn.execute(
                    "SELECT id, question, cat1, cat2, tags, difficulty, frequency, "
                    "sources, original_questions, original_question_sources, ai_answer "
                    "FROM question_bank WHERE id = ?",
                    (m,),
                ).fetchone()
                if not entry:
                    conn.execute("ROLLBACK")
                    return
                from app.services.pipeline.compact import _do_merge_to_existing

                entry_dict = dict(entry)
                entry_dict.setdefault("question", question_lookup.get(m, ""))
                _do_merge_to_existing(
                    s,
                    entry_dict,
                    operation_type='three_stage',
                    phase='full_recluster',
                    cat2=entry_dict.get('cat2') or '',
                    operator_id=user_id,
                    confidence=c,
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise

        await _scan_async(_do_merge)

    total = len(questions)
    merged = len(result['merged'])
    remaining = len(result['unmatched'])

    logger.info(f"全量聚类完成: 总数={total}, 合并={merged}, 剩余={remaining}")
    return {"total": total, "merged": merged, "remaining": remaining}

"""
批处理逻辑:增量聚类,完整流水线

孤岛碎片整理(compact)已拆分至 compact.py。
"""
import json
import asyncio
import logging
import numpy as np
from typing import List, Dict

from app.db.connection import get_db_connection
from app.services.clustering import process_incremental_batch
from .sanitize import BATCH_SIZE, sanitize_batch
from .queue import dequeue_batch, mark_batch_done, mark_batch_failed, should_trigger_clustering
from .writer import apply_matched, insert_new_clusters, tag_and_write_details

logger = logging.getLogger("interview-boss")

_EXISTING_CLUSTERS_PAGE_SIZE = 100


async def _run_db(func):
    """Use the current db.connection.run_db so tests can patch thread behavior."""
    import app.db.connection as db_module
    return await db_module.run_db(func)


def _safe_json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _append_unique_text(items: List[str], text: str) -> bool:
    text = (text or "").strip()
    if not text or text in items:
        return False
    items.append(text)
    return True


def _ensure_original_source_entry(original_sources: List[Dict], question: str, sources: List[Dict]):
    question = (question or "").strip()
    if not question:
        return
    for item in original_sources:
        if item.get("question") != question:
            continue
        existing = {
            (s.get("url", ""), s.get("company", ""), s.get("round", ""))
            for s in item.get("sources", [])
            if isinstance(s, dict)
        }
        for src in sources:
            if not isinstance(src, dict):
                continue
            key = (src.get("url", ""), src.get("company", ""), src.get("round", ""))
            if key not in existing:
                item.setdefault("sources", []).append(src)
                existing.add(key)
        return
    original_sources.append({"question": question, "sources": list(sources or [])})


def _canonicalize_originals(question: str, sources: List[Dict],
                            originals: List[str], original_sources: List[Dict]) -> tuple[List[str], List[Dict]]:
    result = []
    for oq in originals:
        _append_unique_text(result, oq)
    if not result:
        _append_unique_text(result, question)

    canonical_sources = []
    for item in original_sources:
        if not isinstance(item, dict):
            continue
        q = (item.get("question") or "").strip()
        if not q:
            continue
        _append_unique_text(result, q)
        srcs = item.get("sources", [])
        canonical_sources.append({
            "question": q,
            "sources": srcs if isinstance(srcs, list) else [],
        })

    for oq in result:
        _ensure_original_source_entry(
            canonical_sources,
            oq,
            sources if oq == (question or "").strip() else []
        )
    return result, canonical_sources


# ============================================================
# 阶段2:流式增量聚类
# ============================================================

async def _load_existing_clusters_by_cat2(job_position: str) -> Dict[str, List[Dict]]:
    """分页加载已有聚类(只取 ID + 代表题 + embedding,节省内存)"""
    import numpy as np

    existing_by_cat2 = {}
    offset = 0
    while True:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question, cat2, embedding "
            "FROM question_bank "
            "WHERE status = 'approved' AND deleted_at IS NULL AND duplicate_of IS NULL AND job_position = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (job_position, _EXISTING_CLUSTERS_PAGE_SIZE, offset)
        ).fetchall()
        if not rows:
            break
        for r in rows:
            cat2 = r['cat2'] or ''
            entry = {
                "id": r['id'],
                "question": r['question'],
            }
            # 反序列化 embedding BLOB
            emb_blob = r['embedding'] if len(r) > 3 else None
            if emb_blob:
                entry["embedding"] = np.frombuffer(emb_blob, dtype=np.float32).copy()
            existing_by_cat2.setdefault(cat2, []).append(entry)
        offset += len(rows)
        del rows
        await asyncio.sleep(0)
    return existing_by_cat2


async def cluster_batch(batch: List[Dict], user_id: int = None, skip_clean: bool = False) -> int:
    """对一批问题做增量聚类:匹配已有聚类 → 内部聚类剩余 → 原子写入 question_bank

    batch: dequeue_batch() 返回的问题列表
    skip_clean: 是否跳过 URL 清理(全量重建时跳过)
    返回:新创建的 question_bank 记录数
    """
    if not batch:
        return 0

    batch, filtered = sanitize_batch(batch)
    if filtered:
        mark_batch_done([item['queue_id'] for item in filtered])
        logger.info(f"清洗拦截 {len(filtered)} 条脏数据")
    if not batch:
        return 0

    job_position = batch[0].get('job_position', '') or ''
    batch_urls = list({item['url'] for item in batch if item.get('url')})

    # ── Step 0: 保存旧 AI 答案 + 清理旧贡献 ──
    conn = get_db_connection()
    saved_answers = {}
    for url in batch_urls:
        rows = conn.execute(
            "SELECT question, original_questions, ai_answer FROM question_bank "
            "WHERE sources LIKE ? AND ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
            (f"%{url}%", job_position)
        ).fetchall()
        for r in rows:
            if r['ai_answer']:
                saved_answers[r['question']] = r['ai_answer']
                try:
                    for oq in json.loads(r['original_questions'] or '[]'):
                        if oq and oq not in saved_answers:
                            saved_answers[oq] = r['ai_answer']
                except Exception:
                    pass
        del rows

    if not skip_clean:
        def _pre_clean():
            c = get_db_connection()
            c.execute("BEGIN")
            try:
                for url in batch_urls:
                    from app.db.operations import _cleanup_old_sources_txn_v2
                    _cleanup_old_sources_txn_v2(c.cursor(), url, job_position)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        await _run_db(_pre_clean)

    # ── Step 1: 加载已有聚类 ──
    existing_by_cat2 = await _load_existing_clusters_by_cat2(job_position)

    # ── Step 2: 调用增量聚类引擎 ──
    new_rows = [
        {"id": item['qd_id'], "question": item['question'],
         "cat1": item.get('cat1', ''), "cat2": item.get('cat2', ''),
         "tags": item.get('tags', ''), "diff_tag": item.get('diff_tag', ''),
         "url": item.get('url', ''), "company": item.get('company', ''),
         "round": item.get('round', '')}
        for item in batch
    ]

    result = await process_incremental_batch(new_rows, existing_by_cat2, user_id=user_id)
    del new_rows

    matched = result["matched_to_existing"]
    new_clusters = result["new_clusters"]
    del result

    # ── Step 3: 原子写入 ──
    def _atomic_write():
        conn = get_db_connection()
        conn.execute("BEGIN")
        new_qb_ids = []
        try:
            apply_matched(conn, matched, job_position, saved_answers)
            new_qb_ids = insert_new_clusters(conn, new_clusters, job_position, saved_answers)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return new_qb_ids

    qb_ids = await _run_db(_atomic_write)

    del matched, new_clusters, saved_answers, existing_by_cat2
    return len(qb_ids)


# ============================================================
# 完整流水线
# ============================================================

async def process_interview_tag_then_maybe_cluster(
    interview_id: int, url: str, company: str, round_: str,
    questions_list: str, job_position: str = "",
    user_id: int = None, batch_size: int = BATCH_SIZE
) -> Dict:
    from .queue import enqueue_questions as _enqueue
    tagged_rows = await tag_and_write_details(
        url, company, round_, questions_list,
        job_position=job_position, user_id=user_id
    )
    _enqueue(interview_id)

    result = {"tagged_count": len(tagged_rows), "clustered": False, "new_qb_count": 0}
    if should_trigger_clustering(batch_size):
        try:
            from app.worker import enqueue_cluster_task
            job = await enqueue_cluster_task(interview_id, user_id)
            logger.info(f"聚类任务已通过 ARQ 调度: job_id={job.job_id}")
            return result
        except Exception as e:
            logger.warning(f"ARQ 调度失败,回退到内联聚类: {e}")
            batch = dequeue_batch(batch_size)
            if batch:
                try:
                    new_count = await cluster_batch(batch, user_id=user_id)
                    queue_ids = [item['queue_id'] for item in batch]
                    mark_batch_done(queue_ids)
                    result["clustered"] = True
                    result["new_qb_count"] = new_count
                except Exception as e:
                    logger.error(f"聚类失败,回退队列状态: {e}")
                    queue_ids = [item['queue_id'] for item in batch]
                    mark_batch_failed(queue_ids)
                    raise
    return result


async def force_cluster_all_pending(user_id: int = None) -> Dict:
    """强制处理所有 pending 队列(用于手动触发重建)"""
    try:
        from app.worker import enqueue_force_cluster_task
        job = await enqueue_force_cluster_task(user_id)
        logger.info(f"全量重建任务已通过 ARQ 调度: job_id={job.job_id}")
        return {"status": "queued", "job_id": job.job_id}
    except Exception as e:
        logger.warning(f"ARQ 调度失败,回退到内联执行: {e}")

    total_new = 0
    total_batches = 0

    while True:
        batch = dequeue_batch(BATCH_SIZE)
        if not batch:
            break
        total_batches += 1
        try:
            new_count = await cluster_batch(batch, user_id=user_id, skip_clean=True)
            queue_ids = [item['queue_id'] for item in batch]
            mark_batch_done(queue_ids)
            total_new += new_count
        except Exception as e:
            logger.error(f"聚类批次 {total_batches} 失败: {e}")
            queue_ids = [item['queue_id'] for item in batch]
            mark_batch_failed(queue_ids)
            raise

        await asyncio.sleep(0.5)

    return {"batches": total_batches, "new_qb_count": total_new}

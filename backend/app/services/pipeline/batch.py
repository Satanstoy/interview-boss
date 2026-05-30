"""
批处理逻辑：增量聚类、完整流水线、孤岛碎片整理
"""
import json
import asyncio
import logging
from typing import List, Dict

from app.db.connection import get_db_connection, run_db
from app.db.question_bank_sources import delete_all_for_qb, insert_source, insert_original_item
from app.services.clustering import process_incremental_batch, _cluster_unmatched
from .sanitize import BATCH_SIZE, sanitize_batch
from .queue import dequeue_batch, mark_batch_done, mark_batch_failed, should_trigger_clustering
from .writer import apply_matched, insert_new_clusters, tag_and_write_details

logger = logging.getLogger("interview-boss")

_EXISTING_CLUSTERS_PAGE_SIZE = 100


# ============================================================
# 阶段2：流式增量聚类
# ============================================================

async def _load_existing_clusters_by_cat2(job_position: str) -> Dict[str, List[Dict]]:
    """分页加载已有聚类（只取 ID + 代表题，节省内存）"""
    existing_by_cat2 = {}
    offset = 0
    while True:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question, cat2 "
            "FROM question_bank "
            "WHERE status = 'approved' AND deleted_at IS NULL AND job_position = ? "
            "ORDER BY id LIMIT ? OFFSET ?",
            (job_position, _EXISTING_CLUSTERS_PAGE_SIZE, offset)
        ).fetchall()
        if not rows:
            break
        for r in rows:
            cat2 = r['cat2'] or ''
            existing_by_cat2.setdefault(cat2, []).append({
                "id": r['id'],
                "question": r['question'],
            })
        offset += len(rows)
        del rows
        await asyncio.sleep(0)
    return existing_by_cat2


async def cluster_batch(batch: List[Dict], user_id: int = None, skip_clean: bool = False) -> int:
    """对一批问题做增量聚类：匹配已有聚类 → 内部聚类剩余 → 原子写入 question_bank

    batch: dequeue_batch() 返回的问题列表
    skip_clean: 是否跳过 URL 清理（全量重建时跳过）
    返回：新创建的 question_bank 记录数
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
        await run_db(_pre_clean)

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

    qb_ids = await run_db(_atomic_write)

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
            logger.warning(f"ARQ 调度失败，回退到内联聚类: {e}")
            batch = dequeue_batch(batch_size)
            if batch:
                try:
                    new_count = await cluster_batch(batch, user_id=user_id)
                    queue_ids = [item['queue_id'] for item in batch]
                    mark_batch_done(queue_ids)
                    result["clustered"] = True
                    result["new_qb_count"] = new_count
                except Exception as e:
                    logger.error(f"聚类失败，回退队列状态: {e}")
                    queue_ids = [item['queue_id'] for item in batch]
                    mark_batch_failed(queue_ids)
                    raise
    return result


async def force_cluster_all_pending(user_id: int = None) -> Dict:
    """强制处理所有 pending 队列（用于手动触发重建）"""
    try:
        from app.worker import enqueue_force_cluster_task
        job = await enqueue_force_cluster_task(user_id)
        logger.info(f"全量重建任务已通过 ARQ 调度: job_id={job.job_id}")
        return {"status": "queued", "job_id": job.job_id}
    except Exception as e:
        logger.warning(f"ARQ 调度失败，回退到内联执行: {e}")

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


# ============================================================
# 孤岛碎片整理（Compaction）
# ============================================================

async def compact_singletons_in_db(user_id: int = None) -> Dict:
    """孤岛碎片整理：对 frequency=1 的独立题按 cat2 做二次合并"""
    _SINGLETONS_PAGE_SIZE = 200

    singletons = []
    offset = 0
    while True:
        def _load_page(_offset=offset):
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, sources, "
                "original_questions, original_question_sources, ai_answer "
                "FROM question_bank "
                "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
                "AND frequency = 1 "
                "ORDER BY id LIMIT ? OFFSET ?",
                (_SINGLETONS_PAGE_SIZE, _offset)
            ).fetchall()
            return [dict(r) for r in rows]

        page = await run_db(_load_page)
        if not page:
            break
        singletons.extend(page)
        offset += len(page)
        del page
        await asyncio.sleep(0)
    if not singletons:
        return {"total_singletons": 0, "merged": 0, "remaining": 0}

    cat2_groups: Dict[str, List[Dict]] = {}
    for r in singletons:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    total_merged = 0

    for cat2, group in cat2_groups.items():
        if len(group) < 2:
            continue

        items_for_cluster = [
            {"id": r['id'], "question": r['question']}
            for r in group
        ]

        try:
            clusters = await _cluster_unmatched(items_for_cluster, user_id)
        except Exception as e:
            logger.warning(f"[Compaction] cat2={cat2} 聚类失败: {e}")
            continue

        for cluster in clusters:
            ids = cluster.get("ids", [])
            if len(ids) < 2:
                continue

            qb_entries = []
            for sid in ids:
                entry = next((r for r in group if str(r['id']) == str(sid)), None)
                if entry:
                    qb_entries.append(entry)
            if len(qb_entries) < 2:
                continue

            qb_entries.sort(key=lambda x: (-x.get('frequency', 1), x['id']))
            survivor = qb_entries[0]
            to_merge = qb_entries[1:]

            def _do_merge(s=survivor, m=to_merge):
                conn = get_db_connection()
                conn.execute("BEGIN")
                try:
                    existing = conn.execute(
                        "SELECT sources, original_questions, original_question_sources, ai_answer "
                        "FROM question_bank WHERE id = ?", (s['id'],)
                    ).fetchone()
                    try:
                        s_src = json.loads(existing['sources']) if existing['sources'] else []
                    except Exception:
                        s_src = []
                    try:
                        s_oqs = json.loads(existing['original_questions']) if existing['original_questions'] else []
                    except Exception:
                        s_oqs = []
                    try:
                        s_oqs_src = json.loads(existing['original_question_sources']) if existing['original_question_sources'] else []
                    except Exception:
                        s_oqs_src = []

                    # 保留 ai_answer：如果 survivor 没有，从被合并的题中获取
                    s_ai_answer = existing['ai_answer'] if existing else None
                    if not s_ai_answer:
                        for entry in m:
                            if entry.get('ai_answer'):
                                s_ai_answer = entry['ai_answer']
                                break

                    seen_urls = {x.get('url') for x in s_src}

                    for entry in m:
                        try:
                            o_src = json.loads(entry['sources']) if entry['sources'] else []
                        except Exception:
                            o_src = []
                        for x in o_src:
                            u = x.get('url', '')
                            if u and u not in seen_urls:
                                s_src.append(x)
                                seen_urls.add(u)

                        try:
                            o_oqs = json.loads(entry['original_questions']) if entry['original_questions'] else []
                        except Exception:
                            o_oqs = []
                        for oq in o_oqs:
                            if oq and oq not in s_oqs:
                                s_oqs.append(oq)

                        try:
                            o_oqs_src = json.loads(entry['original_question_sources']) if entry['original_question_sources'] else []
                        except Exception:
                            o_oqs_src = []
                        s_oqs_src.extend(o_oqs_src)

                        conn.execute("DELETE FROM question_bank WHERE id = ?", (entry['id'],))
                        conn.execute("DELETE FROM question_position WHERE question_id = ?", (entry['id'],))

                    conn.execute(
                        "UPDATE question_bank SET frequency = ?, sources = ?, "
                        "original_questions = ?, original_question_sources = ?, "
                        "ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (len(s_oqs), json.dumps(s_src, ensure_ascii=False),
                         json.dumps(s_oqs, ensure_ascii=False),
                         json.dumps(s_oqs_src, ensure_ascii=False),
                         s_ai_answer, s['id'])
                    )

                    try:
                        delete_all_for_qb(conn, s['id'])
                    except Exception:
                        pass
                    for src in s_src:
                        try:
                            insert_source(conn, s['id'], src.get('url', ''), src.get('company', ''), src.get('round', ''))
                        except Exception:
                            pass
                    for oqs_entry in s_oqs_src:
                        try:
                            insert_original_item(conn, s['id'], oqs_entry.get('question', ''), oqs_entry.get('sources', []))
                        except Exception:
                            pass

                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            await run_db(_do_merge)
            total_merged += len(to_merge)

        await asyncio.sleep(0.5)

    return {
        "total_singletons": len(singletons),
        "merged": total_merged,
        "remaining": len(singletons) - total_merged,
    }

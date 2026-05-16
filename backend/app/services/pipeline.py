"""
两阶段流水线服务（流式增量处理）

阶段1（并发）: 面经 → tag → questions_detail + enqueue（每题一条队列记录）
阶段2（串行）: queue达到batch_size 或 全部完成 → 增量匹配 + 内部聚类 → question_bank
"""
import re
import json
import asyncio
import logging
from typing import List, Dict

from app.db.connection import get_db_connection, run_db
from app.services.clustering import process_incremental_batch, _cluster_unmatched

logger = logging.getLogger("interview-boss")

BATCH_SIZE = 40
_EXISTING_CLUSTERS_PAGE_SIZE = 100

_BLACKLIST_PHRASES = ["自我介绍", "反问", "想问我", "职业规划", "加班", "薪资", "为什么离职", "优缺点"]


def _sanitize_batch(batch: List[Dict]) -> tuple[List[Dict], List[Dict]]:
    """清洗批次：剔除纯数字和非面试话术。返回 (clean, filtered)"""
    clean, filtered = [], []
    for item in batch:
        q = (item.get('question') or '').strip()
        if re.match(r'^[\d\s\-.,，。、;；:：!！?？]+$', q):
            filtered.append(item)
            continue
        if any(phrase in q for phrase in _BLACKLIST_PHRASES):
            filtered.append(item)
            continue
        clean.append(item)
    return clean, filtered


# ============================================================
# 队列操作（基本单位：单个问题）
# ============================================================

def enqueue_questions(interview_id: int) -> int:
    """将一条面经的所有 questions_detail 加入分析队列，返回队列记录数"""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id FROM questions_detail WHERE url = (SELECT url FROM interview WHERE id = ?) AND deleted_at IS NULL",
        (interview_id,)
    ).fetchall()
    count = 0
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO analysis_queue (interview_id, question_detail_id, status) VALUES (?, ?, 'pending')",
            (interview_id, r[0])
        )
        count += 1
    conn.commit()
    return count


def get_pending_count() -> int:
    conn = get_db_connection()
    row = conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'").fetchone()
    return row['c']


def get_processing_count() -> int:
    conn = get_db_connection()
    row = conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'processing'").fetchone()
    return row['c']


STUCK_PROCESSING_THRESHOLD_MINUTES = 30


def _recover_stuck_processing():
    conn = get_db_connection()
    conn.execute(
        "UPDATE analysis_queue SET status = 'pending' "
        "WHERE status = 'processing' AND created_at < datetime('now', ?)",
        (f'-{STUCK_PROCESSING_THRESHOLD_MINUTES} minutes',)
    )
    conn.commit()


def should_trigger_clustering(batch_size: int = BATCH_SIZE) -> bool:
    _recover_stuck_processing()
    pending = get_pending_count()
    if pending >= batch_size:
        return True
    processing = get_processing_count()
    return processing == 0 and pending > 0


def dequeue_batch(batch_size: int = BATCH_SIZE) -> List[Dict]:
    """取出一批 pending 任务并标记为 processing"""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT aq.id as queue_id, aq.question_detail_id as qd_id, "
        "qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, "
        "qd.url, qd.company, qd.round, qd.job_position "
        "FROM analysis_queue aq "
        "JOIN questions_detail qd ON aq.question_detail_id = qd.id "
        "WHERE aq.status = 'pending' AND qd.deleted_at IS NULL "
        "ORDER BY aq.id LIMIT ?",
        (batch_size,)
    ).fetchall()

    if not rows:
        return []

    queue_ids = [r['queue_id'] for r in rows]
    placeholders = ','.join('?' * len(queue_ids))
    conn.execute(
        f"UPDATE analysis_queue SET status = 'processing' WHERE id IN ({placeholders})",
        queue_ids
    )
    conn.commit()
    return [dict(r) for r in rows]


def mark_batch_done(queue_ids: List[int]):
    if not queue_ids:
        return
    conn = get_db_connection()
    placeholders = ','.join('?' * len(queue_ids))
    conn.execute(
        f"UPDATE analysis_queue SET status = 'done', processed_at = CURRENT_TIMESTAMP "
        f"WHERE id IN ({placeholders})",
        queue_ids
    )
    conn.commit()


def mark_batch_failed(queue_ids: List[int]):
    if not queue_ids:
        return
    conn = get_db_connection()
    placeholders = ','.join('?' * len(queue_ids))
    conn.execute(
        f"UPDATE analysis_queue SET status = 'pending' WHERE id IN ({placeholders})",
        queue_ids
    )
    conn.commit()


# ============================================================
# 阶段1：打标签
# ============================================================

async def tag_interview(interview_id: int, url: str, company: str,
                        round_: str, questions_list: str,
                        job_position: str = "", user_id: int = None) -> List[List[str]]:
    raw_lines = [q.strip() for q in questions_list.split("\n") if q.strip()]
    questions = []
    for line in raw_lines:
        import re
        cleaned = re.sub(r'^[\d]+[.、)\]\s]+', '', line).strip()
        if cleaned:
            questions.append(cleaned)
    if not questions:
        return []

    from app.routers.submit import tag_questions_batch
    tagged_rows = await tag_questions_batch(url, company, round_, questions, user_id=user_id)

    def _write_details():
        conn = get_db_connection()
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
            for tr in tagged_rows:
                conn.execute(
                    "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*tr, job_position)
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    await run_db(_write_details)
    return tagged_rows


# ============================================================
# 阶段2：流式增量聚类
# ============================================================

async def _load_existing_clusters_by_cat2(job_position: str) -> Dict[str, List[Dict]]:
    """分页加载已有聚类（只取 ID + 代表题，不取全量变体题，节省内存）"""
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
    skip_clean: 是否跳过 URL 清理（全量重建时跳过，因为 QB 已被清空）
    返回：新创建的 question_bank 记录数
    """
    if not batch:
        return 0

    # ── 清洗脏数据 ──
    batch, filtered = _sanitize_batch(batch)
    if filtered:
        mark_batch_done([item['queue_id'] for item in filtered])
        logger.info(f"清洗拦截 {len(filtered)} 条脏数据")
    if not batch:
        return 0

    job_position = batch[0].get('job_position', '') or ''
    batch_urls = list({item['url'] for item in batch if item.get('url')})

    # ── Step 0: 保存旧 AI 答案 + 清理旧贡献（可选） ──
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

    # ── Step 1: 分页加载已有聚类（只取 ID + 代表题） ──
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
            _apply_matched(conn, matched, job_position, saved_answers)
            new_qb_ids = _insert_new_clusters(conn, new_clusters, job_position, saved_answers)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return new_qb_ids

    qb_ids = await run_db(_atomic_write)

    del matched, new_clusters, saved_answers, existing_by_cat2
    return len(qb_ids)


def _apply_matched(conn, matched, job_position, saved_answers):
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
        if url and url not in existing_urls:
            sources.append({"url": url, "company": item.get('company', ''), "round": item.get('round', '')})

        q = item.get('question', '')
        if q and q not in oqs:
            oqs.append(q)
            oqs_src.append({
                "question": q,
                "sources": [{"url": url, "company": item.get('company', ''), "round": item.get('round', '')}]
            })

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


def _insert_new_clusters(conn, new_clusters, job_position, saved_answers):
    """插入新聚类到 question_bank"""
    new_qb_ids = []
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
        new_qb_ids.append(new_id)

        pos_rows = conn.execute("SELECT id FROM job_positions WHERE name = ?",
                                (job_position,)).fetchall()
        for pr in pos_rows:
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
        if q:
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


# ============================================================
# 完整流水线
# ============================================================

async def process_interview_tag_then_maybe_cluster(
    interview_id: int, url: str, company: str, round_: str,
    questions_list: str, job_position: str = "",
    user_id: int = None, batch_size: int = BATCH_SIZE
) -> Dict:
    tagged_rows = await tag_interview(
        interview_id, url, company, round_, questions_list,
        job_position=job_position, user_id=user_id
    )
    enqueue_questions(interview_id)

    result = {"tagged_count": len(tagged_rows), "clustered": False, "new_qb_count": 0}
    if should_trigger_clustering(batch_size):
        # 优先使用 ARQ 异步调度，失败时回退到内联执行
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
    """强制处理所有 pending 队列（用于手动触发重建）

    优先通过 ARQ 异步调度，失败时回退到内联执行。
    注意：全量重建时 skip_clean=True，因为 QB 已在重建入口清空，
    每个批次的 _pre_clean 会误删前序批次新建的 QB 条目。
    """
    # 优先使用 ARQ 异步调度
    try:
        from app.worker import enqueue_force_cluster_task
        job = await enqueue_force_cluster_task(user_id)
        logger.info(f"全量重建任务已通过 ARQ 调度: job_id={job.job_id}")
        return {"status": "queued", "job_id": job.job_id}
    except Exception as e:
        logger.warning(f"ARQ 调度失败，回退到内联执行: {e}")

    # 回退：内联执行
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

        # 批次间让 GC 回收上一批次的内存
        await asyncio.sleep(0.5)

    return {"batches": total_batches, "new_qb_count": total_new}


# ============================================================
# 孤岛碎片整理（Compaction）
# ============================================================

async def compact_singletons_in_db(user_id: int = None) -> Dict:
    """孤岛碎片整理：对 frequency=1 且无 ai_answer 的独立题按 cat2 做二次合并"""
    # Step 1: 分页加载孤立题（避免一次性 fetchall 内存峰值）
    _SINGLETONS_PAGE_SIZE = 200

    singletons = []
    offset = 0
    while True:
        def _load_page(_offset=offset):
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, sources, "
                "original_questions, original_question_sources "
                "FROM question_bank "
                "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
                "AND frequency = 1 AND (ai_answer IS NULL OR ai_answer = '') "
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

    # Step 2: 按 cat2 分组
    cat2_groups: Dict[str, List[Dict]] = {}
    for r in singletons:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    total_merged = 0

    # Step 3: 逐 cat2 组做内部聚类
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

        # Step 4: 合并成功配对的聚类
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

            # 保留最早的那条（id 最小），合并其余
            qb_entries.sort(key=lambda x: x['id'])
            survivor = qb_entries[0]
            to_merge = qb_entries[1:]

            def _do_merge(s=survivor, m=to_merge):
                conn = get_db_connection()
                conn.execute("BEGIN")
                try:
                    existing = conn.execute(
                        "SELECT sources, original_questions, original_question_sources "
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
                        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (len(s_oqs), json.dumps(s_src, ensure_ascii=False),
                         json.dumps(s_oqs, ensure_ascii=False),
                         json.dumps(s_oqs_src, ensure_ascii=False), s['id'])
                    )
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

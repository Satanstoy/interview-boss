"""
批处理逻辑:增量聚类,完整流水线,孤岛碎片整理
"""
import json
import asyncio
import logging
import numpy as np
from typing import List, Dict, Optional

from app.db.connection import get_db_connection, run_db
from app.db.question_bank_sources import delete_all_for_qb, insert_source, insert_original_item
from app.services.clustering import (
    process_incremental_batch, _cluster_unmatched,
    _call_llm_with_retry, _extract_json, MATCH_EXISTING_PROMPT,
    _validate_merges, VALIDATION_CONFIDENCE_THRESHOLD,
)
from .sanitize import BATCH_SIZE, sanitize_batch
from .queue import dequeue_batch, mark_batch_done, mark_batch_failed, should_trigger_clustering
from .writer import apply_matched, insert_new_clusters, tag_and_write_details

logger = logging.getLogger("interview-boss")

_EXISTING_CLUSTERS_PAGE_SIZE = 100


async def _run_db(func):
    """Use the current db.connection.run_db so tests can patch thread behavior."""
    import app.db.connection as db_module
    return await db_module.run_db(func)


def _compute_merge_confidence(survivor_id: int, merged_question: str) -> float:
    """合并置信度 fallback。

    历史上 embedding 阈值很难稳定控制误合并，这里只做文本包含/精确匹配
    的保守估算，避免把向量相似度当作自动合并依据。
    """
    try:
        conn = get_db_connection()
        row = conn.execute(
            "SELECT question, original_questions FROM question_bank WHERE id = ?", (survivor_id,)
        ).fetchone()
        if not row:
            return 0.70
        texts = [row["question"] or ""]
        try:
            texts.extend(json.loads(row["original_questions"] or "[]"))
        except Exception:
            pass
        merged_question = (merged_question or "").strip()
        for text in texts:
            text = (text or "").strip()
            if merged_question and text == merged_question:
                return 0.95
            if merged_question and text and (merged_question in text or text in merged_question):
                return 0.80
        return 0.70
    except Exception as e:
        logger.warning(f"[置信度fallback] 文本估算失败: {e}")
        return 0.70


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


# ──────────────────────────── 合并历史记录 ────────────────────────────

def _record_merge_history(
    conn, survivor_id: int, merged_ids: List[int],
    merged_questions: List[str], pre_snapshot: Dict,
    post_snapshot: Dict, operation_type: str = 'auto',
    phase: str = '', confidence: float = 0,
    cat2: str = '', operator_id: int = None
) -> int:
    """记录合并操作到 merge_history 表

    Args:
        conn: 数据库连接(在已有事务中调用)
        survivor_id: 合并后保留的题目 ID
        merged_ids: 被合并删除的题目 ID 列表
        merged_questions: 被合并的题目文本列表
        pre_snapshot: 合并前 survivor 题目的快照
        post_snapshot: 合并后的快照
        operation_type: 操作类型 (auto/manual/compaction)
        phase: 聚类阶段 (phase1/phase1.5/phase2/compaction)
        confidence: 验证置信度
        cat2: 题目分类
        operator_id: 操作者用户 ID

    Returns:
        插入的 merge_history 记录 ID
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_history'"
    ).fetchone()
    if not exists:
        logger.warning("[合并记录] merge_history 表不存在，跳过历史记录")
        return 0
    cursor = conn.execute(
        "INSERT INTO merge_history "
        "(survivor_id, merged_ids, merged_questions, pre_snapshot, post_snapshot, "
        "operation_type, phase, confidence, cat2, operator_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            survivor_id,
            json.dumps(merged_ids, ensure_ascii=False),
            json.dumps(merged_questions, ensure_ascii=False),
            json.dumps(pre_snapshot, ensure_ascii=False),
            json.dumps(post_snapshot, ensure_ascii=False),
            operation_type, phase, confidence, cat2, operator_id,
        )
    )
    return cursor.lastrowid


def _snapshot_question(conn, qb_id: int) -> Dict:
    """获取题目当前状态快照(用于合并前备份)"""
    row = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, "
        "ai_answer, sources, original_questions, original_question_sources, "
        "status, job_position, created_at, updated_at "
        "FROM question_bank WHERE id = ?", (qb_id,)
    ).fetchone()
    if not row:
        return {}
    return dict(row)


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


# ============================================================
# 孤岛碎片整理(Compaction)
# ============================================================

_MATCH_BATCH_SIZE = 40
_COMPACTION_CONCURRENCY = 8  # mimo RPM=100，可以更激进
_CAT2_BATCH_SIZE = 5  # Phase 1 每批处理的 cat2 组数
_PHASE2_BATCH_SIZE = 20  # Phase 2 每批合并的题目数（多个小 cat2 组打包）
_SKIP_VALIDATION_EMB_THRESHOLD = 1.01  # 保留常量兼容；不再跳过 LLM 验证


async def _load_existing_clusters_for_compact() -> Dict[str, List[Dict]]:
    """加载所有 frequency>1 且未删除的题(id, question, cat2),按 cat2 分组"""
    def _query():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, question, cat2 FROM question_bank "
            "WHERE status = 'approved' AND deleted_at IS NULL "
            "AND frequency > 1 ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]

    rows = await _run_db(_query)
    by_cat2: Dict[str, List[Dict]] = {}
    for r in rows:
        cat2 = r.get('cat2') or ''
        by_cat2.setdefault(cat2, []).append({"id": r['id'], "question": r['question']})
    return by_cat2


def _do_merge_to_existing(survivor_id: int, entry: Dict,
                          operation_type: str = 'auto', phase: str = '',
                          cat2: str = '', operator_id: int = None,
                          confidence: float = 0):
    """在已有事务中将 frequency=1 题合并到 frequency>1 的 survivor

    记录合并历史到 merge_history 表,支持回滚。
    """
    conn = get_db_connection()
    existing = conn.execute(
        "SELECT question, sources, original_questions, original_question_sources, ai_answer "
        "FROM question_bank WHERE id = ?", (survivor_id,)
    ).fetchone()
    if not existing:
        return

    # 合并前快照
    pre_snapshot = _snapshot_question(conn, survivor_id)

    s_src = _safe_json_list(existing['sources'])
    s_oqs = _safe_json_list(existing['original_questions'])
    s_oqs_src = _safe_json_list(existing['original_question_sources'])
    s_oqs, s_oqs_src = _canonicalize_originals(
        existing['question'], s_src, s_oqs, s_oqs_src
    )

    s_ai_answer = existing['ai_answer']
    if not s_ai_answer:
        s_ai_answer = entry.get('ai_answer')

    seen_urls = {x.get('url') for x in s_src}
    o_src = _safe_json_list(entry.get('sources'))
    for x in o_src:
        u = x.get('url', '')
        if u and u not in seen_urls:
            s_src.append(x)
            seen_urls.add(u)

    o_oqs = _safe_json_list(entry.get('original_questions'))
    o_oqs_src = _safe_json_list(entry.get('original_question_sources'))
    o_oqs, o_oqs_src = _canonicalize_originals(
        entry.get('question', ''), o_src, o_oqs, o_oqs_src
    )
    for oq in o_oqs:
        if oq and oq not in s_oqs:
            s_oqs.append(oq)

    for oqs_entry in o_oqs_src:
        _ensure_original_source_entry(
            s_oqs_src,
            oqs_entry.get('question', ''),
            oqs_entry.get('sources', []),
        )

    try:
        delete_all_for_qb(conn, entry['id'])
    except Exception as e:
        logger.warning(f"[合并] 清理被合并题 normalized 数据失败 (id={entry['id']}): {e}")
    conn.execute("DELETE FROM question_bank WHERE id = ?", (entry['id'],))
    conn.execute("DELETE FROM question_position WHERE question_id = ?", (entry['id'],))

    conn.execute(
        "UPDATE question_bank SET frequency = ?, sources = ?, "
        "original_questions = ?, original_question_sources = ?, "
        "ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (max(1, len(s_oqs)), json.dumps(s_src, ensure_ascii=False),
         json.dumps(s_oqs, ensure_ascii=False),
         json.dumps(s_oqs_src, ensure_ascii=False),
         s_ai_answer, survivor_id)
    )

    try:
        delete_all_for_qb(conn, survivor_id)
    except Exception as e:
        logger.warning(f"[合并] delete_all_for_qb 失败 (id={survivor_id}): {e}")
    for src in s_src:
        try:
            insert_source(conn, survivor_id, src.get('url', ''), src.get('company', ''), src.get('round', ''))
        except Exception as e:
            logger.warning(f"[合并] insert_source 失败 (id={survivor_id}): {e}")
    for oqs_entry in s_oqs_src:
        try:
            insert_original_item(conn, survivor_id, oqs_entry.get('question', ''), oqs_entry.get('sources', []))
        except Exception as e:
            logger.warning(f"[合并] insert_original_item 失败 (id={survivor_id}): {e}")

    # 合并后快照 & 记录历史
    post_snapshot = _snapshot_question(conn, survivor_id)
    # 置信度 fallback: 当 confidence=0 时只用保守文本规则估算
    final_confidence = confidence
    if final_confidence <= 0:
        final_confidence = _compute_merge_confidence(survivor_id, entry.get('question', ''))
        if final_confidence > 0:
            logger.info(f"  [置信度fallback] 原始confidence=0, 文本估算={final_confidence:.2f}")
    _record_merge_history(
        conn, survivor_id,
        merged_ids=[entry['id']],
        merged_questions=[entry.get('question', '')],
        pre_snapshot=pre_snapshot,
        post_snapshot=post_snapshot,
        operation_type=operation_type,
        phase=phase,
        confidence=final_confidence,
        cat2=cat2 or entry.get('cat2', ''),
        operator_id=operator_id,
    )
    logger.info(
        f"  [合并记录] survivor={survivor_id}, 删除={entry['id']}, "
        f"type={operation_type}, phase={phase}, confidence={confidence:.2f}"
    )


async def _match_singletons_to_existing(
    singletons: List[Dict],
    existing_by_cat2: Dict[str, List[Dict]],
    user_id: int = None,
    operator_id: int = None,
) -> set:
    """把 frequency=1 的题和 frequency>1 的题做 LLM 匹配。

    优化:将 cat2 组按 _CAT2_BATCH_SIZE 分批,每批一次 LLM 调用。
    各批次并发执行(Semaphore 控制并发度),大幅减少 API 调用次数。
    原来 20 个 cat2 组需要 40 次 LLM,现在只需 ~8 次。
    """
    matched_ids: set = set()

    sin_by_cat2: Dict[str, List[Dict]] = {}
    for r in singletons:
        cat2 = r.get('cat2') or ''
        sin_by_cat2.setdefault(cat2, []).append(r)

    # 只处理有 existing clusters 的 cat2 组
    active_groups = []
    for cat2, sin_group in sin_by_cat2.items():
        existing = existing_by_cat2.get(cat2, [])
        if existing:
            active_groups.append((cat2, sin_group, existing))

    if not active_groups:
        return matched_ids

    # 按 _CAT2_BATCH_SIZE 分批
    batches = []
    for i in range(0, len(active_groups), _CAT2_BATCH_SIZE):
        batches.append(active_groups[i:i + _CAT2_BATCH_SIZE])

    semaphore = asyncio.Semaphore(_COMPACTION_CONCURRENCY)

    async def _process_batch(batch_groups):
        """处理一批 cat2 组:一次 LLM 调用匹配 + 一次验证"""
        from app.services.clustering import _format_existing_clusters, _format_new_questions

        all_existing_lines = []
        all_new_lines = []
        new_q_map = {}

        for cat2, sin_group, existing in batch_groups:
            cat2_label = cat2 or '(无分类)'
            all_existing_lines.append(f"\n## 分类: {cat2_label}")
            for c in existing:
                all_existing_lines.append(f"[{c['id']}] {c['question']}")
            all_new_lines.append(f"\n## 分类: {cat2_label}")
            for r in sin_group:
                all_new_lines.append(f"[{r['id']}] {r['question']}")
                new_q_map[str(r['id'])] = r

        merge_ops = []
        async with semaphore:
            try:
                prompt = MATCH_EXISTING_PROMPT.format(
                    existing_clusters="\n".join(all_existing_lines),
                    new_questions="\n".join(all_new_lines),
                    count=len(new_q_map),
                )
                content = await _call_llm_with_retry(
                    prompt, response_format={"type": "json_object"}, user_id=user_id
                )
                result = _extract_json(content)
                raw_matches = result.get("matches", [])
                if not raw_matches:
                    return merge_ops

                # 所有 LLM 匹配都需要二次验证；embedding/单次置信度不作为自动合并依据。
                matches_to_validate = raw_matches
                if matches_to_validate:
                    all_existing_flat = []
                    for _, _, existing in batch_groups:
                        all_existing_flat.extend(existing)

                    new_q_for_validate = [{"id": r['id'], "question": r['question']}
                                          for r in new_q_map.values()]
                    validated_matches, confidence_map = await _validate_merges(
                        matches_to_validate, new_q_for_validate, all_existing_flat, user_id
                    )
                    validated_keys = {
                        (str(m.get('new_id')), str(m.get('cluster_id')))
                        for m in validated_matches
                    }

                    for m in matches_to_validate:
                        nid = str(m.get("new_id", ""))
                        cid = m.get("cluster_id")
                        if cid is None:
                            continue
                        if (nid, str(cid)) not in validated_keys:
                            continue
                        entry = new_q_map.get(nid)
                        if not entry:
                            continue
                        conf = confidence_map.get((nid, str(cid)), 0.0)
                        merge_ops.append((cid, entry, conf))

            except Exception as e:
                logger.warning(f"[Compaction→Existing] 批次匹配失败: {e}")

        return merge_ops

    # 并发处理各批次
    batch_results = await asyncio.gather(
        *[_process_batch(b) for b in batches],
        return_exceptions=True
    )

    # 顺序执行 DB 合并
    for res in batch_results:
        if isinstance(res, Exception):
            logger.warning(f"[Compaction→Existing] 批次异常: {res}")
            continue
        for cid, entry, conf in res:
            if entry['id'] in matched_ids:
                continue
            # 零置信度: 使用 embedding fallback 而非跳过
            if conf <= 0:
                conf = _compute_merge_confidence(cid, entry.get('question', ''))
                logger.info(f"[Compaction→Existing] 零置信度fallback: {entry['question'][:30]} → {conf:.2f}")

            def _merge(s_id=cid, e=entry, c=conf):
                conn = get_db_connection()
                conn.execute("BEGIN")
                try:
                    _do_merge_to_existing(s_id, e,
                                          operation_type='compaction',
                                          phase='compaction_to_existing',
                                          cat2=e.get('cat2', ''),
                                          operator_id=operator_id,
                                          confidence=c)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            await _run_db(_merge)
            matched_ids.add(entry['id'])
            logger.info(
                f"[Compaction→Existing] {entry['question'][:40]} → 聚类#{cid} "
                f"(confidence={conf:.2f})"
            )

    return matched_ids


async def compact_singletons_in_db(user_id: int = None, match_existing: bool = False, operator_id: int = None) -> Dict:
    """孤岛碎片整理:对 frequency=1 的独立题按 cat2 做二次合并

    match_existing=True 时会通过 _match_singletons_to_existing 执行 _validate_merges
    二次验证，禁止 LLM 单次判断直接落库。

    Args:
        user_id: LLM 调用使用的用户 ID（None=全局配置，公共题库应始终为 None）
        match_existing: 是否先匹配已有 frequency>1 聚类(默认跳过,因 API 延迟高)
        operator_id: 审计记录的操作者 ID（merge_history 用）
    """
    _audit_id = operator_id or user_id  # 审计用，优先 operator_id
    _SINGLETONS_PAGE_SIZE = 200

    singletons = []
    offset = 0
    while True:
        def _load_page(_offset=offset):
            conn = get_db_connection()
            rows = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, "
                "original_questions, original_question_sources, ai_answer "
                "FROM question_bank "
                "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
                "AND frequency = 1 "
                "ORDER BY id LIMIT ? OFFSET ?",
                (_SINGLETONS_PAGE_SIZE, _offset)
            ).fetchall()
            return [dict(r) for r in rows]

        page = await _run_db(_load_page)
        if not page:
            break
        singletons.extend(page)
        offset += len(page)
        del page
        await asyncio.sleep(0)
    if not singletons:
        return {"total_singletons": 0, "merged": 0, "remaining": 0,
                "matched_to_existing": 0}

    # ── 可选:匹配 frequency>1 已有聚类 ──
    matched_to_existing_ids = set()
    if match_existing:
        existing_by_cat2 = await _load_existing_clusters_for_compact()
        matched_to_existing_ids = await _match_singletons_to_existing(
            singletons, existing_by_cat2, user_id=user_id, operator_id=_audit_id
        )
        if matched_to_existing_ids:
            logger.info(f"[Compaction] 孤岛→已有聚类 匹配合并: {len(matched_to_existing_ids)} 题")

    # 排除已合并的题,剩余再互相比
    remaining_singletons = [r for r in singletons if r['id'] not in matched_to_existing_ids]

    if len(remaining_singletons) < 2:
        return {
            "total_singletons": len(singletons),
            "matched_to_existing": len(matched_to_existing_ids),
            "merged": 0,
            "remaining": len(remaining_singletons),
        }

    # ── Phase 2: 纯 LLM 聚类（按 cat2 分组，并行处理）──
    logger.info(f"[Compaction] Phase 2: 对 {len(remaining_singletons)} 个孤岛做纯 LLM 聚类")

    # 按 cat2 分组
    cat2_groups: Dict[str, List[Dict]] = {}
    for r in remaining_singletons:
        cat2 = r.get('cat2') or ''
        cat2_groups.setdefault(cat2, []).append(r)

    # 跳过"其他"和空分类
    skip_cats = {'其他', ''}
    active_groups = {k: v for k, v in cat2_groups.items() if k not in skip_cats and len(v) >= 2}
    skipped_groups = {k: v for k, v in cat2_groups.items() if k in skip_cats or len(v) < 2}

    logger.info(f"[Compaction] 活跃分组: {len(active_groups)} 个 (跳过: {len(skipped_groups)} 个)")

    semaphore = asyncio.Semaphore(8)  # 并发控制

    async def _process_cat2_group(cat2, group):
        """处理单个 cat2 组的纯 LLM 聚类"""
        items = [{"id": r['id'], "question": r['question']} for r in group]

        async with semaphore:
            try:
                clusters = await _cluster_unmatched(items, user_id)
                return cat2, clusters
            except Exception as e:
                logger.warning(f"[Compaction] {cat2} 聚类失败: {e}")
                return cat2, []

    # 并发处理所有分组
    tasks = [_process_cat2_group(cat2, group) for cat2, group in active_groups.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 收集合并结果
    merge_ops = []
    for res in results:
        if isinstance(res, Exception):
            continue
        cat2, clusters = res

        for cluster in clusters:
            ids = cluster.get("ids", [])
            if len(ids) < 2:
                continue

            # 找到对应的题目
            qb_entries = []
            for sid in ids:
                entry = next((r for r in remaining_singletons if str(r['id']) == str(sid)), None)
                if entry:
                    qb_entries.append(entry)
            if len(qb_entries) < 2:
                continue

            # 按 frequency 排序，选最高的作为 survivor
            qb_entries.sort(key=lambda x: (-x.get('frequency', 1), x['id']))
            survivor = qb_entries[0]
            to_merge = qb_entries[1:]

            # 使用 embedding 门控的置信度
            confidence = 0.9  # 默认置信度
            merge_ops.append((survivor, to_merge, confidence, cat2))

    logger.info(f"[Compaction] Phase 2 完成: {len(merge_ops)} 个合并操作")

    if merge_ops:
        matches_for_validation = []
        new_questions_for_validation = []
        existing_for_validation = []
        pair_lookup = {}

        for survivor, to_merge, confidence, cat2 in merge_ops:
            existing_for_validation.append({
                "id": survivor["id"],
                "question": survivor["question"],
            })
            for entry in to_merge:
                matches_for_validation.append({
                    "new_id": entry["id"],
                    "cluster_id": survivor["id"],
                })
                new_questions_for_validation.append({
                    "id": entry["id"],
                    "question": entry["question"],
                })
                pair_lookup[(str(entry["id"]), str(survivor["id"]))] = (
                    survivor, entry, confidence, cat2
                )

        validated_matches, confidence_map = await _validate_merges(
            matches_for_validation,
            new_questions_for_validation,
            existing_for_validation,
            user_id,
        )
        validated_keys = {
            (str(m.get("new_id")), str(m.get("cluster_id")))
            for m in validated_matches
        }

        validated_ops = []
        for key in validated_keys:
            item = pair_lookup.get(key)
            if not item:
                continue
            survivor, entry, default_confidence, cat2 = item
            confidence = confidence_map.get(key, default_confidence)
            validated_ops.append((survivor, [entry], confidence, cat2))

        rejected = len(matches_for_validation) - len(validated_ops)
        if rejected:
            logger.info(f"[Compaction] Phase 2 二次验证拒绝 {rejected} 个候选合并")
        merge_ops = validated_ops

    # 执行合并
    total_merged = 0
    for survivor, to_merge, confidence, cat2 in merge_ops:
        for entry in to_merge:
            def _do_merge(s_id=survivor['id'], e=entry, c=confidence):
                conn = get_db_connection()
                conn.execute("BEGIN")
                try:
                    _do_merge_to_existing(s_id, e,
                                          operation_type='compaction',
                                          phase='compaction_pure_llm',
                                          cat2=cat2,
                                          operator_id=_audit_id,
                                          confidence=c)
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise

            await _run_db(_do_merge)
            total_merged += 1

    return {
        "total_singletons": len(singletons),
        "matched_to_existing": len(matched_to_existing_ids),
        "merged": total_merged,
        "remaining": len(remaining_singletons) - total_merged,
    }

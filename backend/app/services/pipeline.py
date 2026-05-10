"""
两阶段流水线服务

阶段1（并发）: 面经 → tag → questions_detail + enqueue
阶段2（串行）: queue达到batch_size 或 全部完成 → 聚类 → question_bank
"""
import json
import logging
import asyncio
from typing import List, Dict, Optional, Tuple

from app.db.connection import get_db_connection, run_db
from app.db.operations import _cleanup_old_sources_txn_v2
from app.services.clustering import (
    cluster_all_questions, generate_unified_question, CLUSTER_PROMPT,
    _format_questions, _cluster_batch, _verify_group, FORBIDDEN_PATTERNS,
    CROSS_CAT_MERGE_PROMPT, CLUSTER_PROMPT_PASS2
)
from app.services.llm import _call_llm_with_retry
from app.core.prompts import build_tagging_prompt, TAGGING_PROMPT

logger = logging.getLogger("interview-boss")

BATCH_SIZE = 20


# ============================================================
# 队列操作
# ============================================================

def enqueue_interview(interview_id: int) -> int:
    """将面经加入分析队列，返回队列记录ID"""
    conn = get_db_connection()
    cursor = conn.execute(
        "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
        (interview_id,)
    )
    conn.commit()
    return cursor.lastrowid


def get_pending_count() -> int:
    """获取待处理队列数量"""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'"
    ).fetchone()
    return row['c']


def get_processing_count() -> int:
    """获取正在处理的任务数量"""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'processing'"
    ).fetchone()
    return row['c']


def should_trigger_clustering(batch_size: int = BATCH_SIZE) -> bool:
    """判断是否应该触发聚类

    触发条件：
    1. pending 数量 >= batch_size
    2. 或者：没有 processing 任务 且 有 pending 任务（全部完成）
    """
    pending = get_pending_count()
    if pending >= batch_size:
        return True
    processing = get_processing_count()
    return processing == 0 and pending > 0


def dequeue_batch(batch_size: int = BATCH_SIZE) -> List[Dict]:
    """取出一批 pending 任务并标记为 processing

    返回：[{"queue_id": ..., "interview_id": ..., "url": ..., ...}, ...]
    """
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT aq.id as queue_id, aq.interview_id, i.url, i.company, i.round, "
        "i.questions_list, i.job_position, i.owner_id "
        "FROM analysis_queue aq "
        "JOIN interview i ON aq.interview_id = i.id "
        "WHERE aq.status = 'pending' "
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
    """标记一批任务为完成"""
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
    """标记一批任务为失败（回退为 pending 以便重试）"""
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
# 阶段1：打标签（并发安全，只写 questions_detail）
# ============================================================

async def tag_interview(interview_id: int, url: str, company: str,
                        round_: str, questions_list: str,
                        job_position: str = "", user_id: int = None) -> List[List[str]]:
    """阶段1：对一条面经打标签，只写 questions_detail，不碰 question_bank

    返回：tagged_rows（每行是 [url, company, round, question, cat1, cat2, tags, difficulty]）
    """
    # 解析题目列表
    raw_lines = [q.strip() for q in questions_list.split("\n") if q.strip()]
    questions = []
    for line in raw_lines:
        # 去掉序号前缀
        import re
        cleaned = re.sub(r'^[\d]+[.、)\]\s]+', '', line).strip()
        if cleaned:
            questions.append(cleaned)

    if not questions:
        return []

    # LLM 打标签
    from app.routers.submit import tag_questions_batch
    tagged_rows = await tag_questions_batch(url, company, round_, questions,
                                            user_id=user_id)

    # 只写 questions_detail（原子操作）
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
# 阶段2：批量聚类（串行，原子写入 question_bank）
# ============================================================

async def cluster_batch(batch: List[Dict], user_id: int = None) -> int:
    """阶段2：对一批面经的 tagged 数据做聚类，原子写入 question_bank

    batch: dequeue_batch() 返回的任务列表
    返回：新生成的 question_bank 记录数
    """
    if not batch:
        return 0

    job_position = batch[0].get('job_position', '') or ''

    # 1. 加载这批面经的所有 questions_detail
    urls = list({item['url'] for item in batch if item.get('url')})
    if not urls:
        return 0

    conn = get_db_connection()
    placeholders = ','.join('?' * len(urls))
    new_rows = conn.execute(
        f"SELECT id, url, company, round, question, cat1, cat2, tags, diff_tag "
        f"FROM questions_detail "
        f"WHERE url IN ({placeholders}) AND deleted_at IS NULL AND job_position = ?",
        (*urls, job_position)
    ).fetchall()
    new_rows = [dict(r) for r in new_rows]

    if not new_rows:
        return 0

    # 2. 加载已有 question_bank 聚类（公共，未删除）
    existing_rows = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, "
        "sources, original_questions, original_question_sources "
        "FROM question_bank "
        "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL AND job_position = ?",
        (job_position,)
    ).fetchall()
    existing_rows = [dict(r) for r in existing_rows]

    # 3. 合并：已有聚类 + 新题，一起做聚类
    # 已有聚类用 question_bank.id 作为 id，新题用 questions_detail.id（加前缀区分）
    all_items = []
    id_map = {}  # item_id -> {"is_existing": bool, "qb_id" or "qd_id": int}

    for er in existing_rows:
        item_id = f"existing_{er['id']}"
        all_items.append({"id": item_id, "question": er['question'], "cat2": er['cat2'] or ""})
        id_map[item_id] = {"is_existing": True, "qb_id": er['id'], "data": er}

    for nr in new_rows:
        item_id = f"new_{nr['id']}"
        all_items.append({"id": item_id, "question": nr['question'], "cat2": nr['cat2'] or ""})
        id_map[item_id] = {"is_existing": False, "qd_id": nr['id'], "data": nr}

    # 4. 执行聚类
    clusters = await cluster_all_questions(all_items, user_id=user_id)

    # 5. 构建聚类详情并原子写入
    cluster_details = _build_cluster_details(clusters, id_map, urls, job_position)

    # 6. 生成 unified questions
    semaphore = asyncio.Semaphore(8)

    async def gen_uq(detail):
        if len(detail['original_questions']) > 1:
            async with semaphore:
                detail['question'] = await generate_unified_question(
                    detail['original_questions'],
                    detail.get('sources_context'),
                    user_id=user_id
                )
        elif detail['original_questions']:
            detail['question'] = detail['original_questions'][0]

    await asyncio.gather(*(gen_uq(d) for d in cluster_details))

    # 7. 原子写入：清理旧的 + 插入新的
    def _atomic_write():
        conn = get_db_connection()
        conn.execute("BEGIN")
        try:
            # 清理这批面经对 question_bank 的旧贡献（彻底清理）
            for url in urls:
                _cleanup_old_sources_txn_v2(conn.cursor(), url, job_position)

            # 删除旧的 questions_detail（已被新的替换）
            # 注意：tag_interview 已经替换了 questions_detail，这里不需要再删

            # 插入新的聚类记录
            qb_ids = []
            for detail in cluster_details:
                cursor = conn.execute(
                    "INSERT INTO question_bank "
                    "(question, cat1, cat2, tags, difficulty, frequency, sources, "
                    "original_questions, original_question_sources, owner_id, job_position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (detail['question'], detail['cat1'], detail['cat2'],
                     detail['tags'], detail['difficulty'], detail['frequency'],
                     json.dumps(detail['sources'], ensure_ascii=False),
                     json.dumps(detail['original_questions'], ensure_ascii=False),
                     json.dumps(detail['original_question_sources'], ensure_ascii=False),
                     job_position)
                )
                new_id = cursor.lastrowid
                qb_ids.append(new_id)

                # 关联岗位
                pos_rows = conn.execute("SELECT id FROM job_positions WHERE name = ?",
                                        (job_position,)).fetchall()
                for pr in pos_rows:
                    conn.execute(
                        "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                        (new_id, pr['id'])
                    )

                # 恢复已有 AI 答案
                if detail.get('existing_ai_answer'):
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = ? WHERE id = ?",
                        (detail['existing_ai_answer'], new_id)
                    )

            conn.execute("COMMIT")
            return qb_ids
        except Exception:
            conn.execute("ROLLBACK")
            raise

    qb_ids = await run_db(_atomic_write)

    # 8. 后台生成 AI 答案（对没有答案的新聚类）
    from app.routers.submit import background_generate_answer
    answer_tasks = []
    for i, detail in enumerate(cluster_details):
        if not detail.get('existing_ai_answer') and i < len(qb_ids):
            answer_tasks.append((qb_ids[i], detail['question']))

    return len(qb_ids)


def _build_cluster_details(clusters, id_map, batch_urls, job_position):
    """从聚类结果构建 question_bank 写入详情"""
    details = []

    for cluster in clusters:
        ids = cluster.get('ids', [])
        if not ids:
            continue

        # 收集聚类内的所有项目
        items = []
        for item_id in ids:
            if item_id in id_map:
                items.append(id_map[item_id])

        if not items:
            continue

        # 确定 cat1/cat2（优先使用已有聚类的）
        existing_items = [it for it in items if it['is_existing']]
        new_items = [it for it in items if not it['is_existing']]

        if existing_items:
            cat1 = existing_items[0]['data'].get('cat1', '')
            cat2 = existing_items[0]['data'].get('cat2', '')
        elif new_items:
            cat1 = new_items[0]['data'].get('cat1', '')
            cat2 = new_items[0]['data'].get('cat2', '')
        else:
            cat1, cat2 = '', ''

        # 收集 tags（合并所有项的 tags）
        all_tags = set()
        for it in items:
            tags_str = it['data'].get('tags', '')
            if tags_str:
                for t in tags_str.split(','):
                    t = t.strip()
                    if t:
                        all_tags.add(t)

        # 收集 difficulty（取最常见的）
        difficulties = [it['data'].get('difficulty', '') or it['data'].get('diff_tag', '')
                       for it in items if it['data'].get('difficulty') or it['data'].get('diff_tag')]
        difficulty = max(set(difficulties), key=difficulties.count) if difficulties else 'L2-中等'

        # 构建 sources 和 original_questions
        sources = []
        original_questions = []
        original_question_sources = []
        existing_ai_answer = None
        seen_urls = set()

        for it in items:
            if it['is_existing']:
                # 已有聚类：保留其 sources/oqs
                data = it['data']
                try:
                    old_sources = json.loads(data.get('sources', '[]'))
                except Exception:
                    old_sources = []
                try:
                    old_oqs = json.loads(data.get('original_questions', '[]'))
                except Exception:
                    old_oqs = []
                try:
                    old_oqs_sources = json.loads(data.get('original_question_sources', '[]'))
                except Exception:
                    old_oqs_sources = []

                for s in old_sources:
                    if s.get('url') not in seen_urls:
                        sources.append(s)
                        seen_urls.add(s.get('url'))
                original_questions.extend(old_oqs)
                original_question_sources.extend(old_oqs_sources)
                if data.get('ai_answer'):
                    existing_ai_answer = data['ai_answer']
            else:
                # 新题
                data = it['data']
                url = data.get('url', '')
                if url and url not in seen_urls:
                    sources.append({
                        "url": url,
                        "company": data.get('company', ''),
                        "round": data.get('round', '')
                    })
                    seen_urls.add(url)
                q = data.get('question', '')
                if q:
                    original_questions.append(q)
                    original_question_sources.append({
                        "question": q,
                        "url": url
                    })

        # 去重 original_questions
        seen_oq = set()
        deduped_oqs = []
        deduped_oqs_sources = []
        for i, oq in enumerate(original_questions):
            if oq not in seen_oq:
                seen_oq.add(oq)
                deduped_oqs.append(oq)
                if i < len(original_question_sources):
                    deduped_oqs_sources.append(original_question_sources[i])

        details.append({
            'question': cluster.get('representative', deduped_oqs[0] if deduped_oqs else ''),
            'cat1': cat1,
            'cat2': cat2,
            'tags': ', '.join(sorted(all_tags)),
            'difficulty': difficulty,
            'frequency': len(sources),
            'sources': sources,
            'original_questions': deduped_oqs,
            'original_question_sources': deduped_oqs_sources,
            'existing_ai_answer': existing_ai_answer,
            'sources_context': sources,
        })

    return details


# ============================================================
# 完整流水线：打标签 + 聚类
# ============================================================

async def process_interview_tag_then_maybe_cluster(
    interview_id: int, url: str, company: str, round_: str,
    questions_list: str, job_position: str = "",
    user_id: int = None, batch_size: int = BATCH_SIZE
) -> Dict:
    """完整流程：打标签 → 入队 → 检查是否触发聚类

    返回：{"tagged_count": int, "clustered": bool, "new_qb_count": int}
    """
    # 阶段1：打标签（只写 questions_detail）
    tagged_rows = await tag_interview(
        interview_id, url, company, round_, questions_list,
        job_position=job_position, user_id=user_id
    )

    # 入队
    enqueue_interview(interview_id)

    # 检查是否触发聚类
    result = {"tagged_count": len(tagged_rows), "clustered": False, "new_qb_count": 0}

    if should_trigger_clustering(batch_size):
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
    total_new = 0
    total_batches = 0

    while True:
        batch = dequeue_batch(BATCH_SIZE)
        if not batch:
            break
        try:
            new_count = await cluster_batch(batch, user_id=user_id)
            queue_ids = [item['queue_id'] for item in batch]
            mark_batch_done(queue_ids)
            total_new += new_count
            total_batches += 1
        except Exception as e:
            logger.error(f"聚类批次 {total_batches + 1} 失败: {e}")
            queue_ids = [item['queue_id'] for item in batch]
            mark_batch_failed(queue_ids)
            raise

    return {"batches": total_batches, "new_qb_count": total_new}

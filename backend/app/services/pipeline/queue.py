"""
队列操作：enqueue / dequeue / mark_done / mark_failed / trigger 判断
"""

import asyncio
import logging
import os
from typing import List, Dict

from app.db.connection import get_db_connection
from .sanitize import BATCH_SIZE

logger = logging.getLogger("interview-boss")

STUCK_PROCESSING_THRESHOLD_MINUTES = 30


def enqueue_questions(interview_id: int, owner_id: int = None) -> int:
    """将一条面经的所有 questions_detail 加入分析队列，返回队列记录数。

    Args:
        interview_id: 面经 ID
        owner_id: NULL = 公共队列, user_id = 个人队列（隔离匹配）
    """
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id FROM questions_detail WHERE url = (SELECT url FROM interview WHERE id = ?) AND deleted_at IS NULL",
        (interview_id,),
    ).fetchall()
    count = 0
    for r in rows:
        conn.execute(
            "INSERT OR IGNORE INTO analysis_queue (interview_id, question_detail_id, status, owner_id) VALUES (?, ?, 'pending', ?)",
            (interview_id, r[0], owner_id),
        )
        count += 1
    conn.commit()
    return count


def get_pending_count() -> int:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'"
    ).fetchone()
    return row["c"]


def get_processing_count() -> int:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'processing'"
    ).fetchone()
    return row["c"]


def _recover_stuck_processing():
    conn = get_db_connection()
    conn.execute(
        "UPDATE analysis_queue SET status = 'pending' "
        "WHERE status = 'processing' AND created_at < datetime('now', ?)",
        (f"-{STUCK_PROCESSING_THRESHOLD_MINUTES} minutes",),
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
    """原子取出一批 pending 任务并标记为 processing（防并发重复取出）。

    Returns items from a single owner_id bucket (NULL for public, or a specific
    user_id for personal). This guarantees ``cluster_batch`` never mixes
    personal and public questions in the same batch.
    """
    _recover_stuck_processing()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    try:
        # Pick the owner_id bucket with the most pending items.
        # NULL owner_id (public) gets priority when tied.
        bucket = cursor.execute(
            "SELECT owner_id, COUNT(*) as cnt FROM analysis_queue "
            "WHERE status = 'pending' "
            "GROUP BY owner_id ORDER BY cnt DESC LIMIT 1"
        ).fetchone()
        if not bucket:
            conn.commit()
            return []
        target_owner = bucket["owner_id"]

        rows = cursor.execute(
            "UPDATE analysis_queue SET status = 'processing', processed_at = CURRENT_TIMESTAMP "
            "WHERE id IN ("
            "  SELECT aq.id FROM analysis_queue aq "
            "  JOIN questions_detail qd ON aq.question_detail_id = qd.id "
            "  WHERE aq.status = 'pending' AND qd.deleted_at IS NULL "
            "  AND (aq.owner_id = ? OR (aq.owner_id IS NULL AND ? IS NULL)) "
            "  ORDER BY aq.id LIMIT ?"
            ") RETURNING id as queue_id, question_detail_id as qd_id, owner_id",
            (target_owner, target_owner, batch_size),
        ).fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if not rows:
        return []

    batch_owner_id = rows[0]["owner_id"] if rows else None
    qd_ids = [r["qd_id"] for r in rows]
    if not qd_ids:
        return []
    placeholders = ",".join("?" * len(qd_ids))
    details = conn.execute(
        f"SELECT id, question, cat1, cat2, tags, diff_tag, url, company, round, job_position "
        f"FROM questions_detail WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        qd_ids,
    ).fetchall()
    detail_map = {d["id"]: dict(d) for d in details}

    result = []
    for r in rows:
        d = detail_map.get(r["qd_id"], {})
        if d:
            d["queue_id"] = r["queue_id"]
            d["qd_id"] = r["qd_id"]
            d["owner_id"] = batch_owner_id
            result.append(d)
    return result


def mark_batch_done(queue_ids: List[int]):
    if not queue_ids:
        return
    conn = get_db_connection()
    placeholders = ",".join("?" * len(queue_ids))
    conn.execute(
        f"UPDATE analysis_queue SET status = 'done', processed_at = CURRENT_TIMESTAMP "
        f"WHERE id IN ({placeholders})",
        queue_ids,
    )
    conn.commit()


def mark_batch_failed(queue_ids: List[int]):
    if not queue_ids:
        return
    conn = get_db_connection()
    placeholders = ",".join("?" * len(queue_ids))
    conn.execute(
        f"UPDATE analysis_queue SET status = 'pending' WHERE id IN ({placeholders})",
        queue_ids,
    )
    conn.commit()


# ──────────────────────────────────────────────────────────────
# 聚类异步化（实验结论 P3）：cluster_public_node 不再同步 await，
# 改为调度后台任务；攒批触发（pending ≥ BATCH_SIZE 立即聚，否则延迟）
# ──────────────────────────────────────────────────────────────

# 攒批延迟窗口（秒）：pending < BATCH_SIZE 时延迟再聚，给连续导入留合并窗口。
# 可用环境变量 CLUSTER_DELAY_SECONDS 覆盖。
CLUSTER_DELAY_SECONDS = int(os.environ.get("CLUSTER_DELAY_SECONDS", "300"))

# 模块级标志：同时只允许一个后台聚类任务在等/在跑（多 worker 进程各自维护，
# dequeue_batch 原子取批兜底防重复）。
_cluster_task_running = False


def _run_cluster_batch_in_background(user_id: int = None) -> bool:
    """调度后台聚类任务（攒批语义），返回是否已调度。

    - pending >= BATCH_SIZE → 立即执行
    - pending < BATCH_SIZE → 延迟 CLUSTER_DELAY_SECONDS 再执行（期间新提交并入同一批）
    - 已有任务在等/在跑 → 不重复调度（新题会被该任务处理）
    """
    global _cluster_task_running
    if _cluster_task_running:
        return False
    _cluster_task_running = True

    async def _run():
        global _cluster_task_running
        try:
            _recover_stuck_processing()
            pending = get_pending_count()
            if pending >= BATCH_SIZE:
                delay = 0
            else:
                delay = CLUSTER_DELAY_SECONDS
            if delay:
                logger.info(
                    "[聚类后台] pending=%d < %d，延迟 %ds 后聚类（攒批窗口）",
                    pending,
                    BATCH_SIZE,
                    delay,
                )
                await asyncio.sleep(delay)
                _recover_stuck_processing()
                if get_pending_count() == 0:
                    return
            batch = dequeue_batch(BATCH_SIZE)
            if not batch:
                return
            try:
                new_count = await cluster_batch(batch, user_id=user_id)
                mark_batch_done([item["queue_id"] for item in batch])
                logger.info(
                    "[聚类后台] 完成: %d 题 → %d 个新聚类", len(batch), new_count
                )
            except Exception as e:
                logger.error("[聚类后台] 失败，回退队列状态: %s", e)
                mark_batch_failed([item["queue_id"] for item in batch])
        except Exception as e:
            logger.error("[聚类后台] 任务异常: %s", e)
        finally:
            _cluster_task_running = False

    from app.services.pipeline import cluster_batch, mark_batch_done, mark_batch_failed

    asyncio.create_task(_run())
    return True

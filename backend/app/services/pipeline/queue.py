"""
队列操作：enqueue / dequeue / mark_done / mark_failed / trigger 判断
"""

import logging
import os
import json
from uuid import uuid4
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
# 聚类攒批：延迟窗口由 jobs.available_at 持久化，ARQ 只执行 job。
# ──────────────────────────────────────────────────────────────

# 攒批延迟窗口（秒）：pending < BATCH_SIZE 时延迟再聚，给连续导入留合并窗口。
# 可用环境变量 CLUSTER_DELAY_SECONDS 覆盖。
CLUSTER_DELAY_SECONDS = int(os.environ.get("CLUSTER_DELAY_SECONDS", "300"))

async def _run_cluster_batch_in_background(user_id: int = None) -> bool:
    """创建一个持久化攒批 Job，返回是否新建了任务。

    pending 不足一批时使用 ``available_at`` 保留攒批窗口；达到阈值则
    立即尝试入队。即使 Redis 或 Web 进程随后不可用，dispatcher 仍会
    根据 jobs 表接管 pending 任务。
    """
    def _create():
        conn = get_db_connection()
        try:
            _recover_stuck_processing()
            existing = conn.execute(
                "SELECT id FROM jobs WHERE job_type = 'cluster_batch' "
                "AND status IN ('pending', 'queued', 'running') LIMIT 1"
            ).fetchone()
            if existing:
                return None, None

            pending = conn.execute(
                "SELECT COUNT(*) AS c FROM analysis_queue WHERE status = 'pending'"
            ).fetchone()["c"]
            delay = 0 if pending >= BATCH_SIZE else CLUSTER_DELAY_SECONDS
            cursor = conn.execute(
                "INSERT INTO jobs "
                "(job_type, status, progress_total, created_by, available_at, idempotency_key) "
                "VALUES ('cluster_batch', 'pending', ?, ?, datetime('now', ?), ?)",
                (
                    max(int(pending), 1),
                    user_id,
                    f"+{delay} seconds",
                    f"cluster-window:{user_id or 'public'}:{uuid4().hex}",
                ),
            )
            job_id = int(cursor.lastrowid)
            conn.execute(
                "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                (job_id, json.dumps({"user_id": user_id}, ensure_ascii=False)),
            )
            conn.commit()
            return job_id, delay
        except Exception:
            conn.rollback()
            raise

    job_id, delay = _create()
    if not job_id:
        return False

    if delay:
        logger.info(
            "[聚类后台] pending=%d < %d，创建 %ds 攒批窗口 job=%s",
            get_pending_count(),
            BATCH_SIZE,
            delay,
            job_id,
        )
        return True

    try:
        from app.services.job_lifecycle import mark_job_dispatched
        from app.worker import enqueue_cluster_batch_job

        arq_job = await enqueue_cluster_batch_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")
        conn = get_db_connection()
        if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
            raise RuntimeError(f"聚类攒批任务不可再投递: job_id={job_id}")
        conn.commit()
    except Exception as exc:
        logger.warning(
            "[聚类后台] ARQ 调度失败，job=%s 保留 pending 等待 dispatcher: %s",
            job_id,
            exc,
        )
    return True

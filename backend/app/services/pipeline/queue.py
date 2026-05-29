"""
队列操作：enqueue / dequeue / mark_done / mark_failed / trigger 判断
"""
import logging
from typing import List, Dict

from app.db.connection import get_db_connection
from .sanitize import BATCH_SIZE

logger = logging.getLogger("interview-boss")

STUCK_PROCESSING_THRESHOLD_MINUTES = 30


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
    """原子取出一批 pending 任务并标记为 processing（防并发重复取出）"""
    _recover_stuck_processing()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    try:
        rows = cursor.execute(
            "UPDATE analysis_queue SET status = 'processing', processed_at = CURRENT_TIMESTAMP "
            "WHERE id IN ("
            "  SELECT aq.id FROM analysis_queue aq "
            "  JOIN questions_detail qd ON aq.question_detail_id = qd.id "
            "  WHERE aq.status = 'pending' AND qd.deleted_at IS NULL "
            "  ORDER BY aq.id LIMIT ?"
            ") RETURNING id as queue_id, question_detail_id as qd_id",
            (batch_size,)
        ).fetchall()
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if not rows:
        return []

    qd_ids = [r['qd_id'] for r in rows]
    if not qd_ids:
        return []
    placeholders = ','.join('?' * len(qd_ids))
    details = conn.execute(
        f"SELECT id, question, cat1, cat2, tags, diff_tag, url, company, round, job_position "
        f"FROM questions_detail WHERE id IN ({placeholders}) AND deleted_at IS NULL",
        qd_ids
    ).fetchall()
    detail_map = {d['id']: dict(d) for d in details}

    result = []
    for r in rows:
        d = detail_map.get(r['qd_id'], {})
        if d:
            d['queue_id'] = r['queue_id']
            d['qd_id'] = r['qd_id']
            result.append(d)
    return result


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

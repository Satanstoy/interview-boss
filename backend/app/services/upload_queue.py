"""v2 聚类队列调度：桶选择、幂等补单与对账（AC-007 / UR-007）。

设计要点（contracts §2.5）：

- 桶 = (root_import_id, scope, 岗位)；dequeue 必须按桶推进，不能整族只跑一批。
- 对账（建议 60 秒一次）：有 pending 但无活跃 job 的桶补**一个**幂等 job。
- 选桶按最早可用时间 + 轮转，避免公共大桶永远占满调度。
- 孤儿/被删原文转 ``blocked`` 并保留证据，不空转、不删除。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")

ANALYSIS_JOB_TYPE = "analysis_batch"
ACTIVE_JOB_STATUSES = ("pending", "queued", "running")


def _scope_key(root_import_id, owner_id, job_position) -> str:
    scope = "public" if owner_id is None else f"user:{owner_id}"
    return f"{root_import_id}:{scope}:{job_position or ''}"


def collect_pending_buckets(conn) -> list[dict]:
    """返回合法 pending 桶（原文与明细都未删除）。"""

    rows = conn.execute(
        """
        SELECT q.root_import_id AS root_import_id,
               q.owner_id AS owner_id,
               COALESCE(i.job_position, '') AS job_position,
               COUNT(*) AS pending_count,
               MIN(q.created_at) AS available_at
        FROM analysis_queue q
        JOIN interview i ON i.id = q.interview_id
        JOIN questions_detail d ON d.id = q.question_detail_id
        WHERE q.status = 'pending'
          AND q.root_import_id IS NOT NULL
          AND q.question_detail_id IS NOT NULL
          AND i.deleted_at IS NULL
          AND d.deleted_at IS NULL
        GROUP BY q.root_import_id, q.owner_id, COALESCE(i.job_position, '')
        ORDER BY MIN(q.created_at), q.root_import_id
        """
    ).fetchall()

    buckets = []
    for row in rows:
        key = _scope_key(row["root_import_id"], row["owner_id"], row["job_position"])
        buckets.append(
            {
                "root_import_id": row["root_import_id"],
                "owner_id": row["owner_id"],
                "job_position": row["job_position"],
                "scope_key": key,
                "work_key": f"cluster:{key}:v1",
                "pending_count": int(row["pending_count"]),
                "available_at": row["available_at"],
            }
        )
    return buckets


def select_next_bucket(buckets, *, recently_selected=None):
    """最早可用优先 + 轮转：刚选过的 scope 排到本轮队尾。"""

    if not buckets:
        return None
    recent = set(recently_selected or [])
    ordered = sorted(
        buckets,
        key=lambda bucket: (
            bucket["scope_key"] in recent,
            bucket["available_at"] or "",
            bucket["scope_key"],
        ),
    )
    return ordered[0]


def ensure_bucket_job(conn, *, bucket: dict, created_by=None) -> dict:
    """为桶补一个幂等 job；已有活跃 job 则复用。"""

    active = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND work_key = ? "
        "AND status IN ('pending','queued','running') LIMIT 1",
        (bucket["root_import_id"], bucket["work_key"]),
    ).fetchone()
    if active is not None:
        return {"created": False, "job_id": int(active["id"])}

    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key, "
        "progress_message) VALUES (?, 'pending', ?, ?, ?, ?)",
        (
            ANALYSIS_JOB_TYPE,
            created_by,
            bucket["root_import_id"],
            bucket["work_key"],
            f"队列补单: {bucket['scope_key']} ({bucket['pending_count']} 题)",
        ),
    )
    return {"created": True, "job_id": int(cursor.lastrowid)}


def mark_orphan_rows_blocked(conn) -> int:
    """孤儿队列行（原文/明细已删除）转 blocked，保留证据。"""

    cursor = conn.execute(
        """
        UPDATE analysis_queue
        SET status = 'blocked', processed_at = CURRENT_TIMESTAMP
        WHERE status = 'pending'
          AND root_import_id IS NOT NULL
          AND (
            question_detail_id IS NULL
            OR interview_id IS NULL
            OR NOT EXISTS (
                SELECT 1 FROM interview i
                WHERE i.id = analysis_queue.interview_id AND i.deleted_at IS NULL
            )
            OR NOT EXISTS (
                SELECT 1 FROM questions_detail d
                WHERE d.id = analysis_queue.question_detail_id AND d.deleted_at IS NULL
            )
          )
        """
    )
    return cursor.rowcount


def reconcile_pending_buckets(conn, *, created_by=None) -> dict:
    """一次对账：处理孤儿 + 为无活跃 job 的桶补单。"""

    orphans_blocked = mark_orphan_rows_blocked(conn)
    buckets = collect_pending_buckets(conn)
    created = 0
    for bucket in buckets:
        result = ensure_bucket_job(conn, bucket=bucket, created_by=created_by)
        if result["created"]:
            created += 1
    report = {
        "buckets": len(buckets),
        "jobs_created": created,
        "orphans_blocked": orphans_blocked,
    }
    if created or orphans_blocked:
        logger.info("队列对账: %s", report)
    return report

"""v2 聚类队列调度：桶选择、幂等补单与对账（AC-007 / UR-007）。

设计要点（contracts §2.5）：

- 桶 = (root_import_id, scope, 岗位)；dequeue 必须按桶推进，不能整族只跑一批。
- 对账（建议 60 秒一次）：有 pending 但无活跃 job 的桶补**一个**幂等 job。
- 选桶按最早可用时间 + 轮转，避免公共大桶永远占满调度。
- 孤儿/被删原文转 ``blocked`` 并保留证据，不空转、不删除。

R06：补单 job 复用已注册可执行的 ``cluster_batch`` 类型（不新造
``analysis_batch`` 孤儿类型，避免注册/执行适配缺失）。
"""

from __future__ import annotations

import logging
import json

from app.services.job_lifecycle import CLUSTER_BATCH_JOB_TYPE

logger = logging.getLogger("interview-boss")

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
               MAX(CASE WHEN q.contribution_request_id IS NOT NULL THEN 1 ELSE 0 END) AS has_contribution,
               MIN(q.created_at) AS available_at
        FROM analysis_queue q
        JOIN interview i ON i.id = q.interview_id
        JOIN questions_detail d ON d.id = q.question_detail_id
        WHERE q.status = 'pending'
          AND q.root_import_id IS NOT NULL
          AND q.question_detail_id IS NOT NULL
          AND i.deleted_at IS NULL
          AND d.deleted_at IS NULL
          AND NOT (
              q.contribution_request_id IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM public_contribution_items pci
                  WHERE pci.request_id = q.contribution_request_id
                    AND pci.public_detail_id = q.question_detail_id
                    AND pci.status = 'failed'
              )
          )
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
                "has_contribution": bool(row["has_contribution"]),
                "available_at": row["available_at"],
            }
        )
    return buckets


def select_next_bucket(buckets, *, recently_selected=None):
    """Select every eligible scope once before starting the next round.

    ``recently_selected`` is a mutable list carried by the durable continuation
    job. A larger public backlog therefore cannot repeatedly win on count alone
    while public work continues arriving.
    """

    if not buckets:
        if isinstance(recently_selected, list):
            recently_selected.clear()
        return None

    keys = {bucket["scope_key"] for bucket in buckets}
    history = list(dict.fromkeys(
        key for key in (recently_selected or []) if key in keys
    ))
    if keys.issubset(history):
        history = []

    ordered = sorted(
        buckets,
        key=lambda bucket: (
            bucket["scope_key"] in history,
            bucket["available_at"] or "",
            bucket["scope_key"],
        ),
    )
    selected = ordered[0]
    history.append(selected["scope_key"])
    if keys.issubset(history):
        history = []
    if isinstance(recently_selected, list):
        recently_selected[:] = history
    return selected


def ensure_bucket_job(conn, *, bucket: dict, created_by=None) -> dict:
    """为桶补一个幂等 job；已有活跃 job 则复用。"""

    active = conn.execute(
        "SELECT id FROM jobs WHERE root_import_id = ? AND work_key = ? "
        "AND status IN ('pending','queued','running') LIMIT 1",
        (bucket["root_import_id"], bucket["work_key"]),
    ).fetchone()
    if active is not None:
        return {"created": False, "job_id": int(active["id"])}

    root = conn.execute(
        "SELECT requester_id, policy_json FROM upload_imports WHERE id = ?",
        (bucket["root_import_id"],),
    ).fetchone()
    attempt = conn.execute(
        "SELECT id FROM upload_attempts WHERE import_id = ? ORDER BY attempt_no DESC LIMIT 1",
        (bucket["root_import_id"],),
    ).fetchone()
    policy = {}
    if root:
        try:
            policy = json.loads(root["policy_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            policy = {}
    if bucket.get("owner_id") is not None:
        credential_scope = "user"
        user_id = int(bucket["owner_id"])
    elif bucket.get("has_contribution"):
        credential_scope = policy.get("post_approval_credential_scope") or "global"
        user_id = int(root["requester_id"]) if credential_scope == "user" and root else None
    else:
        credential_scope = policy.get("credential_scope") or "global"
        user_id = int(root["requester_id"]) if credential_scope == "user" and root else None

    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, upload_attempt_id, "
        "work_key, progress_total, progress_message) "
        "VALUES (?, 'pending', ?, ?, ?, ?, ?, ?)",
        (
            CLUSTER_BATCH_JOB_TYPE,
            created_by,
            bucket["root_import_id"],
            int(attempt["id"]) if attempt else None,
            bucket["work_key"],
            int(bucket.get("pending_count") or 1),
            f"队列补单: {bucket['scope_key']} ({bucket['pending_count']} 题)",
        ),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            job_id,
            json.dumps(
                {
                    "user_id": user_id,
                    "actor_id": created_by,
                    "root_import_id": bucket["root_import_id"],
                    "owner_id": bucket.get("owner_id"),
                    "credential_scope": credential_scope,
                },
                ensure_ascii=False,
            ),
        ),
    )
    return {"created": True, "job_id": job_id}


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

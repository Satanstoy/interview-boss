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
_ANY_OWNER = object()
PUBLIC_CONTRIBUTION_QUEUE_SCOPE = "public_contribution"


def has_active_rootless_cluster_batch_job(conn) -> bool:
    """Whether an incremental rootless cluster batch can consume the shared queue."""

    return conn.execute(
        "SELECT 1 FROM jobs WHERE job_type = 'cluster_batch' "
        "AND root_import_id IS NULL "
        "AND status IN ('pending', 'queued', 'running') LIMIT 1"
    ).fetchone() is not None


def has_active_rootless_cluster_job(conn) -> bool:
    """Whether any active rootless batch or rebuild can consume the shared queue."""

    return conn.execute(
        "SELECT 1 FROM jobs WHERE job_type IN ('cluster_batch', 'cluster_rebuild') "
        "AND root_import_id IS NULL "
        "AND status IN ('pending', 'queued', 'running') LIMIT 1"
    ).fetchone() is not None


def enqueue_questions(
    interview_id: int,
    owner_id: int = None,
    question_detail_ids: List[int] | None = None,
    contribution_request_id: int | None = None,
    conn=None,
    root_import_id: str | None = None,
    retry_existing: bool = False,
) -> int:
    """将指定面经明细加入分析队列，返回本次新建的队列记录数。

    Args:
        interview_id: 面经 ID
        owner_id: NULL = 公共队列, user_id = 个人队列（隔离匹配）
        question_detail_ids: 可选的明细白名单；为空时入队整条面经。
        contribution_request_id: 可选的公共化申请追踪 ID。
        root_import_id: 可选的上传根任务（R06：v2 明细已带 import_id 时
            自动回填；真实上传产生的队列行必须写 root，才能被对账补单）。
        retry_existing: 仅用于显式重试已失败的明细；把同一来源已有的 done/failed
            队列行重新置为 pending，普通重复入队仍保持幂等。
    """
    owns_connection = conn is None
    conn = conn or get_db_connection()
    interview = conn.execute(
        "SELECT owner_id, status, deleted_at FROM interview WHERE id = ?",
        (interview_id,),
    ).fetchone()
    if not interview or interview["deleted_at"] is not None:
        raise ValueError("面经不存在或已删除，不能加入分析队列")
    if interview["owner_id"] != owner_id:
        raise ValueError("分析队列作用域与面经归属不一致")
    if owner_id is None and interview["status"] != "approved":
        raise ValueError("公共面经尚未通过审核，不能加入公共分析队列")
    if question_detail_ids is None:
        rows = conn.execute(
            "SELECT id FROM questions_detail WHERE interview_id = ? AND deleted_at IS NULL",
            (interview_id,),
        ).fetchall()
    else:
        ids = [int(item) for item in question_detail_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT id FROM questions_detail WHERE interview_id = ? "
            f"AND id IN ({placeholders}) AND deleted_at IS NULL",
            [interview_id, *ids],
        ).fetchall()
    # R06：v2 明细带 import_id 时自动回填 root（真实上传队列行才有归属可对账）。
    # 旧 schema（mock/轻量测试库）没有该列时跳过，不改变旧行为。
    if root_import_id is None and rows:
        detail_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info('questions_detail')").fetchall()
        }
        if "import_id" in detail_columns:
            linked = conn.execute(
                f"SELECT DISTINCT import_id FROM questions_detail WHERE id IN "
                f"({','.join('?' * len(rows))}) AND import_id IS NOT NULL LIMIT 1",
                [r[0] for r in rows],
            ).fetchone()
            if linked and linked["import_id"]:
                root_import_id = str(linked["import_id"])
    if root_import_id is None and contribution_request_id is not None:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "upload_imports" in tables:
            linked_root = conn.execute(
                "SELECT id FROM upload_imports WHERE contribution_request_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (contribution_request_id,),
            ).fetchone()
            if linked_root:
                root_import_id = str(linked_root["id"])
    count = 0
    queue_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    has_root_column = "root_import_id" in queue_columns
    has_contribution_column = "contribution_request_id" in queue_columns
    detail_ids = [int(row[0]) for row in rows]
    if retry_existing and detail_ids:
        placeholders = ",".join("?" * len(detail_ids))
        owner_clause = "owner_id IS NULL" if owner_id is None else "owner_id = ?"
        retry_params = [interview_id, *detail_ids]
        if owner_id is not None:
            retry_params.append(owner_id)
        contribution_clause = ""
        if contribution_request_id is not None and has_contribution_column:
            contribution_clause = " AND contribution_request_id = ?"
            retry_params.append(contribution_request_id)
        conn.execute(
            "UPDATE analysis_queue SET status = 'pending', processed_at = NULL, "
            "locked_until = NULL WHERE interview_id = ? "
            f"AND question_detail_id IN ({placeholders}) AND {owner_clause} "
            "AND status IN ('done','failed')" + contribution_clause,
            retry_params,
        )
    for r in rows:
        if has_root_column:
            if has_contribution_column:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO analysis_queue "
                    "(interview_id, question_detail_id, status, owner_id, "
                    "contribution_request_id, root_import_id) "
                    "VALUES (?, ?, 'pending', ?, ?, ?)",
                    (interview_id, r[0], owner_id, contribution_request_id, root_import_id),
                )
            else:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO analysis_queue "
                    "(interview_id, question_detail_id, status, owner_id, root_import_id) "
                    "VALUES (?, ?, 'pending', ?, ?)",
                    (interview_id, r[0], owner_id, root_import_id),
                )
        elif has_contribution_column:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO analysis_queue "
                "(interview_id, question_detail_id, status, owner_id, contribution_request_id) "
                "VALUES (?, ?, 'pending', ?, ?)",
                (interview_id, r[0], owner_id, contribution_request_id),
            )
        else:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO analysis_queue "
                "(interview_id, question_detail_id, status, owner_id) VALUES (?, ?, 'pending', ?)",
                (interview_id, r[0], owner_id),
            )
        count += max(0, cursor.rowcount)
        if root_import_id and has_root_column:
            detail_id = int(r[0])
            conn.execute(
                "INSERT INTO upload_stage_results (import_id, stage, unit_key, "
                "input_version, pipeline_version, status) "
                "VALUES (?, 'resolve', ?, 1, 'upload-pipeline-v1', 'pending') "
                "ON CONFLICT(import_id, stage, unit_key, input_version) DO UPDATE SET "
                "status = CASE WHEN upload_stage_results.status IN ('failed','needs_action') "
                "THEN 'pending' ELSE upload_stage_results.status END, "
                "error_code = CASE WHEN upload_stage_results.status IN ('failed','needs_action') "
                "THEN NULL ELSE upload_stage_results.error_code END, "
                "updated_at = CURRENT_TIMESTAMP",
                (root_import_id, f"detail:{detail_id}"),
            )
    if root_import_id:
        from app.services.upload_lifecycle import refresh_completed_upload_roots

        refresh_completed_upload_roots(conn, [root_import_id])
    if owns_connection:
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


def _assert_queue_write_fences(conn, job_fence, scope_fence):
    if job_fence is not None:
        from app.services.job_lifecycle import assert_job_fence

        assert_job_fence(conn, int(job_fence[0]), int(job_fence[1]))
    if scope_fence is not None:
        from app.services.upload_scope_leases import assert_upload_scope_lease

        assert_upload_scope_lease(
            conn,
            scope_fence[0],
            holder_token=scope_fence[1],
            generation=int(scope_fence[2]),
        )


def _recover_stuck_processing(
    *, job_fence=None, scope_fence=None, root_import_id: str | None = None
):
    conn = get_db_connection()
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _assert_queue_write_fences(conn, job_fence, scope_fence)
        # contracts §2.5：processing 行按租约回收（locked_until 过期）；
        # 兼容旧数据：locked_until IS NULL 的“老式 processing 行”按 created_at
        # 超时兜底回收（不无限悬挂）。created_at 早但租约仍有效的行绝不误伤。
        queue_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
        }
        if root_import_id is not None and "root_import_id" not in queue_columns:
            if owns_transaction:
                conn.commit()
            return
        returning = (
            "root_import_id, question_detail_id"
            if "root_import_id" in queue_columns
            else "NULL AS root_import_id, question_detail_id"
        )
        root_filter = " AND root_import_id = ?" if root_import_id is not None else ""
        params = []
        if root_import_id is not None:
            params.append(str(root_import_id))
        recovered = conn.execute(
            "UPDATE analysis_queue SET status = 'pending', locked_until = NULL "
            "WHERE status = 'processing'" + root_filter + " AND ("
            "  (locked_until IS NOT NULL AND locked_until < CURRENT_TIMESTAMP) "
            "  OR (locked_until IS NULL AND created_at < datetime('now', ?))"
            f") RETURNING {returning}",
            [*params, f"-{STUCK_PROCESSING_THRESHOLD_MINUTES} minutes"],
        ).fetchall()
        for row in recovered:
            if row["root_import_id"]:
                conn.execute(
                    "UPDATE upload_stage_results SET status = 'pending', "
                    "updated_at = CURRENT_TIMESTAMP WHERE import_id = ? "
                    "AND stage IN ('cluster','resolve') AND unit_key = ? AND status = 'running'",
                    (row["root_import_id"], f"detail:{row['question_detail_id']}"),
                )
        conn.commit()
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


def should_trigger_clustering(batch_size: int = BATCH_SIZE) -> bool:
    _recover_stuck_processing()
    pending = get_pending_count()
    if pending >= batch_size:
        return True
    processing = get_processing_count()
    return processing == 0 and pending > 0


def dequeue_batch(
    batch_size: int = BATCH_SIZE,
    owner_id=_ANY_OWNER,
    root_import_id: str | None = None,
    contribution_only: bool = False,
    job_fence: tuple[int, int] | None = None,
    scope_fence: tuple[str, str, int] | None = None,
) -> List[Dict]:
    """原子取出一批 pending 任务并标记为 processing（防并发重复取出）。

    Returns items from a single owner_id bucket (NULL for public, or a specific
    user_id for personal). This guarantees ``cluster_batch`` never mixes
    personal and public questions in the same batch.
    """
    _recover_stuck_processing(
        job_fence=job_fence,
        scope_fence=scope_fence,
        root_import_id=root_import_id,
    )
    conn = get_db_connection()
    cursor = conn.cursor()
    queue_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    contribution_returning = (
        "contribution_request_id"
        if "contribution_request_id" in queue_columns
        else "NULL AS contribution_request_id"
    )
    root_returning = (
        "root_import_id" if "root_import_id" in queue_columns else "NULL AS root_import_id"
    )
    if contribution_only and "contribution_request_id" not in queue_columns:
        return []
    contribution_only_filter = (
        " AND aq.owner_id IS NULL AND aq.contribution_request_id IS NOT NULL"
        if contribution_only
        else ""
    )
    failed_contribution_filter = ""
    if "contribution_request_id" in queue_columns:
        failed_contribution_filter = (
            " AND NOT (aq.contribution_request_id IS NOT NULL AND EXISTS ("
            "SELECT 1 FROM public_contribution_items pci "
            "WHERE pci.request_id = aq.contribution_request_id "
            "AND pci.public_detail_id = aq.question_detail_id "
            "AND pci.status = 'failed'))"
        )
    if root_import_id is not None and "root_import_id" not in queue_columns:
        return []
    root_filter = ""
    root_params = []
    if "root_import_id" in queue_columns:
        if root_import_id is None:
            root_filter = " AND aq.root_import_id IS NULL"
        else:
            root_filter = " AND aq.root_import_id = ?"
            root_params.append(str(root_import_id))
    cursor.execute("BEGIN IMMEDIATE")
    try:
        _assert_queue_write_fences(conn, job_fence, scope_fence)
        # Pick the owner_id bucket with the most pending items.
        # NULL owner_id (public) gets priority when tied.
        bucket_sql = (
            "SELECT aq.owner_id, COUNT(*) as cnt FROM analysis_queue aq "
            "JOIN interview i ON i.id = aq.interview_id "
            "WHERE aq.status = 'pending' AND i.deleted_at IS NULL "
            "AND i.status = 'approved' "
            "AND (i.owner_id = aq.owner_id OR (i.owner_id IS NULL AND aq.owner_id IS NULL))"
        )
        bucket_params = []
        if owner_id is not _ANY_OWNER:
            bucket_sql += " AND (aq.owner_id = ? OR (aq.owner_id IS NULL AND ? IS NULL))"
            bucket_params.extend([owner_id, owner_id])
        bucket_sql += root_filter
        bucket_sql += contribution_only_filter
        bucket_sql += failed_contribution_filter
        bucket_params.extend(root_params)
        bucket_sql += " GROUP BY aq.owner_id ORDER BY cnt DESC LIMIT 1"
        bucket = cursor.execute(bucket_sql, bucket_params).fetchone()
        if not bucket:
            conn.commit()
            return []
        target_owner = bucket["owner_id"]

        dequeue_params = [
            f"+{STUCK_PROCESSING_THRESHOLD_MINUTES} minutes",
            target_owner,
            target_owner,
        ]
        update_root_filter = root_filter
        if root_import_id is not None:
            dequeue_params.append(str(root_import_id))
        dequeue_params.append(batch_size)
        rows = cursor.execute(
            "UPDATE analysis_queue SET status = 'processing', processed_at = CURRENT_TIMESTAMP, "
            "locked_until = datetime('now', ?) "
            "WHERE id IN ("
            "  SELECT aq.id FROM analysis_queue aq "
            "  JOIN interview i ON aq.interview_id = i.id "
            "  JOIN questions_detail qd ON aq.question_detail_id = qd.id "
            "  WHERE aq.status = 'pending' AND i.deleted_at IS NULL "
            "  AND i.status = 'approved' AND qd.deleted_at IS NULL "
            "  AND (i.owner_id = aq.owner_id OR (i.owner_id IS NULL AND aq.owner_id IS NULL)) "
            "  AND (aq.owner_id = ? OR (aq.owner_id IS NULL AND ? IS NULL)) "
            + update_root_filter + contribution_only_filter + failed_contribution_filter + " "
            "  ORDER BY aq.id LIMIT ?"
            ") RETURNING id as queue_id, question_detail_id as qd_id, owner_id, "
            + contribution_returning
            + ", "
            + root_returning,
            dequeue_params,
        ).fetchall()
        for row in rows:
            if row["root_import_id"]:
                cursor.execute(
                    "UPDATE upload_stage_results SET status = 'running', "
                    "updated_at = CURRENT_TIMESTAMP WHERE import_id = ? "
                    "AND stage IN ('cluster','resolve') AND unit_key = ? AND status = 'pending'",
                    (row["root_import_id"], f"detail:{row['qd_id']}"),
                )
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
        f"SELECT id, interview_id, question, cat1, cat2, tags, diff_tag, url, company, round, job_position "
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
            d["contribution_request_id"] = r["contribution_request_id"]
            d["root_import_id"] = r["root_import_id"]
            result.append(d)
    return result


def mark_batch_done(
    queue_ids: List[int],
    *,
    job_fence: tuple[int, int] | None = None,
    scope_fence: tuple[str, str, int] | None = None,
):
    if not queue_ids:
        return
    conn = get_db_connection()
    placeholders = ",".join("?" * len(queue_ids))
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _assert_queue_write_fences(conn, job_fence, scope_fence)
        conn.execute(
            f"UPDATE analysis_queue SET status = 'done', processed_at = CURRENT_TIMESTAMP, "
            f"locked_until = NULL "
            f"WHERE id IN ({placeholders}) AND status != 'cancelled'",
            queue_ids,
        )
        conn.commit()
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


def mark_batch_failed(
    queue_ids: List[int],
    *,
    job_fence: tuple[int, int] | None = None,
    scope_fence: tuple[str, str, int] | None = None,
    terminal: bool = False,
):
    if not queue_ids:
        return
    conn = get_db_connection()
    placeholders = ",".join("?" * len(queue_ids))
    owns_transaction = not conn.in_transaction
    if owns_transaction:
        conn.execute("BEGIN IMMEDIATE")
    try:
        _assert_queue_write_fences(conn, job_fence, scope_fence)
        queue_columns = {
            row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
        }
        roots = (
            conn.execute(
                f"SELECT root_import_id, question_detail_id FROM analysis_queue "
                f"WHERE id IN ({placeholders})",
                queue_ids,
            ).fetchall()
            if "root_import_id" in queue_columns
            else []
        )
        failed_status = "failed" if terminal else "pending"
        processed_at = "CURRENT_TIMESTAMP" if terminal else "NULL"
        conn.execute(
            f"UPDATE analysis_queue SET status = ?, processed_at = {processed_at}, "
            f"locked_until = NULL WHERE id IN ({placeholders}) AND status != 'cancelled'",
            (failed_status, *queue_ids),
        )
        for row in roots:
            if row["root_import_id"]:
                conn.execute(
                    "UPDATE upload_stage_results SET status = 'pending', "
                    "updated_at = CURRENT_TIMESTAMP WHERE import_id = ? "
                    "AND stage IN ('cluster','resolve') AND unit_key = ? AND status = 'running'",
                    (row["root_import_id"], f"detail:{row['question_detail_id']}"),
                )
        conn.commit()
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise


# ──────────────────────────────────────────────────────────────
# 聚类攒批：延迟窗口由 jobs.available_at 持久化，ARQ 只执行 job。
# ──────────────────────────────────────────────────────────────

# 攒批延迟窗口（秒）：pending < BATCH_SIZE 时延迟再聚，给连续导入留合并窗口。
# 可用环境变量 CLUSTER_DELAY_SECONDS 覆盖。
CLUSTER_DELAY_SECONDS = int(os.environ.get("CLUSTER_DELAY_SECONDS", "300"))

async def _run_cluster_batch_in_background(
    user_id: int = None,
    root_import_id: str | None = None,
    *,
    queue_scope: str | None = None,
) -> bool:
    """创建一个持久化攒批 Job，返回是否新建了任务。

    pending 不足一批时使用 ``available_at`` 保留攒批窗口；达到阈值则
    立即尝试入队。即使 Redis 或 Web 进程随后不可用，dispatcher 仍会
    根据 jobs 表接管 pending 任务。
    """
    if root_import_id:
        def _create_root_jobs():
            conn = get_db_connection()
            try:
                from app.services.upload_queue import collect_pending_buckets, ensure_bucket_job

                created = []
                for bucket in collect_pending_buckets(conn):
                    if str(bucket["root_import_id"]) != str(root_import_id):
                        continue
                    result = ensure_bucket_job(conn, bucket=bucket, created_by=user_id)
                    if result.get("job_id"):
                        state = conn.execute(
                            "SELECT status FROM jobs WHERE id = ?", (result["job_id"],)
                        ).fetchone()
                        if state and state["status"] == "pending":
                            created.append(int(result["job_id"]))
                conn.commit()
                return created
            except Exception:
                conn.rollback()
                raise

        job_ids = _create_root_jobs()
        if not job_ids:
            return False
        from app.services.job_lifecycle import mark_job_dispatched
        from app.worker import enqueue_cluster_batch_job

        scheduled = False
        for job_id in job_ids:
            try:
                arq_job = await enqueue_cluster_batch_job(job_id)
                arq_job_id = getattr(arq_job, "job_id", None)
                if not arq_job_id:
                    raise RuntimeError("ARQ 未返回 job_id")
                conn = get_db_connection()
                if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                    raise RuntimeError(f"聚类任务不可再投递: job_id={job_id}")
                conn.commit()
                scheduled = True
            except Exception as exc:
                logger.warning(
                    "root 聚类任务保留在 outbox 等待 dispatcher: root=%s job=%s error=%s",
                    root_import_id,
                    job_id,
                    exc,
                )
        return scheduled or bool(job_ids)

    if queue_scope not in (None, PUBLIC_CONTRIBUTION_QUEUE_SCOPE):
        raise ValueError(f"不支持的 rootless cluster queue scope: {queue_scope!r}")

    def _create():
        conn = get_db_connection()
        try:
            _recover_stuck_processing()
            # Generic legacy jobs can dequeue public contribution rows too, so
            # every rootless cluster job shares one scheduling lock regardless
            # of payload version/scope. BEGIN IMMEDIATE makes this check and
            # insert atomic across API and worker processes.
            conn.execute("BEGIN IMMEDIATE")
            if has_active_rootless_cluster_job(conn):
                conn.rollback()
                return None, None

            if queue_scope == PUBLIC_CONTRIBUTION_QUEUE_SCOPE:
                pending = conn.execute(
                    "SELECT COUNT(*) AS c FROM analysis_queue aq "
                    "JOIN interview i ON i.id = aq.interview_id "
                    "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
                    "JOIN public_contribution_items pci "
                    "ON pci.request_id = aq.contribution_request_id "
                    "AND pci.public_detail_id = aq.question_detail_id "
                    "WHERE aq.status = 'pending' AND aq.root_import_id IS NULL "
                    "AND aq.owner_id IS NULL AND aq.contribution_request_id IS NOT NULL "
                    "AND pci.status IN ('queued', 'approved_for_processing', 'processing') "
                    "AND i.status = 'approved' AND i.deleted_at IS NULL "
                    "AND qd.deleted_at IS NULL"
                ).fetchone()["c"]
            else:
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
            payload = {"user_id": user_id}
            if queue_scope:
                payload["queue_scope"] = queue_scope
            conn.execute(
                "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                (job_id, json.dumps(payload, ensure_ascii=False)),
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

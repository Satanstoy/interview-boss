"""Cluster and interview-processing ARQ task handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from app.services.worker_observability import record_worker_heartbeat_async

logger = logging.getLogger("interview-boss")

async def recompute_embedding_task(ctx, job_id: int):
    """ARQ: 全量 embedding 重算（模型更换后自动触发）。"""
    from app.services.embedding_recompute import run_recompute

    await run_recompute(job_id)


async def cluster_review_task(ctx, task_id: str):
    """ARQ worker：执行一个带 cluster_version 校验的 AI 质量评估。"""
    from app.services.cluster_review_lifecycle import run_cluster_review_task

    return await run_cluster_review_task(task_id)


async def quality_review_scan_task(ctx, job_id: int):
    """ARQ worker：执行管理员触发的误合并 + 漏合并全量扫描。"""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        QUALITY_REVIEW_SCAN_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=QUALITY_REVIEW_SCAN_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            return dict(task), json.loads(payload_row["payload"]) if payload_row else {}

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("聚合质量扫描已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    task, payload = claimed

    def _progress(current: int, message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=current,
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        from app.services.clustering_maintenance import generate_quality_issues
        from app.services.unmerged_quality import generate_unmerged_quality_issues

        await asyncio.to_thread(_progress, 0, "正在分析聚类内误合并")
        mismerge = await generate_quality_issues(
            user_id=payload.get("user_id"),
            limit=payload.get("mismerge_limit", 1000),
            review_task_id=str(job_id),
            trigger_reason="manual_full_scan",
        )
        await asyncio.to_thread(_progress, 1, "正在分析孤岛题漏合并")
        unmerged = await generate_unmerged_quality_issues(
            user_id=payload.get("user_id"),
            limit=payload.get("singleton_limit", 1000),
            candidate_limit=payload.get("candidate_limit", 3),
            similarity_threshold=payload.get("similarity_threshold", 0.30),
            review_task_id=str(job_id),
            trigger_reason="manual_full_scan",
        )
        from app.services.cluster_review_lifecycle import sync_review_state_after_scan

        def _sync_review_state():
            with get_db_connection() as conn:
                state = sync_review_state_after_scan(
                    conn,
                    (mismerge.get("scanned_cluster_ids") or [])
                    + (unmerged.get("scanned_singleton_ids") or []),
                    trigger_reason="manual_full_scan",
                )
                conn.commit()
                return state

        state = await asyncio.to_thread(_sync_review_state)
        result = {
            "status": "completed",
            "mismerge": mismerge,
            "unmerged": unmerged,
            "review_state": state,
        }
        _complete(result)
        return {"job_id": job_id, **result}
    except Exception as exc:
        outcome = _fail(str(exc)[:500])
        logger.exception("聚合质量扫描失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def startup(ctx):
    """Worker 启动时初始化"""
    from app.db.connection import init_db
    from app.core.config import _reload_from_db
    from app.services.embedding_service import reload_embedding_config

    init_db()
    await record_worker_heartbeat_async(
        "arq-worker",
        status="online",
        queue_name=os.environ.get("ARQ_QUEUE_NAME", "arq:default"),
        metadata={"pid": os.getpid()},
    )
    _reload_from_db()
    reload_embedding_config()
    try:
        from redis.asyncio import from_url
        from app.core.cache import set_cache_client
        from app.core.config import REDIS_CACHE_URL

        cache = from_url(REDIS_CACHE_URL, decode_responses=True)
        await cache.ping()
        set_cache_client(cache)
        ctx["redis_cache"] = cache
    except Exception as exc:
        logger.warning("ARQ Worker Redis cache 初始化失败: %s", exc)
    logger.info("ARQ Worker 已启动")


async def shutdown(ctx):
    """Worker 关闭时清理"""
    await record_worker_heartbeat_async(
        "arq-worker",
        status="offline",
        queue_name=os.environ.get("ARQ_QUEUE_NAME", "arq:default"),
        metadata={"pid": os.getpid()},
    )
    from app.core.cache import close_cache_client

    await close_cache_client()
    logger.info("ARQ Worker 已关闭")


async def _schedule_cluster_answer_jobs(
    parent_job_id: int,
    question_bank_ids: list[int],
    *,
    owner_id: int | None,
    actor_id: int | None,
) -> list[int]:
    """Create durable answer jobs with the final question-bank scope.

    The clustering worker may be invoked by an admin on behalf of a user.
    ``owner_id`` is therefore the only source of truth for model/search scope:
    public rows use the global/public configuration, personal rows use the
    owning user's configuration.
    """
    ids = sorted({int(item) for item in (question_bank_ids or [])})
    if not ids:
        return []

    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import create_answer_generation_jobs

    llm_scope = "global" if owner_id is None else "user"
    search_scope = "public" if owner_id is None else "user"
    answer_user_id = owner_id if owner_id is not None else actor_id

    def _create():
        placeholders = ",".join("?" * len(ids))
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, question FROM question_bank "
                f"WHERE id IN ({placeholders}) AND deleted_at IS NULL "
                "AND question IS NOT NULL AND question != '' "
                "AND owner_id IS ? AND (ai_answer IS NULL OR ai_answer = '')",
                [*ids, owner_id],
            ).fetchall()
            tasks = [(int(row["id"]), row["question"]) for row in rows]
            job_ids = create_answer_generation_jobs(
                conn,
                parent_job_id,
                tasks,
                answer_user_id,
                llm_scope=llm_scope,
                search_scope=search_scope,
            )
            conn.commit()
            return job_ids

    try:
        return await asyncio.to_thread(_create)
    except Exception:
        # Answer enrichment is secondary to the durable clustering result.
        # The answer job dispatcher can be retried independently; never roll
        # back a successfully written public/personal cluster here.
        logger.exception(
            "聚类完成但答案任务创建失败: parent_job_id=%s, owner_id=%s",
            parent_job_id,
            owner_id,
        )
        return []


async def cluster_batch_task(ctx, job_id: int):
    """ARQ task: claim and process one database-owned clustering batch."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        CLUSTER_BATCH_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.pipeline import (
        BATCH_SIZE,
        cluster_batch,
        dequeue_batch,
        mark_batch_done,
        mark_batch_failed,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=CLUSTER_BATCH_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            return payload

    payload = await asyncio.to_thread(_claim_and_load)
    if payload is None:
        logger.info("聚类攒批任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(conn, job_id, worker_id, result=json.dumps(result, ensure_ascii=False))
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    batch = []
    try:
        batch = dequeue_batch(BATCH_SIZE)
        if not batch:
            result = {"status": "empty", "new_count": 0}
            _complete(result)
            return {"job_id": job_id, **result}

        cluster_result = await cluster_batch(
            batch, user_id=payload.get("user_id"), return_new_ids=True
        )
        if isinstance(cluster_result, dict):
            new_count = int(cluster_result.get("count", 0))
            new_qb_ids = cluster_result.get("ids", [])
        else:  # compatibility with lightweight test/legacy implementations
            new_count = int(cluster_result or 0)
            new_qb_ids = []
        queue_ids = [item["queue_id"] for item in batch]
        mark_batch_done(queue_ids)
        from app.services.public_contributions import mark_public_contribution_queue_done

        with get_db_connection() as connection:
            mark_public_contribution_queue_done(connection, queue_ids)
        await _schedule_cluster_answer_jobs(
            job_id,
            new_qb_ids,
            owner_id=batch[0].get("owner_id"),
            actor_id=payload.get("user_id"),
        )
        result = {"status": "done", "new_count": new_count, "processed": len(batch)}
        _complete(result)
        return {"job_id": job_id, **result}
    except Exception as exc:
        queue_ids = [item["queue_id"] for item in batch]
        mark_batch_failed(queue_ids)
        from app.services.public_contributions import mark_public_contribution_queue_failed

        with get_db_connection() as connection:
            mark_public_contribution_queue_failed(connection, queue_ids, str(exc))
        outcome = _fail(str(exc)[:500])
        logger.exception("聚类攒批任务失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def cluster_rebuild_task(ctx, job_id: int):
    """ARQ task: durably process every queued question for a full rebuild."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        CLUSTER_REBUILD_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.pipeline import (
        BATCH_SIZE,
        cluster_batch,
        dequeue_batch,
        mark_batch_done,
        mark_batch_failed,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=CLUSTER_REBUILD_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            return payload, int(task["progress_total"] or 1)

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("全量聚类重建任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    payload, progress_total = claimed
    processed = 0
    total_new = 0
    total_batches = 0
    batch = []

    def _touch(message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=processed,
                progress_total=max(progress_total, processed, 1),
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        while True:
            batch = dequeue_batch(BATCH_SIZE, owner_id=None)
            if not batch:
                result = {
                    "status": "done",
                    "batches": total_batches,
                    "new_qb_count": total_new,
                    "processed": processed,
                }
                _complete(result)
                return {"job_id": job_id, **result}

            total_batches += 1
            cluster_result = await cluster_batch(
                batch,
                user_id=payload.get("user_id"),
                skip_clean=True,
                return_new_ids=True,
            )
            if isinstance(cluster_result, dict):
                new_count = int(cluster_result.get("count", 0))
                new_qb_ids = cluster_result.get("ids", [])
            else:
                new_count = int(cluster_result or 0)
                new_qb_ids = []
            queue_ids = [item["queue_id"] for item in batch]
            mark_batch_done(queue_ids)
            from app.services.public_contributions import mark_public_contribution_queue_done

            with get_db_connection() as connection:
                mark_public_contribution_queue_done(connection, queue_ids)
            await _schedule_cluster_answer_jobs(
                job_id,
                new_qb_ids,
                owner_id=batch[0].get("owner_id"),
                actor_id=payload.get("user_id"),
            )
            processed += len(batch)
            total_new += new_count
            _touch(f"已完成 {processed} 道题，处理 {total_batches} 个批次")
            await asyncio.sleep(0.5)
    except Exception as exc:
        if batch:
            mark_batch_failed([item["queue_id"] for item in batch])
            from app.services.public_contributions import mark_public_contribution_queue_failed

            with get_db_connection() as connection:
                mark_public_contribution_queue_failed(
                    connection, [item["queue_id"] for item in batch], str(exc)
                )
        outcome = _fail(str(exc)[:500])
        logger.exception("全量聚类重建任务失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def interview_reprocess_task(ctx, job_id: int):
    """ARQ task: tag one interview, enqueue its questions and open clustering."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        INTERVIEW_REPROCESS_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.pipeline import (
        _run_cluster_batch_in_background,
        enqueue_questions,
        tag_interview,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=INTERVIEW_REPROCESS_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            interview = conn.execute(
                "SELECT id, url, company, round, questions_list, job_position "
                "FROM interview WHERE id = ?",
                (payload.get("interview_id"),),
            ).fetchone()
            conn.commit()
            return payload, dict(interview) if interview else None

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("面经重分析任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    payload, interview = claimed

    def _set_analysis_status(status: str):
        with get_db_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(interview)").fetchall()}
            if "analysis_status" in columns:
                conn.execute(
                    "UPDATE interview SET analysis_status = ?, "
                    "analysis_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, payload.get("interview_id")),
                )
                conn.commit()

    def _touch(message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=0,
                progress_total=1,
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        if not interview:
            raise ValueError("未找到待重分析的面经")
        questions_list = str(interview.get("questions_list") or "")
        if not questions_list.strip():
            raise ValueError("该面经没有可分析的题目清单")

        _set_analysis_status("processing")
        _touch("正在调用 AI 标注题目")
        user_id = payload.get("user_id")
        tagged_rows = await tag_interview(
            interview.get("url") or f"internal://{interview['id']}",
            interview.get("company") or "未提供",
            interview.get("round") or "未提供",
            questions_list,
            job_position=interview.get("job_position") or "",
            user_id=user_id,
            interview_id=interview["id"],
        )
        enqueue_questions(interview["id"])
        scheduled = await _run_cluster_batch_in_background(user_id=user_id)

        details = [
            {
                "question": row[3],
                "cat1": row[4],
                "cat2": row[5],
                "tags": row[6],
                "difficulty": row[7],
            }
            for row in tagged_rows
        ]
        result = {
            "interview_id": interview["id"],
            "tagged_count": len(tagged_rows),
            "details": details,
            "cluster_pending": True,
            "cluster_scheduled": scheduled,
        }
        _set_analysis_status("completed")
        _complete(result)
        return {"job_id": job_id, "status": "completed", **result}
    except Exception as exc:
        _set_analysis_status("failed")
        outcome = _fail(str(exc)[:500])
        logger.exception("面经重分析任务失败: job_id=%s", job_id)
        return {"job_id": job_id, "status": outcome["status"]}


async def refresh_interview_distribution_task(ctx, scope: str, job_position: str):
    """Recompute one distribution hierarchy after its facts were marked stale."""
    from app.db.connection import get_db_connection
    from app.services.interview_distribution import refresh_distribution_scope

    conn = get_db_connection()
    try:
        result = refresh_distribution_scope(conn, scope, job_position)
        conn.commit()
        return {"status": "completed", **result}
    except Exception:
        conn.rollback()
        raise

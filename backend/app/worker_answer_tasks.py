"""Answer and recitation ARQ handlers; worker retains its public task facade."""

import asyncio
import json
import logging

logger = logging.getLogger("interview-boss")


def _normalize_error_code(error):
    from app.services.upload_retry_budget import normalize_upload_error_code

    return normalize_upload_error_code(error)


async def _refresh_answer_batch_parent(parent_job_id: int):
    """Finalize a batch parent after one child answer job changes state."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import ANSWER_BATCH_JOB_TYPE

    def _refresh():
        with get_db_connection() as conn:
            parent = conn.execute(
                "SELECT id FROM jobs WHERE id = ? AND job_type = ?",
                (parent_job_id, ANSWER_BATCH_JOB_TYPE),
            ).fetchone()
            if not parent:
                return
            counts = conn.execute(
                "SELECT "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
                "COUNT(*) AS total "
                "FROM jobs WHERE parent_job_id = ?",
                (parent_job_id,),
            ).fetchone()
            completed = int(counts["completed"] or 0)
            failed = int(counts["failed"] or 0)
            total = int(counts["total"] or 0)
            if total and completed + failed == total:
                status = "failed" if failed else "completed"
                result = json.dumps(
                    {"generated": completed, "failed": failed, "total": total},
                    ensure_ascii=False,
                )
                conn.execute(
                    "UPDATE jobs SET status = ?, progress_current = ?, progress_total = ?, "
                    "result = ?, completed_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status NOT IN ('completed', 'failed')",
                    (
                        status,
                        completed + failed,
                        total,
                        result,
                        parent_job_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status IN ('pending', 'running')",
                    (completed + failed, total, parent_job_id),
                )
            conn.commit()

    await asyncio.to_thread(_refresh)


async def _generate_answer_job(ctx, job_id: int):
    """ARQ task: generate one answer with durable claim/retry semantics."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        ANSWER_GENERATION_JOB_TYPE,
        JobFenceError,
        claim_job,
        claim_job_with_generation,
        complete_job,
        default_worker_id,
        fail_job,
        heartbeat_job,
    )

    worker_id = default_worker_id()

    def _sync_upload_root(conn, status, *, error_code=None, result_json=None):
        from app.services.job_lifecycle import update_upload_answer_stage
        from app.services.upload_lifecycle import refresh_completed_upload_roots

        root_import_id = update_upload_answer_stage(
            conn,
            job_id,
            status,
            error_code=error_code,
            result_json=result_json,
        )
        if root_import_id:
            refresh_completed_upload_roots(conn, [root_import_id])
        return root_import_id

    def _claim_and_load():
        with get_db_connection() as conn:
            candidate = conn.execute(
                "SELECT root_import_id FROM jobs WHERE id = ? AND job_type = ?",
                (job_id, ANSWER_GENERATION_JOB_TYPE),
            ).fetchone()
            if candidate and candidate["root_import_id"]:
                task = claim_job_with_generation(
                    conn,
                    job_id,
                    worker_id=worker_id,
                    job_type=ANSWER_GENERATION_JOB_TYPE,
                    lease_seconds=120,
                )
            else:
                task = claim_job(
                    conn,
                    job_id,
                    worker_id,
                    job_type=ANSWER_GENERATION_JOB_TYPE,
                )
            if not task:
                return None, None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            if payload_row:
                _sync_upload_root(conn, "running")
            conn.commit()
            return dict(task), json.loads(payload_row["payload"]) if payload_row else None

    claimed, payload = await asyncio.to_thread(_claim_and_load)
    if not claimed:
        logger.info("答案任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    heartbeat_stop = asyncio.Event()
    heartbeat_lost = asyncio.Event()
    lease_heartbeat_task = None
    if claimed.get("root_import_id"):
        generation = int(claimed["lease_generation"])

        def _heartbeat_answer_job():
            with get_db_connection() as conn:
                alive = heartbeat_job(conn, job_id, generation, lease_seconds=120)
                conn.commit()
                return alive

        async def _renew_answer_job():
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
                    continue
                except asyncio.TimeoutError:
                    pass
                if not await asyncio.to_thread(_heartbeat_answer_job):
                    heartbeat_lost.set()
                    return

        lease_heartbeat_task = asyncio.create_task(_renew_answer_job())

    async def _stop_answer_heartbeat():
        heartbeat_stop.set()
        if lease_heartbeat_task is not None:
            lease_heartbeat_task.cancel()
            await asyncio.gather(lease_heartbeat_task, return_exceptions=True)

    def _finish(result=None):
        with get_db_connection() as conn:
            if claimed.get("root_import_id"):
                conn.execute("BEGIN IMMEDIATE")
                from app.services.job_lifecycle import assert_job_fence

                assert_job_fence(conn, job_id, int(claimed["lease_generation"]))
                _sync_upload_root(conn, "succeeded", result_json=result)
            completed = complete_job(
                conn,
                job_id,
                worker_id,
                result=result,
                lease_generation=(
                    int(claimed["lease_generation"])
                    if claimed.get("root_import_id")
                    else None
                ),
            )
            if completed:
                if not claimed.get("root_import_id"):
                    _sync_upload_root(conn, "succeeded", result_json=result)
            conn.commit()
            return completed

    def _fail(error: str, terminal: bool = False):
        with get_db_connection() as conn:
            if claimed.get("root_import_id"):
                conn.execute("BEGIN IMMEDIATE")
                from app.services.job_lifecycle import assert_job_fence

                assert_job_fence(conn, job_id, int(claimed["lease_generation"]))
            outcome = fail_job(
                conn,
                job_id,
                worker_id,
                error,
                max_attempts=0 if terminal else 3,
                lease_generation=(
                    int(claimed["lease_generation"])
                    if claimed.get("root_import_id")
                    else None
                ),
            )
            if outcome["status"] != "stale":
                error_code = _normalize_error_code(error)
                _sync_upload_root(
                    conn,
                    "failed" if outcome["status"] == "failed" else "pending",
                    error_code=error_code,
                )
            conn.commit()
            return outcome

    if not payload:
        try:
            outcome = _fail("答案任务数据不存在", terminal=True)
        except JobFenceError:
            outcome = {"status": "stale"}
        await _stop_answer_heartbeat()
        return {"status": outcome["status"], "job_id": job_id}

    try:
        from app.services.submit_service import background_generate_answer
        root_import_id = claimed.get("root_import_id")
        if root_import_id:
            from app.services.upload_llm_accounting import upload_llm_context

            with upload_llm_context(
                root_import_id=str(root_import_id),
                stage="answer",
                unit_key=f"question:{int(payload['question_id'])}",
                credential_scope=payload.get("llm_scope", "user"),
                user_id=payload.get("user_id"),
            ):
                answer_result = await background_generate_answer(
                    int(payload["question_id"]),
                    payload["question_text"],
                    payload.get("user_id"),
                    raise_on_error=True,
                    skip_search=bool(payload.get("skip_search", False)),
                    llm_scope=payload.get("llm_scope", "user"),
                    search_scope=payload.get("search_scope", "user"),
                    job_fence=(
                        job_id,
                        int(claimed["lease_generation"]),
                    ),
                )
        else:
            answer_result = await background_generate_answer(
                int(payload["question_id"]),
                payload["question_text"],
                payload.get("user_id"),
                raise_on_error=True,
                skip_search=bool(payload.get("skip_search", False)),
                llm_scope=payload.get("llm_scope", "user"),
                search_scope=payload.get("search_scope", "user"),
            )
        if heartbeat_lost.is_set():
            raise JobFenceError(
                "答案生成期间job lease心跳失败",
                job_id=job_id,
                generation=claimed.get("lease_generation"),
            )
        completed = _finish(
            json.dumps(
                {
                    "question_id": int(payload["question_id"]),
                    **(answer_result or {}),
                },
                ensure_ascii=False,
            )
        )
        if not completed:
            raise JobFenceError(
                "答案任务租约失效，不能完成任务",
                job_id=job_id,
                generation=claimed.get("lease_generation"),
            )
        await _stop_answer_heartbeat()
        if payload.get("parent_job_id"):
            await _refresh_answer_batch_parent(int(payload["parent_job_id"]))
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.exception("答案生成任务失败: job_id=%s", job_id)
        try:
            outcome = _fail(str(exc)[:500])
        except JobFenceError:
            outcome = {"status": "stale"}
        await _stop_answer_heartbeat()
        if payload.get("parent_job_id") and outcome["status"] != "stale":
            await _refresh_answer_batch_parent(int(payload["parent_job_id"]))
        return {"status": outcome["status"], "job_id": job_id}


async def generate_recitation_task(ctx, job_id: int):
    """ARQ task: generate and persist one user's recitation answer."""
    from app.db.connection import get_db_connection, run_db
    from app.db.queries import get_user_job_position
    from app.services.answer_enrichment import (
        prepare_recitation_prompt,
    )
    from app.services.job_lifecycle import (
        RECITATION_GENERATION_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.llm import _call_llm_with_retry
    from app.services.resume_service import get_resume_text

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=RECITATION_GENERATION_JOB_TYPE,
            )
            if not task:
                return None, None, None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            question = (
                conn.execute(
                    "SELECT question, ai_answer FROM question_bank WHERE id = ?",
                    (int(json.loads(payload_row["payload"])["question_id"]),),
                ).fetchone()
                if payload_row
                else None
            )
            conn.commit()
            return (
                dict(task),
                json.loads(payload_row["payload"]) if payload_row else None,
                dict(question) if question else None,
            )

    claimed, payload, question = await asyncio.to_thread(_claim_and_load)
    if not claimed:
        logger.info("背诵稿任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _finish(result=None):
        with get_db_connection() as conn:
            complete_job(conn, job_id, worker_id, result=result)
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    if not payload or not question or not question["ai_answer"]:
        _fail("背诵稿任务数据不存在或公共答案为空")
        return {"status": "failed", "job_id": job_id}

    try:
        user_id = int(payload["user_id"])
        _, job_position = get_user_job_position(user_id)
        resume_text = get_resume_text(user_id)
        prompt, search_sources = await prepare_recitation_prompt(
            question=question["question"],
            reference_answer=question["ai_answer"],
            job_position=job_position or "",
            resume_text=resume_text,
            user_id=user_id,
            skip_search=bool(payload.get("skip_search", False)),
        )
        answer = await _call_llm_with_retry(prompt, user_id=user_id)

        def _upsert():
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO user_question_view "
                    "(user_id, question_bank_id, user_answer, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET "
                    "user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                    (user_id, int(payload["question_id"]), answer, answer),
                )
                conn.commit()

        await run_db(_upsert)
        from app.core.cache import invalidate_master_bank_cache

        await invalidate_master_bank_cache()
        _finish(
            json.dumps(
                {
                    "question_id": int(payload["question_id"]),
                    "answer": answer,
                    "search_sources": search_sources,
                },
                ensure_ascii=False,
            )
        )
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.exception("背诵稿任务失败: job_id=%s", job_id)
        outcome = _fail(str(exc)[:500])
        return {"status": outcome["status"], "job_id": job_id}

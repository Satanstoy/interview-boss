import json
import logging
import asyncio
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user, get_admin_user
from app.core.cache import invalidate_master_bank_cache
from app.db.connection import get_db_connection, run_db
from app.models.schemas import BatchGenerateAnswersRequest
from app.routers.questions import _build_bank_where_clause
from app.services.llm import _call_llm_with_retry
from app.services.llm_quota import check_and_record
from app.services.answer_enrichment import (
    refine_answer,
    sources_json,
    prepare_answer_prompt,
    prepare_recitation_prompt,
)

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/master-bank")

# 批量生成可能包含联网搜索、答案生成和质量修订，多次外部调用期间不能让
# SSE 长时间没有任何字节；单题超时后继续处理其他题，确保流最终能收尾。
_BATCH_SSE_HEARTBEAT_SECONDS = 15
_BATCH_ANSWER_TIMEOUT_SECONDS = 300


async def _queue_answer_job(job_type: str, question_id: int, question_text: str,
                            user_id: int, **payload_extra):
    """Create one durable answer job and try immediate ARQ delivery.

    A failed Redis enqueue only leaves the job pending.  The worker dispatcher
    will retry it later, so an HTTP process restart cannot lose the request.
    """
    def _create():
        with get_db_connection() as conn:
            active_params = [job_type, question_id]
            active_sql = (
                "SELECT j.id, j.status FROM jobs j "
                "JOIN job_payloads p ON p.job_id = j.id "
                "WHERE j.job_type = ? AND j.status IN ('pending', 'queued', 'running') "
                "AND json_extract(p.payload, '$.question_id') = ?"
            )
            if job_type == "generate_recitation":
                active_sql += " AND j.created_by = ?"
                active_params.append(user_id)
            active_sql += " ORDER BY j.id DESC LIMIT 1"
            active = conn.execute(active_sql, active_params).fetchone()
            if active:
                conn.commit()
                return int(active["id"]), active["status"]

            payload = {
                "question_id": question_id,
                "question_text": question_text,
                "user_id": user_id,
                **payload_extra,
            }
            cursor = conn.execute(
                "INSERT INTO jobs "
                "(job_type, status, progress_total, created_by, idempotency_key) "
                "VALUES (?, 'pending', 1, ?, ?)",
                (
                    job_type,
                    user_id,
                    f"manual:{job_type}:{user_id}:{question_id}:{uuid4().hex}",
                ),
            )
            job_id = cursor.lastrowid
            conn.execute(
                "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                (job_id, json.dumps(payload, ensure_ascii=False)),
            )
            conn.commit()
            return int(job_id), "pending"

    job_id, status = await run_db(_create)
    if status != "pending":
        return {"job_id": job_id, "status": status}

    try:
        from app.services.job_lifecycle import mark_job_dispatched
        if job_type == "generate_recitation":
            from app.worker import enqueue_generate_recitation_job as enqueue
        else:
            from app.worker import enqueue_generate_answer_job as enqueue

        arq_job = await enqueue(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        def _mark():
            with get_db_connection() as conn:
                if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                    raise RuntimeError(f"答案任务不可再投递: job_id={job_id}")
                conn.commit()

        await run_db(_mark)
        return {"job_id": job_id, "status": "queued"}
    except Exception as exc:
        logger.warning(
            "答案任务 ARQ 调度失败，保留 pending 等待 dispatcher: job_id=%s error=%s",
            job_id,
            exc,
        )
        return {"job_id": job_id, "status": "pending", "dispatch_error": str(exc)[:300]}


async def _dispatch_persisted_answer_job(job_id: int) -> bool:
    """Try to deliver an already-created answer child job to ARQ."""
    try:
        from app.services.job_lifecycle import mark_job_dispatched
        from app.worker import enqueue_generate_answer_job

        arq_job = await enqueue_generate_answer_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        def _mark():
            with get_db_connection() as conn:
                if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                    raise RuntimeError(f"批量答案任务不可再投递: job_id={job_id}")
                conn.commit()

        await run_db(_mark)
        return True
    except Exception as exc:
        logger.warning(
            "批量答案任务 ARQ 调度失败，保留 pending 等待 dispatcher: job_id=%s error=%s",
            job_id,
            exc,
        )
        return False


async def _allow_no_search_or_raise(
    user: dict, allow_no_search: bool, search_scope: str = "user"
) -> bool:
    """Require an explicit confirmation before starting a model-only answer job."""
    from app.core.config import get_user_search_config_status

    status = await run_db(
        lambda: get_user_search_config_status(user["id"], scope=search_scope)
    )
    if status.get("configured"):
        return False
    if allow_no_search:
        return True
    if user.get("is_admin"):
        message = "当前没有可用的个人或公共联网搜索配置。是否使用非搜索模式继续生成？"
    else:
        message = "当前没有配置个人联网搜索。是否使用非搜索模式继续生成？"
    raise HTTPException(
        status_code=409,
        detail={
            "code": "SEARCH_NOT_CONFIGURED",
            "message": message,
            "allow_no_search": True,
        },
    )


@router.put("/save-user-answer/{question_id}")
async def save_user_answer(
    question_id: int, body: dict, user: dict = Depends(get_current_user)
):
    """保存用户的背诵稿（手动编辑）"""
    answer = body.get("answer", "")

    def _check_visible():
        with get_db_connection() as conn:
            # all 口径：公共题 + 自己的题（背诵稿保存须对用户可见）
            from app.db.queries import build_bank_where_clause

            from_clause, where_clause, params = build_bank_where_clause(
                user["id"], "all"
            )
            return conn.execute(
                f"SELECT 1 {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()

    if not await run_db(_check_visible):
        raise HTTPException(status_code=404, detail="题目不存在或无权访问")

    def _upsert():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                (user["id"], question_id, answer, answer),
            )
            conn.commit()
            return True

    await run_db(_upsert)
    await invalidate_master_bank_cache()
    return {"status": "success"}


@router.post("/generate-answer/{question_id}")
async def generate_master_answer(
    question_id: int,
    user: dict = Depends(get_current_user),
    force: bool = Query(False, description="管理员重新生成时忽略已有答案"),
    allow_no_search: bool = Query(False, description="已确认使用无搜索模式"),
):
    """生成公共参考答案（仅管理员，全局共享）"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="公共参考答案仅管理员可生成")

    def _get():
        with get_db_connection() as conn:
            from_clause, where_clause, params = _build_bank_where_clause(user)
            return conn.execute(
                f"SELECT qb.question, qb.ai_answer {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)

    is_admin = user.get("is_admin", False)

    # 管理员：如果已有有效答案，直接返回（兼容旧行为）
    if is_admin and not force and row["ai_answer"] and "生成失败" not in row["ai_answer"]:
        return {"status": "success", "answer": row["ai_answer"]}

    skip_search = await _allow_no_search_or_raise(
        user, allow_no_search, search_scope="public"
    )

    return await _queue_answer_job(
        "generate_answer",
        question_id,
        row["question"],
        user["id"],
        llm_scope="global",
        search_scope="public",
        **({"skip_search": True} if skip_search else {}),
    )


@router.post("/generate-recitation/{question_id}")
async def generate_recitation(
    question_id: int,
    user: dict = Depends(get_current_user),
    allow_no_search: bool = Query(False, description="已确认使用无搜索模式"),
):
    """定制用户个人背诵稿：以公共参考答案为基座，结合岗位/简历个性化改写。"""

    def _get():
        with get_db_connection() as conn:
            from_clause, where_clause, params = _build_bank_where_clause(user)
            return conn.execute(
                f"SELECT qb.question, qb.ai_answer {from_clause} "
                f"{where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)
    if not row["ai_answer"] or "生成失败" in row["ai_answer"]:
        raise HTTPException(
            status_code=404, detail="该题目暂无公共参考答案，请等待管理员生成"
        )

    if not await check_and_record(user["id"]):
        raise HTTPException(status_code=429, detail="今日 AI 调用次数已达上限")

    skip_search = await _allow_no_search_or_raise(user, allow_no_search)

    return await _queue_answer_job(
        "generate_recitation",
        question_id,
        row["question"],
        user["id"],
        **({"skip_search": True} if skip_search else {}),
    )


@router.post("/batch-generate-answers")
async def batch_generate_answers(
    req: BatchGenerateAnswersRequest, user: dict = Depends(get_current_user)
):
    """批量生成公共参考答案（SSE 流式推送进度，仅管理员）"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="公共参考答案仅管理员可生成")
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _load():
        with get_db_connection() as conn:
            placeholders = ",".join("?" * len(req.ids))
            from_clause, where_clause, params = _build_bank_where_clause(user)
            from app.db.queries import get_dynamic_frequency_sql

            frequency_sql = get_dynamic_frequency_sql("all", user["id"])
            return conn.execute(
                f"SELECT qb.id, qb.question, qb.ai_answer {from_clause} "
                f"{where_clause} AND qb.id IN ({placeholders}) "
                f"ORDER BY ({frequency_sql}) DESC, qb.id ASC",
                params + req.ids,
            ).fetchall()

    rows = await run_db(_load)
    if not rows:
        raise HTTPException(status_code=404, detail="未找到任何匹配题目")

    questions = [
        (r["id"], r["question"])
        for r in rows
        if r["question"]
        and (
            req.force
            or not r["ai_answer"]
            or "生成失败" in r["ai_answer"]
        )
    ]
    skipped = len(rows) - len(questions)

    if not questions:
        async def empty_stream():
            yield f"data: {json.dumps({'type': 'done', 'generated': 0, 'failed': 0, 'skipped': skipped})}\n\n"

        return StreamingResponse(
            empty_stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    skip_search = await _allow_no_search_or_raise(
        user, req.allow_no_search, search_scope="public"
    )

    def _create_batch_jobs():
        from app.services.job_lifecycle import (
            ANSWER_BATCH_JOB_TYPE,
            create_answer_generation_jobs,
        )

        with get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs "
                "(job_type, status, progress_total, created_by, idempotency_key) "
                "VALUES (?, 'pending', ?, ?, ?)",
                (
                    ANSWER_BATCH_JOB_TYPE,
                    len(questions),
                    user["id"],
                    f"batch-answer:{user['id']}:{uuid4().hex}",
                ),
            )
            parent_job_id = int(cursor.lastrowid)
            child_job_ids = create_answer_generation_jobs(
                conn,
                parent_job_id,
                questions,
                user["id"],
                skip_search=skip_search,
                llm_scope="global",
                search_scope="public",
            )
            conn.commit()
            return parent_job_id, child_job_ids

    parent_job_id, child_job_ids = await run_db(_create_batch_jobs)
    if req.force:
        # 强制刷新按频率顺序投递，确保高频题先进入最新答案链路；普通补全
        # 仍可并发投递，避免影响历史上传流程的吞吐。
        for child_job_id in child_job_ids:
            await _dispatch_persisted_answer_job(child_job_id)
    else:
        await asyncio.gather(
            *(_dispatch_persisted_answer_job(job_id) for job_id in child_job_ids)
        )

    async def event_stream():
        total = len(child_job_ids)
        last_progress = None
        last_heartbeat = asyncio.get_running_loop().time()
        sent_events = set()
        yield f"data: {json.dumps({'type': 'init', 'job_id': parent_job_id, 'total': total, 'skipped': skipped})}\n\n"
        try:
            while True:
                def _read_children():
                    with get_db_connection() as conn:
                        rows_by_id = {
                            row["id"]: dict(row)
                            for row in conn.execute(
                                "SELECT id, status, error FROM jobs WHERE id IN ({})".format(
                                    ",".join("?" * len(child_job_ids))
                                ),
                                child_job_ids,
                            ).fetchall()
                        }
                        return [
                            {
                                "id": qid,
                                "status": rows_by_id.get(job_id, {}).get("status", "pending"),
                                "error": rows_by_id.get(job_id, {}).get("error"),
                            }
                            for (qid, _), job_id in zip(questions, child_job_ids)
                        ]

                states = await run_db(_read_children)
                completed = sum(item["status"] == "completed" for item in states)
                failed = sum(item["status"] == "failed" for item in states)
                done_count = completed + failed
                progress = (done_count, completed, failed)
                if progress != last_progress:
                    for item in states:
                        if item["status"] in ("completed", "failed"):
                            event_key = (item["id"], item["status"])
                            if event_key not in sent_events:
                                sent_events.add(event_key)
                                yield f"data: {json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': item['id'], 'success': item['status'] == 'completed', 'error': item['error']}, ensure_ascii=False)}\n\n"
                    last_progress = progress

                if done_count == total:
                    yield f"data: {json.dumps({'type': 'done', 'job_id': parent_job_id, 'generated': completed, 'failed': failed, 'skipped': skipped})}\n\n"
                    return

                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= _BATCH_SSE_HEARTBEAT_SECONDS:
                    yield f"data: {json.dumps({'type': 'heartbeat', 'job_id': parent_job_id})}\n\n"
                    last_heartbeat = now
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            # Child jobs intentionally continue in ARQ after the browser closes;
            # reconnecting to the same job can still observe the final result.
            raise
        except Exception as exc:
            logger.exception("批量答案进度流失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败: {str(exc)[:200]}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
        },
    )

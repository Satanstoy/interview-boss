import json
import logging
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db, get_current_job_position
from app.services.question_bank_integrity import (
    canonicalize_question_bank_payload,
    claim_public_original_questions,
    sync_question_bank_projections,
)

logger = logging.getLogger("interview-boss")
router = (
    APIRouter()
)  # NO prefix - paths include both /api/jobs/... and /api/master-bank/...


@router.get("/api/jobs/{job_id}/stream")
async def stream_job_progress(job_id: int, user: dict = Depends(get_current_user)):
    """Stream job progress via SSE."""
    is_admin = user.get("is_admin", 0)
    user_id = user["id"]

    async def event_generator():
        last_update = None
        while True:

            def _check():
                with get_db_connection() as conn:
                    return conn.execute(
                        "SELECT status, progress_current, progress_total, progress_message, result, error "
                        "FROM jobs WHERE id = ? AND (? = 1 OR created_by = ?)",
                        (job_id, is_admin, user_id),
                    ).fetchone()

            job = await run_db(_check)
            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': '任务不存在'})}\n\n"
                break

            update = {
                "type": "progress"
                if job["status"] in ("queued", "running")
                else job["status"],
                "status": job["status"],
                "current": job["progress_current"],
                "total": job["progress_total"],
                "message": job["progress_message"]
                or ("等待 worker 调度" if job["status"] == "queued" else ""),
            }

            current_update = json.dumps(update)
            if current_update != last_update:
                yield f"data: {current_update}\n\n"
                last_update = current_update

            if job["status"] in ("completed", "failed"):
                if job["error"]:
                    yield f"data: {json.dumps({'type': 'error', 'status': 'failed', 'job_id': job_id, 'message': job['error']}, ensure_ascii=False)}\n\n"
                elif job["result"]:
                    # 尝试解析 JSON result（submit_import 等任务会存 JSON）
                    try:
                        result_data = json.loads(job["result"])
                        yield f"data: {json.dumps({'type': 'done', 'status': 'completed', 'job_id': job_id, 'result': result_data}, ensure_ascii=False)}\n\n"
                    except (json.JSONDecodeError, TypeError):
                        yield f"data: {json.dumps({'type': 'done', 'status': 'completed', 'job_id': job_id, 'message': job['result']}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'done', 'status': 'completed', 'job_id': job_id, 'message': '任务完成'}, ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(2)  # Poll every 2 seconds

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.get("/api/jobs/{job_id}")
async def get_job_status(job_id: int, user: dict = Depends(get_current_user)):
    """Get job status (non-streaming)."""
    is_admin = user.get("is_admin", 0)
    user_id = user["id"]

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, job_type, status, progress_current, progress_total, progress_message, error, created_at, completed_at "
                "FROM jobs WHERE id = ? AND (? = 1 OR created_by = ?)",
                (job_id, is_admin, user_id),
            ).fetchone()

    job = await run_db(_query)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dict(job)


@router.post("/api/master-bank/build")
async def build_master_bank(user: dict = Depends(get_admin_user)):
    """Submit a master bank rebuild job (async via ARQ worker)."""

    def _create_job():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                # Check for existing running build
                existing = cursor.execute(
                    "SELECT id FROM jobs WHERE job_type = 'build_master_bank' AND status IN ('pending', 'queued', 'running') AND created_by = ?",
                    (user["id"],),
                ).fetchone()
                if existing:
                    return None  # Already running

                cursor.execute(
                    "INSERT INTO jobs (job_type, status, created_by) VALUES ('build_master_bank', 'pending', ?)",
                    (user["id"],),
                )
                job_id = cursor.lastrowid
                conn.commit()
                return job_id
            except Exception:
                conn.rollback()
                raise

    job_id = await run_db(_create_job)
    if job_id is None:
        raise HTTPException(status_code=409, detail="已有重建任务在执行中，请等待完成")

    # Schedule via ARQ.  If Redis is temporarily unavailable, keep the durable
    # job pending and let the worker dispatcher retry it; never execute a long
    # rebuild inside the FastAPI process.
    arq_scheduled = False
    dispatch_error = None
    try:
        from app.worker import enqueue_build_job
        from app.services.job_lifecycle import mark_job_dispatched

        arq_job = await enqueue_build_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        def _mark():
            with get_db_connection() as conn:
                if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                    raise RuntimeError(f"题库重建任务不可再投递: job_id={job_id}")
                conn.commit()

        await run_db(_mark)
        arq_scheduled = True
        logger.info("重建任务已通过 ARQ 调度: job_id=%s arq_job_id=%s", job_id, arq_job_id)
    except Exception as e:
        dispatch_error = str(e)[:300]
        logger.warning("ARQ 调度失败，任务保留 pending 等待 dispatcher: %s", e)

    return {
        "job_id": job_id,
        "status": "queued" if arq_scheduled else "pending",
        "dispatch_error": dispatch_error,
        "message": "重建任务已提交，请通过 SSE 监听进度",
    }

@router.post("/api/master-bank/compact")
async def compact_singletons(
    admin: dict = Depends(get_admin_user),
    match_existing: bool = Query(False, description="是否先匹配已有聚类"),
):
    """孤岛碎片整理：对独立题做二次合并（SSE 流式推送）

    Args:
        match_existing: True 时先将孤岛匹配到已有聚类（RAG+LLM），再做内部合并
    """

    async def event_stream():
        try:
            from app.services.pipeline import compact_singletons_in_db

            mode = "匹配已有聚类+内部合并" if match_existing else "仅内部合并"
            yield f"data: {json.dumps({'type': 'init', 'step': 'compact', 'message': f'开始孤岛碎片整理（{mode}）...'})}\n\n"
            result = await compact_singletons_in_db(
                user_id=None, match_existing=match_existing, operator_id=admin["id"]
            )
            yield f"data: {json.dumps({'type': 'done', **result})}\n\n"
        except Exception as e:
            logger.exception("孤岛碎片整理失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'整理失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


@router.post("/api/master-bank/build-personal")
async def build_personal_bank(user: dict = Depends(get_current_user)):
    """个人题库与公共题库聚类合并（SSE 流式推送进度）"""

    async def event_stream():
        try:
            uid = user["id"]
            yield f"data: {json.dumps({'type': 'init', 'total': 0, 'step': 'prepare', 'message': '正在加载数据...'})}\n\n"

            from app.db.connection import get_user_job_position

            _, current_pos = get_user_job_position(uid)
            if not current_pos:
                current_pos = get_current_job_position()

            def _load():
                with get_db_connection() as conn:
                    # 加载用户的个人题目
                    personal = conn.execute(
                        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, "
                        "original_questions, original_question_sources, job_position "
                        "FROM question_bank WHERE owner_id = ? AND job_position = ?",
                        (uid, current_pos),
                    ).fetchall()
                    # 加载公共题库（含 original_questions 用于匹配上下文）
                    public = conn.execute(
                        "SELECT id, question, cat2, sources, original_questions FROM question_bank "
                        "WHERE owner_id IS NULL AND status = 'approved' AND job_position = ?",
                        (current_pos,),
                    ).fetchall()
                    return [dict(r) for r in personal], [dict(r) for r in public]

            personal_rows, public_rows = await run_db(_load)

            if not personal_rows:
                yield f"data: {json.dumps({'type': 'done', 'error': '没有个人题目需要合并'})}\n\n"
                return

            if not public_rows:
                yield f"data: {json.dumps({'type': 'done', 'error': '公共题库为空，无法合并'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'init', 'total': len(personal_rows), 'message': f'开始合并: {len(personal_rows)} 道个人题目 vs {len(public_rows)} 道公共题目'})}\n\n"

            # 按 cat2 构建公共题库聚类上下文
            existing_by_cat2 = {}
            for r in public_rows:
                cat2 = r.get("cat2") or ""
                if cat2 not in existing_by_cat2:
                    existing_by_cat2[cat2] = []
                all_qs = [r["question"]]
                try:
                    orig = json.loads(r.get("original_questions") or "[]")
                    all_qs.extend([q for q in orig if q and q != r["question"]])
                except Exception:
                    pass
                existing_by_cat2[cat2].append(
                    {
                        "question_bank_id": r["id"],
                        "question": r["question"],
                        "all_questions": all_qs,
                    }
                )

            # 为个人题目分配临时 id 用于匹配
            new_rows_for_match = []
            for idx, row in enumerate(personal_rows):
                new_rows_for_match.append(
                    {
                        "id": idx,
                        "question": row["question"],
                        "cat2": row.get("cat2") or "",
                    }
                )

            yield f"data: {json.dumps({'type': 'progress', 'step': 'match', 'current': 0, 'total': 1, 'message': 'LLM 匹配中...'})}\n\n"

            match_result = await match_new_questions(
                new_rows_for_match, existing_by_cat2, user_id=user["id"]
            )
            matched = match_result["matched"]
            unmatched = match_result["unmatched"]

            # 执行合并：匹配到的个人题目 → 增加公共题目的 frequency，追加 sources
            merged_count = 0

            def _merge():
                nonlocal merged_count
                with get_db_connection() as conn:
                    is_admin = bool(user.get("is_admin", 0))
                    for m in matched:
                        new_id = m["new_id"]
                        qb_id = m["question_bank_id"]
                        personal_row = personal_rows[new_id]
                        existing = conn.execute(
                            "SELECT sources, original_questions, original_question_sources, owner_id, status FROM question_bank WHERE id = ?",
                            (qb_id,),
                        ).fetchone()
                        if existing:
                            try:
                                sources = (
                                    json.loads(existing["sources"])
                                    if existing["sources"]
                                    else []
                                )
                            except (json.JSONDecodeError, TypeError):
                                sources = []
                            personal_sources = []
                            try:
                                personal_sources = (
                                    json.loads(personal_row.get("sources", "[]"))
                                    if personal_row.get("sources")
                                    else []
                                )
                            except (json.JSONDecodeError, TypeError):
                                pass
                            # BUG-012: URL-based 去重
                            existing_urls = {s.get("url") for s in sources}
                            for s in personal_sources:
                                if s.get("url") not in existing_urls:
                                    sources.append(s)
                                    existing_urls.add(s.get("url"))
                            # BUG-013: 回写 original_questions
                            try:
                                orig_qs = (
                                    json.loads(existing["original_questions"])
                                    if existing["original_questions"]
                                    else []
                                )
                                orig_qs_src = (
                                    json.loads(existing["original_question_sources"])
                                    if existing["original_question_sources"]
                                    else []
                                )
                            except (json.JSONDecodeError, TypeError):
                                orig_qs, orig_qs_src = [], []
                            personal_q_text = personal_row["question"]
                            if personal_q_text:
                                orig_qs.append(personal_q_text)
                                orig_qs_src.append(
                                    {"question": personal_q_text, "sources": personal_sources}
                                )
                            sources, orig_qs, orig_qs_src = canonicalize_question_bank_payload(
                                sources, orig_qs, orig_qs_src
                            )
                            if is_admin:
                                # 管理员：个人题并入公共题（现有行为）
                                conn.execute(
                                    "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (
                                        len(orig_qs),
                                        json.dumps(sources, ensure_ascii=False),
                                        json.dumps(orig_qs, ensure_ascii=False),
                                        json.dumps(orig_qs_src, ensure_ascii=False),
                                        qb_id,
                                    ),
                                )
                                claim_public_original_questions(
                                    conn,
                                    qb_id,
                                    existing["owner_id"],
                                    existing["status"],
                                    orig_qs,
                                )
                                sync_question_bank_projections(
                                    conn.cursor(), qb_id, sources, orig_qs, orig_qs_src
                                )
                                from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                                mark_cluster_review_pending(
                                    conn, qb_id, "private_question_merged"
                                )
                                # 删除已合并的个人题目
                                conn.execute(
                                    "DELETE FROM question_bank WHERE id = ?",
                                    (personal_row["id"],),
                                )
                            else:
                                # 非管理员：合并只落个人题，公共题数据绝不改动
                                # 个人题吸收公共题来源（去重后），公共题保持原样，个人题保留
                                conn.execute(
                                    "UPDATE question_bank SET sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (
                                        json.dumps(sources, ensure_ascii=False),
                                        personal_row["id"],
                                    ),
                                )
                                personal_oqs = personal_row.get("original_questions") or []
                                personal_oqs_src = personal_row.get("original_question_sources") or []
                                if isinstance(personal_oqs, str):
                                    personal_oqs = json.loads(personal_oqs or "[]")
                                if isinstance(personal_oqs_src, str):
                                    personal_oqs_src = json.loads(personal_oqs_src or "[]")
                                sync_question_bank_projections(
                                    conn.cursor(),
                                    personal_row["id"],
                                    sources,
                                    personal_oqs,
                                    personal_oqs_src,
                                )
                        merged_count += 1
                    conn.commit()

            await run_db(_merge)

            yield f"data: {json.dumps({'type': 'progress', 'step': 'done', 'current': 0, 'total': 0, 'message': '合并完成'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'merged': merged_count, 'kept': len(unmatched), 'total_personal': len(personal_rows)})}\n\n"
        except Exception as e:
            logger.exception("个人题库构建失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'构建失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )

import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from app.core.auth import get_admin_user, get_current_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.get("/api/interview/experiences")
async def list_experiences(user: dict = Depends(get_current_user)):
    """获取可用的面经列表（用于模拟面试选择）"""

    def _query():
        with get_db_connection() as conn:
            deleted_at_clause = "AND deleted_at IS NULL" if _has_column(conn, "interview", "deleted_at") else ""
            rows = conn.execute(
                f"""
                SELECT id, company, round, job_position, difficulty, questions_list
                FROM interview
                WHERE status = 'approved'
                  AND questions_list IS NOT NULL
                  AND questions_list != ''
                  {deleted_at_clause}
                  AND (owner_id = ? OR owner_id IS NULL)
                ORDER BY company, round
                """,
                (user["id"],),
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for row in rows:
        questions = [q.strip() for q in str(row["questions_list"] or "").splitlines() if q.strip()]
        result.append({
            "id": row["id"],
            "company": row["company"] or "未知公司",
            "round": row["round"] or "未知轮次",
            "job_position": row["job_position"] or "",
            "difficulty": row["difficulty"] or "",
            "question_count": len(questions),
        })
    return {"status": "success", "data": result}


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


@router.post("/api/interview/{interview_id}/re-process")
async def reprocess_interview(interview_id: int, user: dict = Depends(get_admin_user)):
    """创建单条面经重分析任务，由 ARQ worker 执行耗时 AI 处理。"""
    def _load():
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM interview WHERE id = ?", (interview_id,)).fetchone()

    row = await run_db(_load)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该面经记录")

    questions_str = row['questions_list']
    if not questions_str or not questions_str.strip():
        raise HTTPException(status_code=400, detail="该面经没有具体的题目清单可以分析")

    from app.services.interview_reprocess import submit_interview_reprocess_job

    job = await submit_interview_reprocess_job(interview_id, user_id=user["id"])
    return {
        "status": "success",
        "message": "重分析任务已进入后台队列",
        "job_id": job["job_id"],
        "job_status": job["status"],
    }


@router.post("/api/interview/{interview_id}/re-process-stream")
async def reprocess_interview_stream(interview_id: int, user: dict = Depends(get_admin_user)):
    """SSE 版重新分析单条面经；SSE 只订阅 durable job 状态。"""

    def _load():
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM interview WHERE id = ?", (interview_id,)).fetchone()

    row = await run_db(_load)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该面经记录")

    questions_str = row['questions_list']
    if not questions_str or not questions_str.strip():
        raise HTTPException(status_code=400, detail="该面经没有具体的题目清单可以分析")

    from app.services.interview_reprocess import submit_interview_reprocess_job

    submitted = await submit_interview_reprocess_job(interview_id, user_id=user["id"])
    job_id = submitted["job_id"]

    async def event_stream():
        last_update = None
        last_heartbeat = 0.0
        import time

        yield f"data: {json.dumps({'step': 'queued', 'message': '重分析任务已持久化，等待 ARQ worker', 'type': 'progress', **submitted}, ensure_ascii=False)}\n\n"
        while True:
            def _read_job():
                with get_db_connection() as conn:
                    return conn.execute(
                        "SELECT status, progress_current, progress_total, progress_message, result, error "
                        "FROM jobs WHERE id = ? AND job_type = 'reprocess_interview'",
                        (job_id,),
                    ).fetchone()

            job = await run_db(_read_job)
            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': '重分析任务不存在'}, ensure_ascii=False)}\n\n"
                break

            status = job["status"]
            update = {
                "step": "tag" if status == "running" else "queued",
                "message": job["progress_message"] or "等待 worker 调度",
                "type": "progress",
                "status": status,
                "job_id": job_id,
                "current": job["progress_current"],
                "total": job["progress_total"],
            }
            serialized = json.dumps(update, ensure_ascii=False)
            now = time.monotonic()
            if serialized != last_update or now - last_heartbeat >= 15:
                yield f"data: {serialized}\n\n"
                last_update = serialized
                last_heartbeat = now

            if status == "completed":
                result = {}
                if job["result"]:
                    try:
                        result = json.loads(job["result"])
                    except (TypeError, json.JSONDecodeError):
                        result = {}
                yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {result.get("tagged_count", 0)} 道题', 'type': 'progress', **result}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'step': 'done', 'message': '重分析完成，聚类任务后台处理中', 'type': 'done', 'job_id': job_id, **result}, ensure_ascii=False)}\n\n"
                break
            if status == "failed":
                yield f"data: {json.dumps({'type': 'error', 'status': 'failed', 'job_id': job_id, 'message': job['error'] or '重分析失败'}, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.post("/api/interview/batch-reprocess-stream")
async def batch_reprocess_stream(user: dict = Depends(get_admin_user)):
    """SSE 版批量分析：逐条创建 durable job 并订阅完成状态。"""
    def _load_all():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, url, company, round, questions_list, job_position "
                "FROM interview WHERE deleted_at IS NULL AND questions_list IS NOT NULL AND questions_list != '' "
                "ORDER BY id"
            ).fetchall()

    interviews = await run_db(_load_all)
    if not interviews:
        raise HTTPException(status_code=400, detail="没有可分析的面经")

    async def event_stream():
        total = len(interviews)
        tagged_total = 0
        from app.services.interview_reprocess import submit_interview_reprocess_job

        yield f"data: {json.dumps({'step': 'init', 'message': f'开始批量分析 {total} 条面经...', 'total': total, 'type': 'progress'}, ensure_ascii=False)}\n\n"

        # 逐条创建并等待 durable job；浏览器断开不会取消 worker 任务。
        for idx, iv in enumerate(interviews):
            iv = dict(iv)
            try:
                submitted = await submit_interview_reprocess_job(
                    iv["id"], user_id=user["id"]
                )
                job_id = submitted["job_id"]
                yield f"data: {json.dumps({'step': 'queued', 'current': idx + 1, 'total': total, 'interview_id': iv['id'], 'message': '任务已进入持久化队列', 'type': 'progress', **submitted}, ensure_ascii=False)}\n\n"

                last_status = None
                while True:
                    def _read_job():
                        with get_db_connection() as conn:
                            return conn.execute(
                                "SELECT status, progress_message, result, error "
                                "FROM jobs WHERE id = ? AND job_type = 'reprocess_interview'",
                                (job_id,),
                            ).fetchone()

                    job = await run_db(_read_job)
                    if not job:
                        raise RuntimeError("重分析任务不存在")
                    if job["status"] != last_status:
                        yield f"data: {json.dumps({'step': 'tag', 'current': idx + 1, 'total': total, 'interview_id': iv['id'], 'message': job['progress_message'] or '等待 worker 调度', 'status': job['status'], 'type': 'progress'}, ensure_ascii=False)}\n\n"
                        last_status = job["status"]
                    if job["status"] == "completed":
                        result = {}
                        if job["result"]:
                            try:
                                result = json.loads(job["result"])
                            except (TypeError, json.JSONDecodeError):
                                pass
                        tagged_total += int(result.get("tagged_count", 0))
                        break
                    if job["status"] == "failed":
                        yield f"data: {json.dumps({'step': 'tag', 'current': idx + 1, 'total': total, 'interview_id': iv['id'], 'message': job['error'] or '分析失败', 'type': 'error'}, ensure_ascii=False)}\n\n"
                        break
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"面经 {iv['id']} 打标签失败: {e}")
                yield f"data: {json.dumps({'step': 'tag', 'current': idx + 1, 'total': total, 'interview_id': iv['id'], 'error': str(e), 'type': 'error'}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'step': 'done', 'message': f'标注完成，共 {total} 条面经，{tagged_total} 道题；聚类任务后台处理中', 'type': 'done', 'total': total, 'tagged_total': tagged_total, 'cluster_pending': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

import json
import logging
import openai
import magic as _magic
import base64

from typing import List, Optional
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends,
)
from fastapi.responses import StreamingResponse
from app.core.config import MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
from app.core.auth import get_current_user
from app.core.validation import validate_source_url
from app.db.connection import get_db_connection, run_db, get_taxonomy_for_position
from app.db.operations import (
    _check_duplicate_url_sync,
)

from app.agents.submit.graph import stream_submit_graph

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _mark_job_dispatched(job_id: int, arq_job_id: str, marker) -> None:
    """Persist ARQ delivery on the same durable job row."""
    with get_db_connection() as conn:
        if not marker(conn, job_id, arq_job_id):
            raise RuntimeError(f"上传任务不可再投递: job_id={job_id}")
        conn.commit()


# Backward-compatible re-exports — business logic moved to app.services.submit_service
from app.services.submit_service import (
    tag_questions_batch,
    incremental_update_master_bank,
    background_generate_answer,
    persist_answer_generation_jobs,
    _get_current_position_for_user,
)


@router.post("/api/submit-stream-v2")
async def submit_data_stream_v2(
    user: dict = Depends(get_current_user),
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    content_type: Optional[str] = Form(""),
    target: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[]),
):
    """SSE 版提交端点 (LangGraph 版本) — 流式推送处理进度。"""

    # ── 输入校验（与 v1 相同） ──
    if text and len(text) > 50000:
        raise HTTPException(
            status_code=400, detail="文本内容过长，请限制在 50000 字符以内"
        )
    url = validate_source_url(url)
    submit_target = (target or "private").lower()
    # 分享意愿：share → 公共审核队列；private → 个人路径（目标内部映射）
    if submit_target not in ("share", "private"):
        submit_target = "private"
    bank_target = "personal" if submit_target == "private" else "public"
    if url:
        check_owner = user["id"] if bank_target == "personal" else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(
                status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！"
            )
    if not (text or "").strip() and (
        not files or len(files) == 0 or not files[0].filename
    ):
        raise HTTPException(
            status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。"
        )

    # ── 读取文件到内存 ──
    image_data = []
    if files and files[0].filename:
        if len(files) > 20:
            raise HTTPException(status_code=400, detail="最多上传 20 个文件")
        total_size = 0
        for file in files:
            if file.content_type.startswith("image/"):
                content = await file.read()
                total_size += len(content)
                if total_size > MAX_TOTAL_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）",
                    )
                if len(content) > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）",
                    )
                real_mime = _magic.from_buffer(content[:2048], mime=True)
                if real_mime not in ALLOWED_MIME_TYPES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）",
                    )
                image_data.append({"content": content, "mime": real_mime})

    input_state = {
        "raw_text": text or "",
        "image_data": image_data,
        "url": url,
        "season": season or "",
        "content_type_hint": (content_type or "").lower(),
        "target": bank_target,
        "user_id": user["id"],
        "is_admin": bool(user.get("is_admin", 0)),
        "job_position": _get_current_position_for_user(user["id"]),
    }

    async def event_stream():
        result_collector = {}
        try:
            async for sse_data in stream_submit_graph(
                input_state, result_collector=result_collector
            ):
                yield sse_data
        except openai.AuthenticationError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'API Key 无效或已过期，请在系统配置中检查并更新'})}\n\n"
        except openai.NotFoundError as e:
            msg = str(e)
            if "image" in msg.lower():
                yield f"data: {json.dumps({'type': 'error', 'message': '当前模型不支持图片输入，请在系统配置中切换支持视觉的模型，或仅提交文本内容'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'error', 'message': 'LLM 接口返回错误，请检查模型配置是否正确'})}\n\n"
        except openai.APIConnectionError:
            yield f"data: {json.dumps({'type': 'error', 'message': '无法连接 LLM 服务，请检查 Base URL 是否正确'})}\n\n"
        except openai.APITimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'LLM 服务响应超时，请稍后重试'})}\n\n"
        except openai.APIStatusError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'LLM 接口返回错误（{e.status_code}），请查看服务端日志'})}\n\n"
        except Exception as e:
            logger.exception("LangGraph 流式提交处理失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'处理失败: {str(e)[:200]}'})}\n\n"
        finally:
            # 旧 SSE 上传路径也必须使用 durable child jobs；请求结束、断线或
            # FastAPI 重启都不能让已入库的个人题目丢失答案生成。
            answer_tasks = result_collector.get("answer_tasks", [])
            uid = result_collector.get("user_id") or user["id"]
            if answer_tasks and uid is not None:
                try:
                    parent_id, child_ids = await persist_answer_generation_jobs(
                        answer_tasks,
                        uid,
                        source="legacy-submit-answer",
                        llm_scope="global"
                        if user.get("is_admin") and bank_target == "public"
                        else "user",
                        search_scope="public"
                        if user.get("is_admin") and bank_target == "public"
                        else "user",
                    )
                    logger.info(
                        "旧上传路径已持久化答案任务: parent=%s children=%s",
                        parent_id,
                        len(child_ids),
                    )
                except Exception:
                    logger.exception("旧上传路径持久化答案任务失败，未执行进程内 fallback")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


# ── 上传任务化接口（后台 Job 模式） ──

SUBMIT_PHASES = ["extract", "fill", "tag", "match", "save", "cluster"]


@router.post("/api/submit-jobs")
async def create_submit_job(
    user: dict = Depends(get_current_user),
    url: Optional[str] = Form(""),
    text: Optional[str] = Form(""),
    season: Optional[str] = Form(""),
    content_type: Optional[str] = Form(""),
    target: Optional[str] = Form(""),
    files: List[UploadFile] = File(default=[]),
):
    """创建上传导入后台任务。校验输入 → 存 payload → 创建 job → 入队执行。"""

    # ── 输入校验（与 submit-stream-v2 相同） ──
    if text and len(text) > 50000:
        raise HTTPException(
            status_code=400, detail="文本内容过长，请限制在 50000 字符以内"
        )
    url = validate_source_url(url)
    submit_target = (target or "private").lower()
    # 分享意愿：share → 公共审核队列；private → 个人路径（目标内部映射）
    if submit_target not in ("share", "private"):
        submit_target = "private"
    bank_target = "personal" if submit_target == "private" else "public"
    if url:
        check_owner = user["id"] if bank_target == "personal" else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(
                status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！"
            )
    if not (text or "").strip() and (
        not files or len(files) == 0 or not files[0].filename
    ):
        raise HTTPException(
            status_code=400, detail="提交内容不能为空，必须提供纯文本或至少一张图片。"
        )

    # ── 读取文件到内存 ──
    image_data = []
    if files and files[0].filename:
        if len(files) > 20:
            raise HTTPException(status_code=400, detail="最多上传 20 个文件")
        total_size = 0
        for file in files:
            if file.content_type.startswith("image/"):
                content = await file.read()
                total_size += len(content)
                if total_size > MAX_TOTAL_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"上传文件总大小超过限制（最大 {MAX_TOTAL_UPLOAD_SIZE // 1024 // 1024}MB）",
                    )
                if len(content) > MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"图片 {file.filename} 超过大小限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）",
                    )
                real_mime = _magic.from_buffer(content[:2048], mime=True)
                if real_mime not in ALLOWED_MIME_TYPES:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）",
                    )
                # 图片序列化为 base64 以便存入 payload
                image_data.append(
                    {
                        "content_b64": base64.b64encode(content).decode("ascii"),
                        "mime": real_mime,
                    }
                )

    # 构建 payload
    payload = {
        "raw_text": text or "",
        "image_data": image_data,
        "url": url,
        "season": season or "",
        "content_type_hint": (content_type or "").lower(),
        "target": bank_target,
        "user_id": user["id"],
        "is_admin": bool(user.get("is_admin", 0)),
        "job_position": _get_current_position_for_user(user["id"]),
    }

    # ── 创建 job + 存 payload（单事务） ──
    def _create_job():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                cursor.execute(
                    "INSERT INTO jobs (job_type, status, created_by, progress_total) VALUES ('submit_import', 'pending', ?, ?)",
                    (user["id"], len(SUBMIT_PHASES)),
                )
                job_id = cursor.lastrowid
                cursor.execute(
                    "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                    (job_id, json.dumps(payload, ensure_ascii=False)),
                )
                conn.commit()
                return job_id
            except Exception:
                conn.rollback()
                raise

    job_id = await run_db(_create_job)

    # ── 入队后台执行 ──
    # jobs 是事实源；ARQ 只负责投递。入队失败时保留 pending，交给
    # worker dispatcher 重试，不能退回当前 FastAPI 进程内的临时 task。
    arq_scheduled = False
    dispatch_error = None
    try:
        from app.worker import enqueue_submit_import_job
        from app.services.job_lifecycle import mark_job_dispatched

        arq_job = await enqueue_submit_import_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        await run_db(
            lambda: _mark_job_dispatched(job_id, str(arq_job_id), mark_job_dispatched)
        )
        arq_scheduled = True
        logger.info(
            "上传导入任务已通过 ARQ 调度: job_id=%s arq_job_id=%s",
            job_id,
            arq_job_id,
        )
    except Exception as e:
        dispatch_error = str(e)[:300]
        logger.warning("ARQ 调度失败，任务保留 pending 等待 dispatcher: %s", e)

    return {
        "job_id": job_id,
        "status": "queued" if arq_scheduled else "pending",
        "dispatch_error": dispatch_error,
        "message": (
            "上传任务已进入 ARQ 队列"
            if arq_scheduled
            else "上传任务已创建，等待后台 worker 调度"
        ),
    }


@router.get("/api/submit-jobs/active")
async def get_active_submit_jobs(user: dict = Depends(get_current_user)):
    """查询当前用户上传页需要展示的任务。

    成功任务不再出现在这里；失败任务保留，直到用户重试。若失败任务
    已经产生了新的重试尝试，只返回最新尝试，避免同一上传在界面重复出现。
    """

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT j.id, j.job_type, j.status, j.progress_current, "
                "j.progress_total, j.progress_message, j.last_error AS error, "
                "j.created_at, j.updated_at, j.parent_job_id "
                "FROM jobs j "
                "WHERE j.created_by = ? "
                "AND j.job_type = 'submit_import' "
                "AND j.status IN ('pending', 'queued', 'running', 'failed') "
                "AND NOT EXISTS ("
                "  SELECT 1 FROM jobs child "
                "  WHERE child.parent_job_id = j.id "
                "    AND child.job_type = 'submit_import'"
                ") "
                "ORDER BY CASE WHEN j.status = 'failed' THEN 0 ELSE 1 END, "
                "j.created_at DESC",
                (user["id"],),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["retryable"] = item["status"] == "failed"
                result.append(item)
            return result

    return await run_db(_query)


@router.post("/api/submit-jobs/{job_id}/retry")
async def retry_submit_job(job_id: int, user: dict = Depends(get_current_user)):
    """创建一次新的上传尝试，保留原任务作为审计记录。"""

    def _create_retry():
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                original = conn.execute(
                    "SELECT id, job_type, status, created_by, progress_total "
                    "FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if not original or (
                    original["created_by"] != user["id"]
                    and not user.get("is_admin", False)
                ):
                    raise HTTPException(status_code=404, detail="任务不存在")
                if original["job_type"] != "submit_import":
                    raise HTTPException(status_code=400, detail="该任务不支持重新处理")
                if original["status"] != "failed":
                    raise HTTPException(status_code=409, detail="只有失败任务可以重新处理")

                active_child = conn.execute(
                    "SELECT id FROM jobs WHERE parent_job_id = ? "
                    "AND job_type = 'submit_import' "
                    "AND status IN ('pending', 'queued', 'running') "
                    "ORDER BY id DESC LIMIT 1",
                    (job_id,),
                ).fetchone()
                if active_child:
                    conn.commit()
                    return {"job_id": int(active_child["id"]), "created": False}

                payload_row = conn.execute(
                    "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
                ).fetchone()
                if not payload_row:
                    raise HTTPException(status_code=409, detail="原任务数据已不存在，无法重试")

                retry_count = conn.execute(
                    "SELECT COUNT(*) AS count FROM jobs WHERE parent_job_id = ?",
                    (job_id,),
                ).fetchone()["count"]
                idempotency_key = f"submit-retry:{job_id}:{int(retry_count) + 1}"
                cursor = conn.execute(
                    "INSERT INTO jobs (job_type, status, progress_total, created_by, "
                    "available_at, parent_job_id, idempotency_key) "
                    "VALUES ('submit_import', 'pending', ?, ?, CURRENT_TIMESTAMP, ?, ?)",
                    (
                        original["progress_total"] or 6,
                        original["created_by"],
                        job_id,
                        idempotency_key,
                    ),
                )
                new_job_id = int(cursor.lastrowid)

                payload = json.loads(payload_row["payload"])
                payload["retry_of_job_id"] = job_id
                payload["retry_attempt"] = int(retry_count) + 1
                conn.execute(
                    "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                    (new_job_id, json.dumps(payload, ensure_ascii=False)),
                )
                conn.commit()
                return {"job_id": new_job_id, "created": True}
            except Exception:
                conn.rollback()
                raise

    retry = await run_db(_create_retry)
    new_job_id = retry["job_id"]
    if not retry["created"]:
        return {"job_id": new_job_id, "status": "queued", "created": False}

    dispatch_error = None
    try:
        from app.worker import enqueue_submit_import_job
        from app.services.job_lifecycle import mark_job_dispatched

        arq_job = await enqueue_submit_import_job(new_job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")
        await run_db(
            lambda: _mark_job_dispatched(new_job_id, str(arq_job_id), mark_job_dispatched)
        )
    except Exception as exc:
        dispatch_error = str(exc)[:300]
        logger.warning("重试上传任务暂未投递，等待 dispatcher: job_id=%s error=%s", new_job_id, exc)

    return {
        "job_id": new_job_id,
        "status": "queued" if dispatch_error is None else "pending",
        "created": True,
        "dispatch_error": dispatch_error,
    }

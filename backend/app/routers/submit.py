import asyncio
import json
import logging
import os
import re
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
    BackgroundTasks,
    Depends,
)
from fastapi.responses import StreamingResponse
from app.core.config import MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db, get_taxonomy_for_position
from app.db.operations import (
    _check_duplicate_url_sync,
)

from app.agents.submit.graph import stream_submit_graph

logger = logging.getLogger("interview-boss")

router = APIRouter()


# Backward-compatible re-exports — business logic moved to app.services.submit_service
from app.services.submit_service import (
    tag_questions_batch,
    incremental_update_master_bank,
    background_generate_answer,
    _get_current_position_for_user,
)


def _validate_submit_url(url: str) -> str:
    """校验面经来源链接：非空时必须为 http(s) URL。

    回归防护：用户粘贴 App 内部分享链接（internal://<base64>）会被拒绝，
    避免无效来源进入 question_sources（历史上有 33 行 internal:// 脏数据）。
    """
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        raise HTTPException(
            status_code=400,
            detail="来源链接必须是有效的 http(s) 链接，请检查后重试（没有链接可以留空）",
        )
    return url


@router.post("/api/submit-stream-v2")
async def submit_data_stream_v2(
    bg_tasks: BackgroundTasks,
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
    url = _validate_submit_url(url)
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
            # 派发后台 AI 答案生成
            for qid, qtext in result_collector.get("answer_tasks", []):
                bg_tasks.add_task(
                    background_generate_answer,
                    qid,
                    qtext,
                    result_collector.get("user_id"),
                )

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
    url = _validate_submit_url(url)
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
    # 默认通过 ARQ Worker 消费；仅当显式关闭时回退到 asyncio.create_task。
    arq_scheduled = False
    if os.environ.get("SUBMIT_JOBS_USE_ARQ", "1").lower() in ("1", "true", "yes"):
        try:
            from app.worker import enqueue_submit_import_job

            await enqueue_submit_import_job(job_id)
            arq_scheduled = True
            logger.info(f"上传导入任务已通过 ARQ 调度: job_id={job_id}")
        except Exception as e:
            logger.warning(f"ARQ 调度失败，回退到 asyncio.create_task: {e}")

    if not arq_scheduled:
        from app.worker import submit_import_task

        asyncio.create_task(submit_import_task({}, job_id))
        logger.info(f"上传导入任务已在 backend 后台执行: job_id={job_id}")

    return {"job_id": job_id, "status": "pending", "message": "上传任务已创建"}


@router.get("/api/submit-jobs/active")
async def get_active_submit_jobs(user: dict = Depends(get_current_user)):
    """查询当前用户未完成的上传导入任务。"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, job_type, status, progress_current, progress_total, progress_message, created_at, updated_at "
                "FROM jobs WHERE created_by = ? AND job_type = 'submit_import' AND status IN ('pending', 'running') "
                "ORDER BY created_at DESC",
                (user["id"],),
            ).fetchall()
            return [dict(r) for r in rows]

    return await run_db(_query)

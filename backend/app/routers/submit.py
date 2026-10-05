import json
import logging
import magic as _magic
import base64
import uuid

from typing import List, Optional
from fastapi import (
    APIRouter,
    Header,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends,
)
from fastapi.responses import JSONResponse, StreamingResponse
from app.core.config import MAX_FILE_SIZE, MAX_TOTAL_UPLOAD_SIZE
from app.core.multipart_limits import UploadSubmissionRoute

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
from app.core.auth import get_current_user
from app.core.validation import validate_source_url
from app.db.connection import get_db_connection, run_db
from app.db.operations import (
    _check_duplicate_url_sync,
)
from app.services.upload_lifecycle import (
    UploadFileMeta,
    UploadInputError,
    accept_upload,
    validate_submission,
)
from app.services.upload_policy import ClientPolicyFieldError
from app.services.upload_repository import IdempotencyConflict


logger = logging.getLogger("interview-boss")

router = APIRouter(route_class=UploadSubmissionRoute)


def _mark_job_dispatched(job_id: int, arq_job_id: str, marker) -> None:
    """Persist ARQ delivery on the same durable job row."""
    with get_db_connection() as conn:
        if not marker(conn, job_id, arq_job_id):
            raise RuntimeError(f"上传任务不可再投递: job_id={job_id}")
        conn.commit()


async def _dispatch_accepted_upload_jobs(accepted: dict) -> tuple[int, str | None]:
    """Deliver only durable outbox rows returned by the accept transaction."""

    from app.services.job_lifecycle import mark_job_dispatched

    dispatched = 0
    first_error = None
    for item in accepted.get("dispatch_jobs", []):
        job_id = int(item["job_id"])
        job_type = item["job_type"]
        try:
            if job_type == "credential_preflight":
                from app.worker_enqueue import enqueue_credential_preflight_job

                arq_job = await enqueue_credential_preflight_job(job_id)
            elif job_type == "submit_import":
                from app.worker_enqueue import enqueue_submit_import_job

                arq_job = await enqueue_submit_import_job(job_id)
            else:
                continue
            arq_job_id = getattr(arq_job, "job_id", None)
            if not arq_job_id:
                raise RuntimeError("ARQ 未返回 job_id")
            await run_db(
                lambda jid=job_id, aid=str(arq_job_id): _mark_job_dispatched(
                    jid, aid, mark_job_dispatched
                )
            )
            dispatched += 1
        except Exception as exc:  # durable outbox dispatcher will retry later
            first_error = first_error or str(exc)[:300]
            logger.warning(
                "上传 outbox 投递失败，保留任务等待 dispatcher: job_id=%s type=%s error=%s",
                job_id,
                job_type,
                exc,
            )
    return dispatched, first_error


# Backward-compatible re-exports — business logic moved to app.services.submit_service
from app.services.submit_service import (
    tag_questions_batch,  # noqa: F401 — backward-compatible router re-export
    incremental_update_master_bank,  # noqa: F401 — backward-compatible router re-export
    background_generate_answer,  # noqa: F401 — backward-compatible router re-export
    persist_answer_generation_jobs,  # noqa: F401 — backward-compatible router re-export
    _get_current_position_for_user,
)


@router.post("/api/submit-stream-v2")
async def submit_data_stream_v2(
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
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
    submit_target = _normalize_target(target)
    # share 是“申请公共化”，不是普通用户直写公共题库。
    is_admin = bool(user.get("is_admin", 0))
    bank_target = "public" if submit_target == "share" and is_admin else "personal"
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

    # 统一接受服务（contracts §8）：旧 SSE 只创建根任务并订阅快照，
    # 执行一律交给 worker；web 进程内不再启动第二套可写 graph。
    return await _legacy_sse_via_accept_service(
        user=user,
        idempotency_key=idempotency_key,
        submit_target=submit_target,
        text=text,
        url=url,
        season=season,
        content_type=content_type,
        image_data=image_data,
        files=files,
        job_position=_get_current_position_for_user(user["id"]),
    )


# ── 上传任务化接口（后台 Job 模式） ──

# 旧 SSE 适配的快照轮询上限（每次 2 秒）；测试可调小
LEGACY_SSE_MAX_POLLS = 900


async def _legacy_sse_via_accept_service(
    *,
    user,
    idempotency_key,
    submit_target,
    text,
    url,
    season,
    content_type,
    image_data,
    files,
    job_position,
):
    """旧 SSE 适配：只创建根任务并订阅快照，执行交给 worker（AC-003）。"""

    import asyncio as _asyncio

    from app.services.upload_lifecycle import UploadFileMeta, UploadInputError
    from app.models.upload_contracts import UploadSnapshot
    from app.services.upload_retry_budget import build_snapshot_event

    named_files = [f for f in (files or []) if f and f.filename]
    file_metas = [
        UploadFileMeta(
            filename=f.filename,
            content_type=f.content_type or "",
            size=int(getattr(f, "size", 0) or 0),
        )
        for f in named_files
    ]
    images = [
        {"content_b64": base64.b64encode(img["content"]).decode("ascii"), "mime": img["mime"]}
        for img in image_data
    ]
    key = idempotency_key or str(uuid.uuid4())

    def _accept():
        with get_db_connection() as conn:
            conn.execute("BEGIN")
            try:
                result = accept_upload(
                    conn,
                    actor_id=user["id"],
                    actor_is_admin=bool(user.get("is_admin", 0)),
                    idempotency_key=key,
                    target_intent=submit_target,
                    source_type="interview",
                    text=text,
                    url=url,
                    season=season or "",
                    content_type=content_type or "",
                    position_id=None,
                    position_name=job_position or "",
                    files=file_metas,
                    images=images,
                    entry="legacy_sse",
                    job_position=job_position or "",
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    try:
        accepted = await run_db(_accept)
    except UploadInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    except ClientPolicyFieldError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except IdempotencyConflict:
        raise HTTPException(
            status_code=409,
            detail="该提交键已绑定不同内容，请使用新的提交键或查看已有任务",
        ) from None

    if accepted.get("dispatch_jobs"):
        await _dispatch_accepted_upload_jobs(accepted)

    terminal = {"completed", "failed", "partial_failed", "needs_action", "waiting_review"}

    def _load_snapshot():
        # Keep the legacy transport on the same question-level snapshot contract
        # as GET /api/upload-imports and its dedicated SSE endpoint.
        from app.routers.upload_imports import _snapshot as build_upload_snapshot
        from app.routers.upload_imports import _stage_counts

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM upload_imports WHERE id = ?", (accepted["import_id"],)
            ).fetchone()
            if row is None:
                return None
            return build_upload_snapshot(
                row,
                counts=_stage_counts(conn, accepted["import_id"]),
                conn=conn,
                actor_is_admin=bool(user.get("is_admin")),
            )

    async def event_stream():
        last_revision = -1
        try:
            for _ in range(LEGACY_SSE_MAX_POLLS):
                loaded = await run_db(_load_snapshot)
                if loaded is None:
                    yield f"data: {json.dumps({'type': 'error', 'message': '任务不存在'}, ensure_ascii=False)}\n\n"
                    return
                snapshot = UploadSnapshot(
                    **{
                        field: loaded[field]
                        for field in UploadSnapshot.model_fields
                        if field in loaded
                    }
                )
                event = build_snapshot_event(snapshot)
                if int(snapshot.revision) > last_revision:
                    last_revision = int(snapshot.revision)
                    yield f"event: snapshot\nid: {last_revision}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                if snapshot.status in terminal:
                    return
                await _asyncio.sleep(2)
        finally:
            # 断开连接不取消后台任务
            pass

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


def _normalize_target(target: Optional[str]) -> str:
    """target 必须是 private/share；非法值 400，禁止静默改成 private。"""

    normalized = (target or "private").lower()
    if normalized not in ("private", "share"):
        raise HTTPException(
            status_code=400, detail="不支持的提交目标，仅支持 private 或 share"
        )
    return normalized


@router.post("/api/submit-jobs")
async def create_submit_job(
    user: dict = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
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
    submit_target = _normalize_target(target)
    # 分享意愿：share → 公共审核队列；private → 个人路径（目标内部映射）
    bank_target = "personal" if submit_target == "private" else "public"
    if url:
        check_owner = user["id"] if bank_target == "personal" else None
        if await run_db(lambda: _check_duplicate_url_sync(url, owner_id=check_owner)):
            raise HTTPException(
                status_code=409, detail="该链接的内容已存在于数据库中，请勿重复上传！"
            )
    # ── 文件元信息先校验：超限/非图片在读取内容前拒绝，不产生幽灵 job ──
    named_files = [f for f in (files or []) if f and f.filename]
    file_metas = [
        UploadFileMeta(
            filename=f.filename,
            content_type=f.content_type or "",
            size=int(getattr(f, "size", 0) or 0),
        )
        for f in named_files
    ]
    try:
        validate_submission(text=text, files=file_metas)
    except UploadInputError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None

    # ── 读取文件到内存（已通过大小/类型校验） ──
    image_data = []
    for file in named_files:
        content = await file.read()
        real_mime = _magic.from_buffer(content[:2048], mime=True)
        if real_mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"文件 {file.filename} 不是有效的图片文件（检测到: {real_mime}）",
            )
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

    # 统一接受服务（稳定 import_id + 幂等键 + 同事务落库）
    idempotency_key = idempotency_key or str(uuid.uuid4())

    def _accept():
        with get_db_connection() as conn:
            conn.execute("BEGIN")
            try:
                result = accept_upload(
                    conn,
                    actor_id=user["id"],
                    actor_is_admin=bool(user.get("is_admin", 0)),
                    idempotency_key=idempotency_key,
                    target_intent=submit_target,
                    source_type="interview",
                    text=text,
                    url=url,
                    season=season or "",
                    content_type=content_type or "",
                    position_id=None,
                    position_name=payload["job_position"] or "",
                    files=file_metas,
                    images=image_data,
                    entry="api",
                    job_position=payload["job_position"] or "",
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    try:
        accepted = await run_db(_accept)
    except ClientPolicyFieldError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except IdempotencyConflict:
        raise HTTPException(
            status_code=409,
            detail="该提交键已绑定不同内容，请使用新的提交键或查看已有任务",
        ) from None

    dispatched_count, dispatch_error = await _dispatch_accepted_upload_jobs(accepted)
    arq_scheduled = dispatched_count == len(accepted.get("dispatch_jobs", []))

    return JSONResponse(
        status_code=202,
        content={
            **accepted,
            "idempotency_key": idempotency_key,
            "job_status": "queued" if arq_scheduled else "pending",
            "dispatch_error": dispatch_error,
            "message": (
                "上传任务已接受"
                if accepted["created"]
                else "该提交已存在，返回原任务"
            ),
        },
    )


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
    """创建一次新的上传尝试，保留原任务作为审计记录。

    R03：先解析业务根任务，再复用上传恢复的同一规划器，保证新 job
    绑定 root + attempt + work_key（不只看直接子任务、不丢失根归属）。
    """

    def _create_retry():
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                original = conn.execute(
                    "SELECT id, job_type, status, created_by, progress_total "
                    "FROM jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
                if not original or original["created_by"] != user["id"]:
                    raise HTTPException(status_code=404, detail="任务不存在")
                if original["job_type"] != "submit_import":
                    raise HTTPException(status_code=400, detail="该任务不支持重新处理")
                if original["status"] != "failed":
                    raise HTTPException(status_code=409, detail="只有失败任务可以重新处理")

                # R03：旧 retry 优先走根任务恢复规划器（同 root、绑定 attempt、幂等）；
                # 纯历史 job（无 v2 root 归属）回退到旧子任务行为，不破坏老界面重试。
                from app.services.upload_lifecycle import (
                    UploadRestoreError,
                    restore_upload,
                )

                try:
                    restored = restore_upload(
                        conn,
                        actor_id=int(user["id"]),
                        job_id=int(job_id),
                    )
                    new_root_id = restored.get("planned_job_id")
                    if not new_root_id:
                        # 幂等路径：已有在途 job 直接返回
                        active_child = conn.execute(
                            "SELECT id, job_type FROM jobs WHERE root_import_id = ? "
                            "AND status IN ('pending', 'queued', 'running') "
                            "ORDER BY id DESC LIMIT 1",
                            (restored["import_id"],),
                        ).fetchone()
                        if active_child:
                            conn.commit()
                            return {
                                "job_id": int(active_child["id"]),
                                "job_type": active_child["job_type"],
                                "created": False,
                            }
                        raise HTTPException(status_code=409, detail="无法规划恢复工作")
                    planned_job = conn.execute(
                        "SELECT job_type FROM jobs WHERE id = ?", (new_root_id,)
                    ).fetchone()
                    if planned_job is None:
                        raise HTTPException(status_code=409, detail="无法规划恢复工作")
                    conn.commit()
                    return {
                        "job_id": new_root_id,
                        "job_type": planned_job["job_type"],
                        "created": restored["created_attempt"],
                    }
                except UploadRestoreError as leaky:
                    if leaky.code not in ("NOT_FOUND", "LEGACY_MAPPING_AMBIGUOUS"):
                        raise HTTPException(status_code=409, detail=f"{leaky.code}: {leaky}") from None
                    # 无 root 归属的历史任务：走旧子任务重试路径
                    active_child = conn.execute(
                        "SELECT id, job_type FROM jobs WHERE parent_job_id = ? "
                        "AND job_type = 'submit_import' "
                        "AND status IN ('pending', 'queued', 'running') "
                        "ORDER BY id DESC LIMIT 1",
                        (job_id,),
                    ).fetchone()
                    if active_child:
                        conn.commit()
                        return {
                            "job_id": int(active_child["id"]),
                            "job_type": active_child["job_type"],
                            "created": False,
                        }

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
                    return {
                        "job_id": new_job_id,
                        "job_type": "submit_import",
                        "created": True,
                    }
            except HTTPException:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise

    retry = await run_db(_create_retry)
    new_job_id = retry["job_id"]
    if not retry["created"]:
        return {"job_id": new_job_id, "status": "queued", "created": False}

    dispatch_error = None
    try:
        from app.services.job_lifecycle import mark_job_dispatched

        if retry.get("job_type") == "credential_preflight":
            from app.worker_enqueue import enqueue_credential_preflight_job

            arq_job = await enqueue_credential_preflight_job(new_job_id)
        else:
            from app.worker import enqueue_submit_import_job

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

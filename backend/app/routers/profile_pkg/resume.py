"""简历管理端点"""
import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user
from app.db.connection import run_db
from app.services.llm import raw_llm_call, stream_llm_messages, _extract_json
from app.core.prompts import (
    build_resume_optimize_points_prompt,
    build_resume_optimize_text_prompt,
)

logger = logging.getLogger("interview-boss")

router = APIRouter()

# 简历上传大小上限（字节），在 file.read() 之前用 Content-Length 提前拦截
_MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/api/profile/resume")
async def upload_resume(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """上传简历 PDF → 解析 → 保存到数据库"""
    from app.services import resume_service

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    # 用 Content-Length 提前拦截超大文件，避免全量读入内存放大
    if file.size and file.size > _MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，请上传 10MB 以内的 PDF")

    try:
        content = await file.read()
        if len(content) > _MAX_RESUME_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="文件过大，请上传 10MB 以内的 PDF")

        # audit D14 / spec Task B M40：pdfplumber 是 CPU 密集解析，必须移到线程池，
        # 避免在事件循环内同步执行阻塞全站（10MB 恶意/扫描件可卡住所有请求）
        raw_text = await asyncio.to_thread(resume_service.extract_pdf_text, content)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="无法从 PDF 中提取文本，可能是扫描件或空白文件")

        if len(raw_text) > 50000:
            raw_text = raw_text[:50000] + "\n\n...(文本过长，已截断)"

        resume_id = await run_db(lambda: resume_service.save_resume(
            user['id'], file.filename, raw_text
        ))
        return {"status": "success", "id": resume_id, "filename": file.filename}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"简历上传失败: {e}")
        raise HTTPException(status_code=500, detail="简历上传失败，请稍后重试")


@router.get("/api/profile/resume")
async def get_resume(user: dict = Depends(get_current_user)):
    """获取当前用户的简历信息（不含 raw_text，仅元数据）"""
    from app.services import resume_service

    resume = await run_db(lambda: resume_service.get_resume(user['id']))
    if not resume:
        return {"has_resume": False, "resume": None}

    return {
        "has_resume": True,
        "resume": {
            "id": resume["id"],
            "filename": resume["filename"],
            "created_at": resume["created_at"],
        }
    }


@router.delete("/api/profile/resume")
async def delete_resume(user: dict = Depends(get_current_user)):
    """删除当前用户的简历"""
    from app.services import resume_service

    deleted = await run_db(lambda: resume_service.delete_resume(user['id']))
    if not deleted:
        raise HTTPException(status_code=404, detail="未找到简历")

    return {"status": "success", "message": "简历已删除"}


@router.get("/api/profile/resume/text")
async def get_resume_text(user: dict = Depends(get_current_user)):
    """获取当前用户简历的原始文本（用于原文预览）"""
    from app.services import resume_service

    raw_text = await run_db(lambda: resume_service.get_resume_text(user['id']))
    if raw_text is None:
        raise HTTPException(status_code=404, detail="未找到简历")
    return {"raw_text": raw_text}


@router.get("/api/profile/resume/optimization")
async def get_optimization(user: dict = Depends(get_current_user)):
    """获取最新简历优化结果"""
    from app.services import resume_service

    opt = await run_db(lambda: resume_service.get_optimization(user['id']))
    if not opt:
        return {"has_optimization": False, "optimization": None}
    return {"has_optimization": True, "optimization": opt}


async def optimize_resume_event_stream(user: dict, position: str):
    """简历优化 SSE 事件流：points → delta* → done/error"""
    from app.services import resume_service

    try:
        raw_text = await run_db(lambda: resume_service.get_resume_text(user['id']))
        if not raw_text:
            yield f"data: {json.dumps({'type': 'error', 'message': '未找到简历，请先上传'})}\n\n"
            return

        # 第一阶段：非流式生成要点 JSON
        try:
            points_raw = await raw_llm_call(
                user["id"],
                messages=[{
                    "role": "user",
                    "content": build_resume_optimize_points_prompt(raw_text, position),
                }],
                temperature=0.3,
                max_tokens=1024,
                response_format={"type": "json_object"},
            )
            points_data = _extract_json(points_raw)
            points = points_data if isinstance(points_data, list) else points_data.get("points", [])
            if not isinstance(points, list):
                points = []
        except Exception as e:
            logger.warning(f"简历优化要点生成失败，跳过要点: {e}")
            points = []

        yield f"data: {json.dumps({'type': 'points', 'points': points}, ensure_ascii=False)}\n\n"

        # 第二阶段：流式生成优化版全文
        text_chunks = []
        async for chunk in stream_llm_messages(
            messages=[{
                "role": "user",
                "content": build_resume_optimize_text_prompt(raw_text, position),
            }],
            user_id=user["id"],
            temperature=0.4,
            # audit D14 / spec Task C M41：显式下发 max_tokens 防服务端默认值截断
            max_tokens=4096,
        ):
            text_chunks.append(chunk)
            yield f"data: {json.dumps({'type': 'delta', 'content': chunk}, ensure_ascii=False)}\n\n"

        optimized_text = "".join(text_chunks)
        if not optimized_text.strip():
            raise RuntimeError("模型未生成优化内容")

        await run_db(lambda: resume_service.save_optimization(
            user["id"], position, points, optimized_text
        ))

        yield f"data: {json.dumps({'type': 'done', 'position': position}, ensure_ascii=False)}\n\n"
    except Exception:
        logger.exception("简历优化失败")
        yield f"data: {json.dumps({'type': 'error', 'message': '优化失败，请稍后重试'}, ensure_ascii=False)}\n\n"


@router.post("/api/profile/resume/optimize")
async def optimize_resume(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """生成简历优化版（SSE 流式）"""
    position = (body.get("position") or "").strip()
    if not position:
        raise HTTPException(status_code=400, detail="请提供目标岗位")

    from app.services import resume_service

    has = await run_db(lambda: resume_service.has_resume(user['id']))
    if not has:
        raise HTTPException(status_code=400, detail="请先上传简历")

    return StreamingResponse(
        optimize_resume_event_stream(user, position),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )

"""简历管理端点"""
import asyncio
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from app.core.auth import get_current_user
from app.db.connection import run_db

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

    # audit D10 / spec Task G2 M45：轻量 meta 查询，不 SELECT raw_text
    resume = await run_db(lambda: resume_service.get_resume_meta(user['id']))
    if not resume:
        return {"has_resume": False, "resume": None}

    return {
        "has_resume": True,
        "resume": resume,
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

class OptimizeResumeRequest(BaseModel):
    """简历优化请求体（audit D14 / spec Task G4 M45）

    用 Pydantic 模型代替裸 dict：类型错误（如 position 传数组）由 FastAPI 返回
    422 而非内部 500；超长岗位名（>100）同样被模型层拒绝。
    """
    position: Optional[str] = Field(None, max_length=100)


@router.post("/api/profile/resume/optimize")
async def optimize_resume(
    body: OptimizeResumeRequest,
    user: dict = Depends(get_current_user),
):
    """生成简历优化版（SSE 流式）"""
    position = (body.position or "").strip()
    if not position:
        raise HTTPException(status_code=400, detail="请提供目标岗位")

    from app.services import resume_service

    has = await run_db(lambda: resume_service.has_resume(user['id']))
    if not has:
        raise HTTPException(status_code=400, detail="请先上传简历")

    return StreamingResponse(
        resume_service.optimize_resume_event_stream(user["id"], position),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
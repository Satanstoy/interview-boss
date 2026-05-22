"""简历管理端点"""
import logging
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from app.core.auth import get_current_user
from app.db.connection import run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.post("/api/profile/resume")
async def upload_resume(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """上传简历 PDF → 解析 → 保存到数据库"""
    from app.services import resume_service

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    try:
        content = await file.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件过大，请上传 10MB 以内的 PDF")

        raw_text = resume_service.extract_pdf_text(content)
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

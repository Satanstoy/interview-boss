"""分类体系管理端点"""
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db, get_taxonomy_for_position

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.get("/api/profile/taxonomy")
async def get_taxonomy(user: dict = Depends(get_current_user)):
    """获取当前岗位的分类体系配置（登录即可访问，不需要 admin）"""
    return await run_db(lambda: get_taxonomy_for_position())


@router.post("/api/profile/taxonomy/generate")
async def generate_taxonomy(user: dict = Depends(get_current_user)):
    """调用LLM生成推荐的分类体系（不自动保存，需用户确认）"""
    from app.services.taxonomy_suggest import generate_taxonomy_suggestion
    from app.db.connection import get_user_job_position

    _, position = await run_db(lambda: get_user_job_position(user['id']))
    if not position:
        raise HTTPException(status_code=400, detail="请先选择目标岗位")

    try:
        suggestion = await generate_taxonomy_suggestion(position, user_id=user['id'])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except TimeoutError:
        raise HTTPException(status_code=504, detail="AI生成超时，请稍后重试")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"生成分类建议失败: {error_msg}")

        if "500" in error_msg and "Internal Server Error" in error_msg:
            detail = "AI服务暂时不可用，请稍后重试"
        elif "Connection" in error_msg or "timeout" in error_msg.lower():
            detail = "网络连接失败，请检查网络后重试"
        elif "401" in error_msg or "403" in error_msg:
            detail = "AI服务认证失败，请检查API配置"
        else:
            detail = f"AI生成失败: {error_msg[:100]}"

        raise HTTPException(status_code=500, detail=detail)

    return {"position": position, "categories": suggestion}


@router.post("/api/profile/taxonomy/confirm")
async def confirm_taxonomy(req: dict, user: dict = Depends(get_current_user)):
    """用户确认采纳AI生成的分类体系（保存为用户个人分类）"""
    from app.db.connection import get_user_job_position, save_taxonomy_for_position

    categories = req.get("categories")
    if not categories or not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="需要提供 categories 列表")

    _, position = await run_db(lambda: get_user_job_position(user['id']))
    if not position:
        raise HTTPException(status_code=400, detail="请先选择目标岗位")

    await run_db(lambda: save_taxonomy_for_position(position, categories, source='user', owner_id=user['id']))
    return {"status": "success", "position": position}


@router.post("/api/profile/taxonomy/save-personal")
async def save_personal_taxonomy(req: dict, user: dict = Depends(get_current_user)):
    """保存个人分类体系"""
    from app.db.operations import create_personal_taxonomy
    from app.db.connection import get_user_job_position

    categories = req.get("categories")
    if not categories or not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="需要提供 categories 列表")

    _, position = await run_db(lambda: get_user_job_position(user['id']))
    if not position:
        raise HTTPException(status_code=400, detail="请先选择目标岗位")

    try:
        result = await create_personal_taxonomy(position, categories, user)
        return result
    except Exception as e:
        logger.error(f"保存个人分类失败: {e}")
        raise HTTPException(status_code=500, detail="保存失败")


@router.post("/api/profile/taxonomy/{taxonomy_id}/share")
async def share_taxonomy_endpoint(taxonomy_id: int, user: dict = Depends(get_current_user)):
    """分享分类体系"""
    from app.db.operations import share_taxonomy

    try:
        result = await share_taxonomy(taxonomy_id, user)
        return result
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"分享分类失败: {e}")
        raise HTTPException(status_code=500, detail="分享失败")


@router.get("/api/profile/taxonomy/public")
async def get_public_taxonomies(user: dict = Depends(get_current_user)):
    """获取公开分享的分类体系列表"""
    from app.db.operations import get_public_shared_taxonomies

    try:
        result = await get_public_shared_taxonomies(user)
        return {"taxonomies": result}
    except Exception as e:
        logger.error(f"获取公开分类失败: {e}")
        raise HTTPException(status_code=500, detail="获取失败")


@router.delete("/api/profile/taxonomy/{taxonomy_id}/public")
async def delete_public_taxonomy(taxonomy_id: int, admin: dict = Depends(get_admin_user)):
    """删除公开分类（仅管理员）"""
    from app.db.operations import delete_taxonomy_by_id

    try:
        result = delete_taxonomy_by_id(taxonomy_id)
        if not result:
            raise HTTPException(status_code=404, detail="分类不存在")
        return {"status": "success", "message": "已删除公开分类"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除公开分类失败: {e}")
        raise HTTPException(status_code=500, detail="删除失败")

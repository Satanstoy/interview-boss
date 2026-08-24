"""分类体系管理端点"""
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import (
    get_db_connection,
    get_taxonomy_for_position,
    get_user_job_position,
    run_db,
)

logger = logging.getLogger("interview-boss")

router = APIRouter()

_PERSONAL_TAXONOMY_GONE = "个人分类体系已停用，岗位分类由系统和管理员统一维护"


@router.get("/api/profile/taxonomy")
async def get_taxonomy(user: dict = Depends(get_current_user)):
    """获取当前岗位的分类体系配置（登录即可访问，不需要 admin）"""
    _, position = await run_db(lambda: get_user_job_position(user["id"]))
    return await run_db(lambda: get_taxonomy_for_position(position=position))


@router.get("/api/profile/taxonomy/system")
async def get_system_taxonomy(position: str, admin: dict = Depends(get_admin_user)):
    """管理员按岗位读取系统 taxonomy，供分类管理页面切换岗位。"""
    position = position.strip()
    if not position:
        raise HTTPException(status_code=400, detail="需要提供 position")
    return await run_db(lambda: get_taxonomy_for_position(position=position))


@router.put("/api/profile/taxonomy/system")
async def update_system_taxonomy(req: dict, admin: dict = Depends(get_admin_user)):
    """管理员更新现有岗位的系统 taxonomy（cat1/cat2/tags）。"""
    position = str(req.get("position") or "").strip()
    categories = req.get("categories")
    tags = req.get("tags")
    if not position:
        raise HTTPException(status_code=400, detail="需要提供 position")
    if not isinstance(categories, list) or not categories:
        raise HTTPException(status_code=400, detail="categories 必须是非空数组")
    if not isinstance(tags, list) or not tags or any(not isinstance(tag, str) or not tag.strip() for tag in tags):
        raise HTTPException(status_code=400, detail="tags 必须是非空字符串数组")
    normalized_categories = []
    seen_cat1 = set()
    for category in categories:
        if not isinstance(category, dict) or not str(category.get("cat1") or "").strip():
            raise HTTPException(status_code=400, detail="每个分类必须包含 cat1")
        cat1 = str(category["cat1"]).strip()
        if cat1 in seen_cat1:
            raise HTTPException(status_code=400, detail="cat1 不能重复")
        seen_cat1.add(cat1)
        children = category.get("children")
        if not isinstance(children, list) or not children or any(not isinstance(child, str) or not child.strip() for child in children):
            raise HTTPException(status_code=400, detail="每个分类必须包含非空 children")
        normalized_children = [str(child).strip() for child in children]
        if len(normalized_children) != len(set(normalized_children)):
            raise HTTPException(status_code=400, detail="同一 cat1 下的 cat2 不能重复")
        normalized_categories.append(
            {
                "cat1": cat1,
                "children": normalized_children,
            }
        )
    normalized_tags = list(dict.fromkeys(tag.strip() for tag in tags))

    def _update():
        with get_db_connection() as conn:
            position_columns = {
                row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()
            }
            deleted_filter = "AND (is_deleted = 0 OR is_deleted IS NULL)" if "is_deleted" in position_columns else ""
            position_row = conn.execute(
                f"SELECT id FROM job_positions WHERE name = ? {deleted_filter}",
                (position,),
            ).fetchone()
            if not position_row:
                raise HTTPException(status_code=404, detail="岗位不存在或已下线")

            taxonomy_columns = {
                row[1] for row in conn.execute("PRAGMA table_info('taxonomy')").fetchall()
            }
            if "tags_json" not in taxonomy_columns:
                raise HTTPException(status_code=409, detail="数据库尚未完成 taxonomy 迁移")
            categories_json = json.dumps(normalized_categories, ensure_ascii=False)
            tags_json = json.dumps(normalized_tags, ensure_ascii=False)
            existing = conn.execute(
                "SELECT id FROM taxonomy WHERE position_name = ? AND source = 'system' AND owner_id IS NULL",
                (position,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE taxonomy SET categories_json = ?, tags_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (categories_json, tags_json, existing[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO taxonomy "
                    "(position_name, categories_json, tags_json, source, owner_id, is_default, is_public) "
                    "VALUES (?, ?, ?, 'system', NULL, 0, 0)",
                    (position, categories_json, tags_json),
                )
            conn.commit()

    await run_db(_update)
    return {
        "status": "success",
        "position": position,
        "categories": normalized_categories,
        "tags": normalized_tags,
    }


@router.post("/api/profile/taxonomy/generate")
async def generate_taxonomy(user: dict = Depends(get_current_user)):
    """Legacy endpoint retained as an explicit no-op after taxonomy centralization."""
    raise HTTPException(status_code=410, detail=_PERSONAL_TAXONOMY_GONE)


@router.post("/api/profile/taxonomy/confirm")
async def confirm_taxonomy(req: dict, user: dict = Depends(get_current_user)):
    """Reject the former user-owned taxonomy write path."""
    raise HTTPException(status_code=410, detail=_PERSONAL_TAXONOMY_GONE)


@router.post("/api/profile/taxonomy/save-personal")
async def save_personal_taxonomy(req: dict, user: dict = Depends(get_current_user)):
    """Reject the former user-owned taxonomy write path."""
    raise HTTPException(status_code=410, detail=_PERSONAL_TAXONOMY_GONE)


@router.post("/api/profile/taxonomy/{taxonomy_id}/share")
async def share_taxonomy_endpoint(taxonomy_id: int, user: dict = Depends(get_current_user)):
    """Reject the former taxonomy-sharing path."""
    raise HTTPException(status_code=410, detail=_PERSONAL_TAXONOMY_GONE)


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

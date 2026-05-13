import re
import json
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.auth import get_admin_user, get_current_user
from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_taxonomy_for_position
from app.core.config import _reload_from_db, _sync_env_file
from app.core import config as app_config
from app.models.schemas import ProfileUpdateRequest

limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger("interview-boss")

router = APIRouter()

ALLOWED_PROFILE_KEYS = {
    "active_season", "llm_model",
    "llm_api_key", "llm_base_url", "llm_timeout",
    "taxonomy_config"
}

_SENSITIVE_KEYS = {"llm_api_key"}

# 必填字段：不允许提交空值
_REQUIRED_NON_EMPTY = {"llm_model", "llm_base_url"}


_MAX_POSITION_LEN = 30


def _get_available_positions() -> list:
    """从 taxonomy + job_positions 合并读取所有岗位列表"""
    with get_db_connection() as conn:
        tax_rows = conn.execute("SELECT position_name FROM taxonomy ORDER BY position_name").fetchall()
        # 排除已软删除的岗位（兼容 is_deleted 字段不存在的情况）
        try:
            pos_rows = conn.execute("SELECT name FROM job_positions WHERE is_deleted = 0 OR is_deleted IS NULL ORDER BY name").fetchall()
        except Exception:
            pos_rows = conn.execute("SELECT name FROM job_positions ORDER BY name").fetchall()
        seen = set()
        result = []
        for r in tax_rows:
            name = r['position_name']
            if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                seen.add(name)
                result.append(name)
        for r in pos_rows:
            name = r['name']
            if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                seen.add(name)
                result.append(name)
        return result if result else [DEFAULT_TAXONOMY["job_position"]]


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


@router.get("/api/profile/public")
async def get_public_profile(user: dict = Depends(get_current_user)):
    """公开配置（普通用户可访问）：岗位列表、分类配置、招聘季"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
            settings_map = {r['key']: r['value'] for r in rows}
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
            season_list = [r['season'] for r in seasons]
            active = settings_map.get('active_season', '')
            if active and active not in season_list:
                season_list.append(active)
                season_list.sort()
            # 合并岗位列表查询（避免在 async 上下文中阻塞）
            tax_rows = conn.execute("SELECT position_name FROM taxonomy ORDER BY position_name").fetchall()
            try:
                pos_rows = conn.execute("SELECT name FROM job_positions WHERE is_deleted = 0 OR is_deleted IS NULL ORDER BY name").fetchall()
            except Exception:
                pos_rows = conn.execute("SELECT name FROM job_positions ORDER BY name").fetchall()
            seen = set()
            positions = []
            for r in tax_rows:
                name = r['position_name']
                if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                    seen.add(name)
                    positions.append(name)
            for r in pos_rows:
                name = r['name']
                if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                    seen.add(name)
                    positions.append(name)
            if not positions:
                positions = [DEFAULT_TAXONOMY["job_position"]]
            # 用户当前岗位（优先 personal_position）
            user_row = conn.execute(
                "SELECT u.personal_position, jp.name as position_name FROM users u "
                "LEFT JOIN job_positions jp ON u.current_position_id = jp.id WHERE u.id = ?",
                (user['id'],)
            ).fetchone()
        return settings_map, season_list, positions, user_row

    settings, used_seasons, available_positions, user_row = await run_db(_query)
    current_pos = (
        (user_row['personal_position'] if user_row and user_row['personal_position'] else None)
        or (user_row['position_name'] if user_row and user_row['position_name'] else None)
        or settings.get('current_job_position')
        or DEFAULT_TAXONOMY['job_position']
    )
    taxonomy_data = await run_db(lambda: get_taxonomy_for_position(current_pos, user_id=user['id']))

    return {
        "settings": {
            "current_job_position": current_pos,
            "available_positions": available_positions,
            "taxonomy_config": json.dumps(taxonomy_data, ensure_ascii=False),
            "active_season": settings.get('active_season', ''),
        },
        "available_seasons": used_seasons,
    }


@router.get("/api/profile/llm")
async def get_my_llm_config(user: dict = Depends(get_current_user)):
    """读取当前用户的 LLM 配置（密钥掩码返回）"""

    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT api_key, base_url, model, timeout FROM user_llm_config WHERE user_id = ?",
                (user['id'],)
            ).fetchone()
            return dict(row) if row else None

    cfg = await run_db(_query)
    if not cfg:
        return {"configured": False, "settings": {}}

    return {
        "configured": True,
        "settings": {
            "llm_api_key": _mask_key(cfg["api_key"]) if cfg["api_key"] else "",
            "llm_api_key_set": bool(cfg["api_key"]),
            "llm_base_url": cfg["base_url"] or "",
            "llm_model": cfg["model"] or "gpt-4o",
            "llm_timeout": cfg["timeout"] or 120,
        }
    }


@router.put("/api/profile/llm")
async def update_my_llm_config(req: dict, user: dict = Depends(get_current_user)):
    """更新当前用户的 LLM 配置"""

    api_key = (req.get("llm_api_key") or "").strip()
    base_url = (req.get("llm_base_url") or "").strip()
    model = (req.get("llm_model") or "").strip()
    timeout = req.get("llm_timeout")

    # 验证必填字段
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL 不能为空")

    # URL 格式校验
    import re
    _URL_RE = re.compile(r'^https?://[^\s<>"\']+$', re.IGNORECASE)
    if not _URL_RE.match(base_url):
        raise HTTPException(status_code=400, detail="Base URL 格式无效，必须以 http:// 或 https:// 开头")

    # 超时范围校验
    if timeout is not None:
        try:
            timeout = int(timeout)
            timeout = max(5, min(timeout, 600))
        except (ValueError, TypeError):
            timeout = 120
    else:
        timeout = 120

    def _upsert():
        with get_db_connection() as conn:
            # 如果 api_key 为空，保留原有值
            existing = conn.execute(
                "SELECT api_key FROM user_llm_config WHERE user_id = ?",
                (user['id'],)
            ).fetchone()
            if not api_key and existing and existing['api_key']:
                final_key = existing['api_key']
            else:
                final_key = api_key

            conn.execute(
                "INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET api_key = excluded.api_key, base_url = excluded.base_url, "
                "model = excluded.model, timeout = excluded.timeout, updated_at = CURRENT_TIMESTAMP",
                (user['id'], final_key, base_url, model, timeout)
            )
            conn.commit()

    await run_db(_upsert)

    # 清除该用户的 client 缓存
    from app.services.llm import clear_user_client_cache
    clear_user_client_cache(user['id'])

    return {"status": "success", "message": "LLM 配置已保存"}


@router.delete("/api/profile/llm")
async def delete_my_llm_config(user: dict = Depends(get_current_user)):
    """删除当前用户的 LLM 配置"""

    def _delete():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM user_llm_config WHERE user_id = ?", (user['id'],))
            conn.commit()

    await run_db(_delete)

    # 清除该用户的 client 缓存
    from app.services.llm import clear_user_client_cache
    clear_user_client_cache(user['id'])

    return {"status": "success", "message": "LLM 配置已清除"}


@router.get("/api/profile")
async def get_profile(admin: dict = Depends(get_admin_user)):
    """读取全部用户配置（API Key 掩码返回）— 仅管理员"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
            settings_map = {r['key']: r['value'] for r in rows}
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
            season_list = [r['season'] for r in seasons]
            # 确保当前 active_season 也在可选列表中
            active = settings_map.get('active_season', '')
            if active and active not in season_list:
                season_list.append(active)
                season_list.sort()
        return settings_map, season_list

    settings, used_seasons = await run_db(_query)

    # 非敏感字段：DB 为空时回退到 .env / config 全局变量
    _FALLBACK = {
        "llm_model": app_config.LLM_MODEL or "gpt-4o",
        "llm_base_url": app_config.LLM_BASE_URL or "",
        "llm_timeout": str(app_config.LLM_TIMEOUT or "120"),
    }
    for k, fallback in _FALLBACK.items():
        if not settings.get(k):
            settings[k] = fallback

    # 敏感字段：DB 为空时检查 .env 中是否有值
    _ENV_FALLBACK = {
        "llm_api_key": app_config.LLM_API_KEY,
    }

    # 掩码处理 API Key
    display_settings = {}
    for k, v in settings.items():
        if k in _SENSITIVE_KEYS:
            display_settings[k] = _mask_key(v) if v else ""
            display_settings[f"{k}_set"] = bool(v)
        else:
            display_settings[k] = v

    # 敏感字段：DB 没有但 .env 有的情况
    for k, env_val in _ENV_FALLBACK.items():
        if k not in display_settings or not display_settings[f"{k}_set"]:
            if env_val:
                display_settings[k] = _mask_key(env_val)
                display_settings[f"{k}_set"] = True

    # 多岗位支持：优先从 users 表读取当前用户的岗位，fallback 到全局设置
    available_positions = _get_available_positions()
    with get_db_connection() as conn:
        user_row = conn.execute(
            "SELECT u.personal_position, jp.name as position_name FROM users u "
            "LEFT JOIN job_positions jp ON u.current_position_id = jp.id WHERE u.id = ?",
            (admin['id'],)
        ).fetchone()
    current_pos = (
        (user_row['personal_position'] if user_row and user_row['personal_position'] else None)
        or (user_row['position_name'] if user_row and user_row['position_name'] else None)
        or settings.get('current_job_position')
        or DEFAULT_TAXONOMY['job_position']
    )
    # 从 taxonomy 表读取当前岗位的分类配置（优先用户个人分类）
    taxonomy_data = get_taxonomy_for_position(current_pos, user_id=admin['id'])

    display_settings['current_job_position'] = current_pos
    display_settings['available_positions'] = available_positions
    display_settings['taxonomy_config'] = json.dumps(taxonomy_data, ensure_ascii=False)

    return {"settings": display_settings, "available_seasons": used_seasons}


@router.put("/api/profile")
async def update_profile(req: ProfileUpdateRequest, admin: dict = Depends(get_admin_user)):
    """批量更新用户配置"""

    invalid = set(req.settings.keys()) - ALLOWED_PROFILE_KEYS
    if invalid:
        raise HTTPException(status_code=400, detail=f"不允许的配置项: {invalid}")

    # 对于 API Key，空值表示不更新（保留原值）
    filtered = {k: v for k, v in req.settings.items() if not (k in _SENSITIVE_KEYS and not v)}

    # 必填字段不允许空值
    empty_required = [k for k in _REQUIRED_NON_EMPTY if k in filtered and not str(filtered[k]).strip()]
    if empty_required:
        labels = {
            "llm_model": "主模型名称",
            "llm_base_url": "主模型 Base URL",
        }
        names = "、".join(labels.get(k, k) for k in empty_required)
        raise HTTPException(status_code=400, detail=f"{names} 不能为空")

    # taxonomy_config JSON 格式校验 + 写入 taxonomy 表
    if "taxonomy_config" in filtered:
        try:
            tc = json.loads(filtered["taxonomy_config"]) if isinstance(filtered["taxonomy_config"], str) else filtered["taxonomy_config"]
            if not isinstance(tc.get("categories"), list):
                raise ValueError("categories 字段必须是数组")
            position = tc.get("job_position", get_current_job_position())
            from app.db.connection import save_taxonomy_for_position
            await run_db(lambda: save_taxonomy_for_position(position, tc["categories"], source='user', owner_id=admin['id']))
            del filtered["taxonomy_config"]  # 不写入 user_profile
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            raise HTTPException(status_code=400, detail=f"taxonomy_config 格式无效: {e}")

    # URL 格式校验
    _URL_RE = re.compile(r'^https?://[^\s<>"\']+$', re.IGNORECASE)
    for k, v in filtered.items():
        if k.endswith('_base_url') and v:
            if not _URL_RE.match(v.strip()):
                raise HTTPException(status_code=400, detail=f"Base URL 格式无效，URL 必须以 http:// 或 https:// 开头")

    if not filtered:
        return {"status": "success", "message": "无需更新"}

    def _update():
        with get_db_connection() as conn:
            for k, v in filtered.items():
                conn.execute(
                    "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                    (k, v)
                )
            conn.commit()

    try:
        await run_db(_update)
        _reload_from_db()
        _sync_env_file(filtered)
        return {"status": "success", "message": "配置已保存（已同步到 .env）"}
    except Exception as e:
        logger.exception("保存配置失败")
        raise HTTPException(status_code=500, detail="保存配置失败，请查看服务端日志")


@router.get("/api/profile/taxonomy")
async def get_taxonomy(user: dict = Depends(get_current_user)):
    """获取当前岗位的分类体系配置（登录即可访问，不需要 admin）"""
    return await run_db(lambda: get_taxonomy_for_position())


@router.post("/api/profile/taxonomy/generate")
async def generate_taxonomy(user: dict = Depends(get_current_user)):
    """调用LLM生成推荐的分类体系（不自动保存，需用户确认）"""
    from app.services.taxonomy_suggest import generate_taxonomy_suggestion
    from app.db.connection import get_user_job_position

    # 获取用户的个人岗位，而不是全局岗位
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

        # 区分不同类型的错误
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

    # 获取用户的个人岗位，而不是全局岗位
    _, position = await run_db(lambda: get_user_job_position(user['id']))
    if not position:
        raise HTTPException(status_code=400, detail="请先选择目标岗位")

    # 保存为用户个人分类
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


@router.put("/api/profile/my-position")
async def switch_my_position(req: dict, user: dict = Depends(get_current_user)):
    """普通用户切换个人岗位（仅对自己生效，不写入公共 job_positions 表）"""
    position_name = req.get("position", "").strip()
    if not position_name:
        raise HTTPException(status_code=400, detail="需要提供 position")
    if len(position_name) > 30:
        raise HTTPException(status_code=400, detail="岗位名称不能超过 30 个字符")
    import re
    if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', position_name):
        raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _switch():
        with get_db_connection() as conn:
            # 仅更新 users.personal_position，不触碰 job_positions 表
            conn.execute(
                "UPDATE users SET personal_position = ?, current_position_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (position_name, user['id'])
            )
            conn.commit()

    await run_db(_switch)
    return {"status": "success", "current_job_position": position_name}


@router.put("/api/profile/position")
async def switch_position(req: dict, admin: dict = Depends(get_admin_user)):
    """切换当前岗位（支持 position_id 或 position 名称）"""
    position_id = req.get("position_id")
    position_name = req.get("position", "").strip()

    # 输入验证：岗位名称长度和字符限制
    if position_name:
        if len(position_name) > 100:
            raise HTTPException(status_code=400, detail="岗位名称不能超过 100 个字符")
        import re
        if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', position_name):
            raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _switch():
        with get_db_connection() as conn:
            if position_id:
                row = conn.execute("SELECT id, name FROM job_positions WHERE id = ?", (position_id,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="岗位不存在")
                conn.execute("UPDATE users SET current_position_id = ?, personal_position = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row['id'], admin['id']))
                conn.commit()
                return row['name']
            elif position_name:
                # 查找岗位（包括软删除的）
                row = conn.execute("SELECT id, name FROM job_positions WHERE name = ?", (position_name,)).fetchone()
                if not row:
                    # 岗位不存在，自动创建
                    conn.execute("INSERT INTO job_positions (name) VALUES (?)", (position_name,))
                    pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    row = {'id': pos_id, 'name': position_name}
                    # 同时在 taxonomy 表创建空分类条目，使岗位出现在可选列表中
                    import json as _json
                    conn.execute(
                        "INSERT INTO taxonomy (position_name, categories_json, source, owner_id, updated_at) "
                        "VALUES (?, ?, 'system', NULL, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(position_name, source, owner_id) DO NOTHING",
                        (position_name, _json.dumps([], ensure_ascii=False))
                    )
                else:
                    # 岗位存在，检查是否被软删除，如果是则重新激活
                    cols = {r[1] for r in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
                    if 'is_deleted' in cols:
                        conn.execute("UPDATE job_positions SET is_deleted = 0 WHERE id = ? AND is_deleted = 1", (row['id'],))
                conn.execute("UPDATE users SET current_position_id = ?, personal_position = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row['id'], admin['id']))
                conn.commit()
                return row['name']
            else:
                raise HTTPException(status_code=400, detail="需要提供 position_id 或 position")

    result = await run_db(_switch)
    return {"status": "success", "current_job_position": result}


@router.get("/api/positions")
async def list_positions(user: dict = Depends(get_current_user)):
    """列出所有岗位"""
    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id, name, description FROM job_positions ORDER BY name").fetchall()
            return [dict(r) for r in rows]
    positions = await run_db(_query)
    return {"positions": positions}


@router.post("/api/positions")
async def create_position(req: dict, admin: dict = Depends(get_admin_user)):
    """新建岗位"""
    name = req.get("name", "").strip()
    description = req.get("description", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="岗位名称不能为空")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="岗位名称不能超过 100 个字符")
    import re
    if not re.match(r'^[一-龥a-zA-Z0-9\s/\-_()（）]+$', name):
        raise HTTPException(status_code=400, detail="岗位名称仅允许中英文、数字、空格、斜杠、连字符和括号")

    def _create():
        with get_db_connection() as conn:
            existing = conn.execute("SELECT id FROM job_positions WHERE name = ?", (name,)).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="岗位已存在")
            conn.execute("INSERT INTO job_positions (name, description) VALUES (?, ?)", (name, description))
            pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            return pos_id

    pos_id = await run_db(_create)
    return {"status": "success", "id": pos_id, "name": name}


@router.delete("/api/profile/position/{position_name}")
async def delete_position(position_name: str, admin: dict = Depends(get_admin_user)):
    """软删除岗位（仅管理员）"""
    def _delete():
        with get_db_connection() as conn:
            # 检查岗位是否存在
            row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (position_name,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="岗位不存在")

            # 确保 is_deleted 字段存在
            cols = {r[1] for r in conn.execute("PRAGMA table_info('job_positions')").fetchall()}
            if 'is_deleted' not in cols:
                conn.execute("ALTER TABLE job_positions ADD COLUMN is_deleted INTEGER DEFAULT 0")

            # 软删除
            conn.execute(
                "UPDATE job_positions SET is_deleted = 1 WHERE name = ?",
                (position_name,)
            )
            conn.commit()
            return True

    await run_db(_delete)
    return {"status": "success", "message": f"岗位 '{position_name}' 已删除"}


# ── 邮箱绑定 ──────────────────────────────────────────────────────

from pydantic import BaseModel, Field
from app.services.email_service import send_verification_code, verify_code


class BindEmailRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)
    code: str = Field(..., min_length=6, max_length=6)


class SendBindCodeRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=120)


def _check_email_taken(email: str, exclude_user_id: int = None) -> bool:
    """检查邮箱是否已被其他用户使用"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            return False
        if exclude_user_id and row['id'] == exclude_user_id:
            return False
        return True


def _update_user_email(user_id: int, email: str):
    """更新用户的邮箱"""
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET email = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (email, user_id))
        conn.commit()


@router.post("/api/profile/bind-email")
async def bind_email(req: BindEmailRequest, user: dict = Depends(get_current_user)):
    """绑定/更换邮箱"""
    # 校验验证码
    valid = await verify_code(req.email, req.code, "bind")
    if not valid:
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    # 检查邮箱是否已被其他用户使用
    if _check_email_taken(req.email, exclude_user_id=user['id']):
        raise HTTPException(status_code=409, detail="该邮箱已被其他用户绑定")

    # 更新邮箱
    _update_user_email(user['id'], req.email)
    return {"success": True, "message": "邮箱绑定成功", "email": req.email}


@router.get("/api/profile/email")
async def get_email(user: dict = Depends(get_current_user)):
    """获取当前绑定的邮箱"""
    def _query():
        with get_db_connection() as conn:
            row = conn.execute("SELECT email FROM users WHERE id = ?", (user['id'],)).fetchone()
            return row['email'] if row else None

    email = await run_db(_query)
    return {"email": email}


@router.post("/api/profile/send-bind-code")
@limiter.limit("3/minute")
async def send_bind_code(request: Request, req: SendBindCodeRequest, user: dict = Depends(get_current_user)):
    """发送绑定邮箱的验证码"""
    result = await send_verification_code(req.email, "bind")
    if not result["success"]:
        status = 503 if "未配置" in result["message"] else 429
        raise HTTPException(status_code=status, detail=result["message"])
    return result

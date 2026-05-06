import re
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_admin_user, get_current_user
from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_taxonomy_for_position
from app.core.config import _reload_from_db, _sync_env_file
from app.core import config as app_config
from app.models.schemas import ProfileUpdateRequest

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


def _get_available_positions(settings: dict) -> list:
    """从 user_profile 中提取所有已配置的岗位列表"""
    positions = set()
    for key in settings:
        if key.startswith("taxonomy_config_") and key != "taxonomy_config":
            pos = key[len("taxonomy_config_"):]
            if pos:
                positions.add(pos)
    # 兼容旧的单一 key
    if "taxonomy_config" in settings:
        try:
            tc = json.loads(settings["taxonomy_config"])
            if tc.get("job_position"):
                positions.add(tc["job_position"])
        except (json.JSONDecodeError, TypeError):
            pass
    if not positions:
        positions.add(DEFAULT_TAXONOMY["job_position"])
    return sorted(positions)


def _mask_key(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return value[:4] + "****"


@router.get("/api/profile")
async def get_profile(admin: dict = Depends(get_admin_user)):
    """读取全部用户配置（API Key 掩码返回）"""

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

    # 多岗位支持
    current_pos = settings.get('current_job_position', DEFAULT_TAXONOMY['job_position'])
    available_positions = _get_available_positions(settings)
    # 读取当前岗位的分类配置
    pos_taxonomy_key = f"taxonomy_config_{current_pos}"
    taxonomy_raw = settings.get(pos_taxonomy_key)
    if not taxonomy_raw:
        taxonomy_raw = settings.get('taxonomy_config')  # 兼容旧 key

    display_settings['current_job_position'] = current_pos
    display_settings['available_positions'] = available_positions
    if taxonomy_raw:
        display_settings['taxonomy_config'] = taxonomy_raw

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

    # taxonomy_config JSON 格式校验 + 按岗位存储
    if "taxonomy_config" in filtered:
        try:
            tc = json.loads(filtered["taxonomy_config"]) if isinstance(filtered["taxonomy_config"], str) else filtered["taxonomy_config"]
            if not isinstance(tc.get("categories"), list):
                raise ValueError("categories 字段必须是数组")
            # 按岗位存储为 taxonomy_config_{position}
            position = tc.get("job_position", get_current_job_position())
            pos_key = f"taxonomy_config_{position}"
            filtered[pos_key] = json.dumps(tc, ensure_ascii=False)
            del filtered["taxonomy_config"]
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


@router.put("/api/profile/position")
async def switch_position(req: dict, admin: dict = Depends(get_admin_user)):
    """切换当前岗位（支持 position_id 或 position 名称）"""
    position_id = req.get("position_id")
    position_name = req.get("position", "").strip()

    def _switch():
        with get_db_connection() as conn:
            if position_id:
                row = conn.execute("SELECT id, name FROM job_positions WHERE id = ?", (position_id,)).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="岗位不存在")
                conn.execute("UPDATE users SET current_position_id = ? WHERE id = ?", (row['id'], admin['id']))
                # 同步更新旧的 user_profile（兼容）
                conn.execute(
                    "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                    ("current_job_position", row['name'])
                )
                conn.commit()
                return row['name']
            elif position_name:
                row = conn.execute("SELECT id, name FROM job_positions WHERE name = ?", (position_name,)).fetchone()
                if not row:
                    # 岗位不存在，自动创建
                    conn.execute("INSERT INTO job_positions (name) VALUES (?)", (position_name,))
                    pos_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                    row = {'id': pos_id, 'name': position_name}
                conn.execute("UPDATE users SET current_position_id = ? WHERE id = ?", (row['id'], admin['id']))
                conn.execute(
                    "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                    ("current_job_position", row['name'])
                )
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

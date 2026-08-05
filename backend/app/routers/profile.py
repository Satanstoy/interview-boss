"""Profile 路由 — 公共配置 + 管理员配置（LLM/Taxonomy/Position/Email/Resume 已拆分到 profile_pkg/）"""

import re
import json
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_admin_user, get_current_user
from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import (
    get_db_connection,
    run_db,
    get_current_job_position,
    get_taxonomy_for_position,
)
from app.core.config import _reload_from_db, _sync_env_file
from app.core import config as app_config
from app.models.schemas import ProfileUpdateRequest

logger = logging.getLogger("interview-boss")

router = APIRouter()

ALLOWED_PROFILE_KEYS = {
    "active_season",
    "llm_model",
    "llm_api_key",
    "llm_base_url",
    "llm_timeout",
    "taxonomy_config",
}

_SENSITIVE_KEYS = {"llm_api_key"}
_REQUIRED_NON_EMPTY = {"llm_model", "llm_base_url"}
_MAX_POSITION_LEN = 30

_DEFAULT_SEASONS = [
    "2026届春招",
    "2026届秋招",
    "2026届暑期实习",
    "2026届日常实习",
    "2027届春招",
    "2027届秋招",
    "2027届暑期实习",
    "2027届日常实习",
    "2028届春招",
    "2028届秋招",
    "2028届暑期实习",
    "2028届日常实习",
]


def _get_available_positions() -> list:
    """从 taxonomy + job_positions 合并读取所有岗位列表"""
    with get_db_connection() as conn:
        tax_rows = conn.execute(
            "SELECT position_name FROM taxonomy ORDER BY position_name"
        ).fetchall()
        try:
            pos_rows = conn.execute(
                "SELECT name FROM job_positions WHERE is_deleted = 0 OR is_deleted IS NULL ORDER BY name"
            ).fetchall()
        except Exception:
            pos_rows = conn.execute(
                "SELECT name FROM job_positions ORDER BY name"
            ).fetchall()
        seen = set()
        result = []
        for r in tax_rows:
            name = r["position_name"]
            if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                seen.add(name)
                result.append(name)
        for r in pos_rows:
            name = r["name"]
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
            settings_map = {r["key"]: r["value"] for r in rows}
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
            season_list = [r["season"] for r in seasons]
            active = settings_map.get("active_season", "")
            if active and active not in season_list:
                season_list.append(active)
            for s in _DEFAULT_SEASONS:
                if s not in season_list:
                    season_list.append(s)
            season_list.sort()
            tax_rows = conn.execute(
                "SELECT position_name FROM taxonomy ORDER BY position_name"
            ).fetchall()
            try:
                pos_rows = conn.execute(
                    "SELECT name FROM job_positions WHERE is_deleted = 0 OR is_deleted IS NULL ORDER BY name"
                ).fetchall()
            except Exception:
                pos_rows = conn.execute(
                    "SELECT name FROM job_positions ORDER BY name"
                ).fetchall()
            seen = set()
            positions = []
            for r in tax_rows:
                name = r["position_name"]
                if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                    seen.add(name)
                    positions.append(name)
            for r in pos_rows:
                name = r["name"]
                if name and len(name) <= _MAX_POSITION_LEN and name not in seen:
                    seen.add(name)
                    positions.append(name)
            if not positions:
                positions = [DEFAULT_TAXONOMY["job_position"]]
            user_row = conn.execute(
                "SELECT u.personal_position, jp.name as position_name FROM users u "
                "LEFT JOIN job_positions jp ON u.current_position_id = jp.id WHERE u.id = ?",
                (user["id"],),
            ).fetchone()
        return settings_map, season_list, positions, user_row

    settings, used_seasons, available_positions, user_row = await run_db(_query)
    current_pos = (
        (
            user_row["personal_position"]
            if user_row and user_row["personal_position"]
            else None
        )
        or (
            user_row["position_name"]
            if user_row and user_row["position_name"]
            else None
        )
        or settings.get("current_job_position")
        or DEFAULT_TAXONOMY["job_position"]
    )
    taxonomy_data = await run_db(
        lambda: get_taxonomy_for_position(current_pos, user_id=user["id"])
    )

    return {
        "settings": {
            "current_job_position": current_pos,
            "available_positions": available_positions,
            "taxonomy_config": json.dumps(taxonomy_data, ensure_ascii=False),
            "active_season": settings.get("active_season", ""),
        },
        "available_seasons": used_seasons,
    }


@router.get("/api/profile")
async def get_profile(admin: dict = Depends(get_admin_user)):
    """读取全部用户配置（API Key 掩码返回）— 仅管理员"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
            settings_map = {r["key"]: r["value"] for r in rows}
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
            season_list = [r["season"] for r in seasons]
            active = settings_map.get("active_season", "")
            if active and active not in season_list:
                season_list.append(active)
            for s in _DEFAULT_SEASONS:
                if s not in season_list:
                    season_list.append(s)
            season_list.sort()
        return settings_map, season_list

    settings, used_seasons = await run_db(_query)

    _FALLBACK = {
        "llm_model": app_config.LLM_MODEL or "gpt-4o",
        "llm_base_url": app_config.LLM_BASE_URL or "",
        "llm_timeout": str(app_config.LLM_TIMEOUT or "120"),
    }
    for k, fallback in _FALLBACK.items():
        if not settings.get(k):
            settings[k] = fallback

    _ENV_FALLBACK = {
        "llm_api_key": app_config.LLM_API_KEY,
    }

    display_settings = {}
    for k, v in settings.items():
        if k in _SENSITIVE_KEYS:
            display_settings[k] = _mask_key(v) if v else ""
            display_settings[f"{k}_set"] = bool(v)
        else:
            display_settings[k] = v

    for k, env_val in _ENV_FALLBACK.items():
        if k not in display_settings or not display_settings[f"{k}_set"]:
            if env_val:
                display_settings[k] = _mask_key(env_val)
                display_settings[f"{k}_set"] = True

    available_positions = _get_available_positions()
    with get_db_connection() as conn:
        user_row = conn.execute(
            "SELECT u.personal_position, jp.name as position_name FROM users u "
            "LEFT JOIN job_positions jp ON u.current_position_id = jp.id WHERE u.id = ?",
            (admin["id"],),
        ).fetchone()
    current_pos = (
        (
            user_row["personal_position"]
            if user_row and user_row["personal_position"]
            else None
        )
        or (
            user_row["position_name"]
            if user_row and user_row["position_name"]
            else None
        )
        or settings.get("current_job_position")
        or DEFAULT_TAXONOMY["job_position"]
    )
    taxonomy_data = get_taxonomy_for_position(current_pos, user_id=admin["id"])

    display_settings["current_job_position"] = current_pos
    display_settings["available_positions"] = available_positions
    display_settings["taxonomy_config"] = json.dumps(taxonomy_data, ensure_ascii=False)

    return {"settings": display_settings, "available_seasons": used_seasons}


@router.put("/api/profile")
async def update_profile(
    req: ProfileUpdateRequest, admin: dict = Depends(get_admin_user)
):
    """批量更新用户配置"""

    invalid = set(req.settings.keys()) - ALLOWED_PROFILE_KEYS
    if invalid:
        raise HTTPException(status_code=400, detail=f"不允许的配置项: {invalid}")

    filtered = {
        k: v for k, v in req.settings.items() if not (k in _SENSITIVE_KEYS and not v)
    }

    empty_required = [
        k for k in _REQUIRED_NON_EMPTY if k in filtered and not str(filtered[k]).strip()
    ]
    if empty_required:
        labels = {
            "llm_model": "主模型名称",
            "llm_base_url": "主模型 Base URL",
        }
        names = "、".join(labels.get(k, k) for k in empty_required)
        raise HTTPException(status_code=400, detail=f"{names} 不能为空")

    if "taxonomy_config" in filtered:
        try:
            tc = (
                json.loads(filtered["taxonomy_config"])
                if isinstance(filtered["taxonomy_config"], str)
                else filtered["taxonomy_config"]
            )
            if not isinstance(tc.get("categories"), list):
                raise ValueError("categories 字段必须是数组")
            position = tc.get("job_position", get_current_job_position())
            from app.db.connection import save_taxonomy_for_position

            await run_db(
                lambda: save_taxonomy_for_position(
                    position, tc["categories"], source="user", owner_id=admin["id"]
                )
            )
            del filtered["taxonomy_config"]
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            raise HTTPException(
                status_code=400, detail=f"taxonomy_config 格式无效: {e}"
            )

    _URL_RE = re.compile(r'^https?://[^\s<>"\']+$', re.IGNORECASE)
    for k, v in filtered.items():
        if k.endswith("_base_url") and v:
            if not _URL_RE.match(v.strip()):
                raise HTTPException(
                    status_code=400,
                    detail=f"Base URL 格式无效，URL 必须以 http:// 或 https:// 开头",
                )

    if not filtered:
        return {"status": "success", "message": "无需更新"}

    def _update():
        with get_db_connection() as conn:
            for k, v in filtered.items():
                conn.execute(
                    "INSERT INTO user_profile (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                    (k, v),
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


@router.put("/api/profile/active-season")
async def update_active_season(req: dict, user: dict = Depends(get_admin_user)):
    """保存全局活跃招聘季（仅管理员；user_profile 为全局 key-value 单例）"""
    season = (req.get("active_season") or "").strip()

    def _save():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_profile (key, value, updated_at) VALUES ('active_season', ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                (season,),
            )
            conn.commit()

    await run_db(_save)
    return {"status": "success", "active_season": season}

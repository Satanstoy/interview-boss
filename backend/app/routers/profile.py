import logging
from fastapi import APIRouter, HTTPException
from app.db.connection import get_db_connection, run_db
from app.core.config import _reload_from_db, _sync_env_file
from app.core import config as app_config
from app.models.schemas import ProfileUpdateRequest

logger = logging.getLogger("multimodal-parser")

router = APIRouter()

ALLOWED_PROFILE_KEYS = {
    "active_season", "llm_model", "embedding_model", "similarity_threshold",
    "llm_api_key", "llm_base_url", "embedding_api_key", "embedding_base_url", "llm_timeout"
}

_SENSITIVE_KEYS = {"llm_api_key", "embedding_api_key"}

# 必填字段：不允许提交空值
_REQUIRED_NON_EMPTY = {"llm_model", "embedding_model", "llm_base_url", "embedding_base_url"}


def _mask_key(value: str) -> str:
    if not value or len(value) <= 4:
        return "****"
    return value[:4] + "****"


@router.get("/api/profile")
async def get_profile():
    """读取全部用户配置（API Key 掩码返回）"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
            seasons = conn.execute(
                "SELECT DISTINCT season FROM interview WHERE season IS NOT NULL AND season != '' ORDER BY season"
            ).fetchall()
        return {r['key']: r['value'] for r in rows}, [r['season'] for r in seasons]

    settings, used_seasons = await run_db(_query)

    # 非敏感字段：DB 为空时回退到 .env / config 全局变量
    _FALLBACK = {
        "llm_model": app_config.LLM_MODEL or "gpt-4o",
        "llm_base_url": app_config.LLM_BASE_URL or "",
        "embedding_model": app_config.EMBEDDING_MODEL or "text-embedding-3-small",
        "embedding_base_url": app_config.EMBEDDING_BASE_URL or "",
        "similarity_threshold": str(app_config.SIMILARITY_THRESHOLD or "0.85"),
        "llm_timeout": str(app_config.LLM_TIMEOUT or "120"),
    }
    for k, fallback in _FALLBACK.items():
        if not settings.get(k):
            settings[k] = fallback

    # 敏感字段：DB 为空时检查 .env 中是否有值
    _ENV_FALLBACK = {
        "llm_api_key": app_config.LLM_API_KEY,
        "embedding_api_key": app_config.EMBEDDING_API_KEY,
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

    return {"settings": display_settings, "available_seasons": used_seasons}


@router.put("/api/profile")
async def update_profile(req: ProfileUpdateRequest):
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
            "embedding_model": "Embedding 模型名称",
            "llm_base_url": "主模型 Base URL",
            "embedding_base_url": "Embedding Base URL"
        }
        names = "、".join(labels.get(k, k) for k in empty_required)
        raise HTTPException(status_code=400, detail=f"{names} 不能为空")

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
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")

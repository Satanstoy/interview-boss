"""Per-user web search provider configuration."""

import re
from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import get_current_user
from app.core.config import get_user_search_config
from app.db.connection import get_db_connection, run_db
from app.services.search_service import (
    SUPPORTED_SEARCH_PROVIDERS,
    get_search_provider_options,
    search_web,
)

router = APIRouter()


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


@router.get("/api/profile/search")
async def get_my_search_config(user: dict = Depends(get_current_user)):
    cfg = await run_db(lambda: get_user_search_config(user["id"]))
    if not cfg:
        return {
            "configured": False,
            "settings": {"provider": "none", "api_key": "", "api_key_set": False, "base_url": "", "enabled": False},
            "providers": get_search_provider_options(),
        }
    return {
        "configured": True,
        "settings": {
            "provider": cfg.get("provider", "none"),
            "api_key": _mask_key(cfg.get("api_key", "")),
            "api_key_set": bool(cfg.get("api_key")),
            "base_url": cfg.get("base_url", ""),
            "enabled": bool(cfg.get("enabled")),
        },
        "providers": get_search_provider_options(),
    }


@router.put("/api/profile/search")
async def update_my_search_config(req: dict, user: dict = Depends(get_current_user)):
    provider = (req.get("provider") or "none").strip().lower()
    if provider != "none" and provider not in SUPPORTED_SEARCH_PROVIDERS:
        raise HTTPException(status_code=400, detail="不支持的搜索服务商")

    base_url = (req.get("base_url") or "").strip()
    if base_url and not re.match(r"^https?://[^\s<>'\"]+$", base_url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Base URL 格式无效")

    api_key = (req.get("api_key") or "").strip()

    def _upsert():
        with get_db_connection() as conn:
            existing = conn.execute(
                "SELECT provider, api_key FROM user_search_config WHERE user_id = ?",
                (user["id"],),
            ).fetchone()
            same_provider = existing and existing["provider"] == provider
            final_key = api_key or (existing["api_key"] if same_provider else "")
            if provider == "none":
                final_key = ""
            if provider != "none" and not final_key:
                raise HTTPException(status_code=400, detail="请输入当前搜索服务商的 API Key")
            conn.execute(
                "INSERT INTO user_search_config (user_id, provider, api_key, base_url, enabled, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET provider = excluded.provider, "
                "api_key = excluded.api_key, base_url = excluded.base_url, "
                "enabled = excluded.enabled, updated_at = CURRENT_TIMESTAMP",
                (user["id"], provider, final_key, base_url, 0 if provider == "none" else 1),
            )
            conn.commit()

    await run_db(_upsert)
    return {"status": "success", "message": "联网搜索配置已保存"}


@router.delete("/api/profile/search")
async def delete_my_search_config(user: dict = Depends(get_current_user)):
    await run_db(
        lambda: _delete_search_config(user["id"])
    )
    return {"status": "success", "message": "联网搜索配置已清除"}


def _delete_search_config(user_id: int):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM user_search_config WHERE user_id = ?", (user_id,))
        conn.commit()


@router.post("/api/profile/search/test")
async def test_my_search_config(req: dict | None = None, user: dict = Depends(get_current_user)):
    query = ((req or {}).get("query") or "Redis 缓存面试题 官方文档").strip()[:300]
    cfg = await run_db(lambda: get_user_search_config(user["id"]))
    if not cfg:
        raise HTTPException(status_code=400, detail="请先保存搜索服务商和 API Key")
    try:
        data = await search_web(query, config=cfg, max_results=3)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "status": "success",
        "provider": data["provider"],
        "count": len(data.get("results", [])),
        "results": data.get("results", []),
    }

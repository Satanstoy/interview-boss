"""LLM 配置管理端点"""

import re
import logging
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()

_SENSITIVE_KEYS = {"llm_api_key"}


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


@router.get("/api/profile/llm")
async def get_my_llm_config(user: dict = Depends(get_current_user)):
    """读取当前用户的 LLM 配置（密钥掩码返回）"""

    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT api_key, base_url, model, timeout FROM user_llm_config WHERE user_id = ?",
                (user["id"],),
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
        },
    }


@router.put("/api/profile/llm")
async def update_my_llm_config(req: dict, user: dict = Depends(get_current_user)):
    """更新当前用户的 LLM 配置"""

    api_key = (req.get("llm_api_key") or "").strip()
    base_url = (req.get("llm_base_url") or "").strip()
    model = (req.get("llm_model") or "").strip()
    timeout = req.get("llm_timeout")

    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL 不能为空")

    _URL_RE = re.compile(r'^https?://[^\s<>"\']+$', re.IGNORECASE)
    if not _URL_RE.match(base_url):
        raise HTTPException(
            status_code=400, detail="Base URL 格式无效，必须以 http:// 或 https:// 开头"
        )

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
            existing = conn.execute(
                "SELECT api_key FROM user_llm_config WHERE user_id = ?", (user["id"],)
            ).fetchone()
            if not api_key and existing and existing["api_key"]:
                final_key = existing["api_key"]
            else:
                final_key = api_key

            conn.execute(
                "INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id) DO UPDATE SET api_key = excluded.api_key, base_url = excluded.base_url, "
                "model = excluded.model, timeout = excluded.timeout, updated_at = CURRENT_TIMESTAMP",
                (user["id"], final_key, base_url, model, timeout),
            )
            conn.commit()

    await run_db(_upsert)

    from app.services.llm import clear_user_client_cache

    clear_user_client_cache(user["id"])

    return {"status": "success", "message": "LLM 配置已保存"}


@router.delete("/api/profile/llm")
async def delete_my_llm_config(user: dict = Depends(get_current_user)):
    """删除当前用户的 LLM 配置"""

    def _delete():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM user_llm_config WHERE user_id = ?", (user["id"],))
            conn.commit()

    await run_db(_delete)

    from app.services.llm import clear_user_client_cache

    clear_user_client_cache(user["id"])

    return {"status": "success", "message": "LLM 配置已清除"}


@router.get("/api/profile/llm/models")
async def list_available_models(user: dict = Depends(get_current_user)):
    """获取当前用户配置的 LLM 提供商可用模型列表"""

    from app.core.config import get_user_llm_config
    from app.services.llm import _detect_provider

    cfg = get_user_llm_config(user["id"])
    if not cfg or not cfg.get("api_key"):
        return {"models": [], "current_model": "", "error": "请先配置 LLM API Key"}

    api_key = cfg["api_key"]
    base_url = cfg["base_url"]
    current_model = cfg.get("model", "gpt-4o")
    provider = _detect_provider(base_url)

    try:
        import httpx

        if provider == "anthropic":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
            url = "https://api.anthropic.com/v1/models"
        else:
            headers = {"Authorization": f"Bearer {api_key}"}
            base = base_url.rstrip("/")
            # base_url 可能已含 /v1 后缀（OpenAI 兼容 API 的标准做法），避免拼成 /v1/v1/models
            if base.endswith("/v1"):
                url = f"{base}/models"
            else:
                url = f"{base}/v1/models"

        async with httpx.AsyncClient(timeout=10) as http_client:
            response = await http_client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

        raw_models = data.get("data", [])
        models = [
            {"id": m.get("id", ""), "name": m.get("id", "")}
            for m in raw_models
            if m.get("id")
        ]
        models.sort(key=lambda x: x["id"])

    except Exception as e:
        logger.warning(f"获取模型列表失败: {e}")
        return {"models": [], "current_model": current_model, "error": str(e)}

    return {"models": models, "current_model": current_model, "error": None}

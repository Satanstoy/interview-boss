"""User-configurable web search providers used to ground generated answers."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_user_search_config

logger = logging.getLogger("interview-boss")

SUPPORTED_SEARCH_PROVIDERS = {
    "tavily": {
        "label": "Tavily",
        "description": "面向 AI Agent 的实时搜索，适合技术资料和答案增强。",
        "default_base_url": "https://api.tavily.com/search",
    },
    "brave": {
        "label": "Brave Search",
        "description": "独立搜索索引，适合作为通用搜索和备用搜索源。",
        "default_base_url": "https://api.search.brave.com/res/v1/web/search",
    },
    "bocha": {
        "label": "博查 Bocha",
        "description": "中文搜索体验较好，适合中文技术资料和面经。",
        "default_base_url": "https://api.bochaai.com/v1/web-search",
    },
}


class SearchProviderError(RuntimeError):
    """Raised when a configured search provider cannot be used."""


def get_search_provider_options() -> list[dict[str, str]]:
    return [
        {"id": "none", "label": "不使用联网搜索", "description": "仅使用系统题库和模型自身知识。"},
        *[
            {
                "id": provider,
                "label": data["label"],
                "description": data["description"],
            }
            for provider, data in SUPPORTED_SEARCH_PROVIDERS.items()
        ],
    ]


def _endpoint(provider: str, base_url: str | None) -> str:
    value = (base_url or SUPPORTED_SEARCH_PROVIDERS[provider]["default_base_url"]).strip()
    if provider == "tavily" and not value.rstrip("/").endswith("/search"):
        return value.rstrip("/") + "/search"
    if provider == "brave" and not value.rstrip("/").endswith("/search"):
        return value.rstrip("/") + "/res/v1/web/search"
    if provider == "bocha" and not value.rstrip("/").endswith("web-search"):
        return value.rstrip("/") + "/v1/web-search"
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_results(provider: str, payload: dict, limit: int) -> list[dict[str, str]]:
    if provider == "tavily":
        raw_items = payload.get("results") or []
    elif provider == "brave":
        raw_items = (payload.get("web") or {}).get("results") or []
    else:
        data = payload.get("data") or payload
        web_pages = data.get("webPages") if isinstance(data, dict) else None
        raw_items = (web_pages or {}).get("value") if isinstance(web_pages, dict) else None
        raw_items = raw_items or (data.get("results") if isinstance(data, dict) else []) or []

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        url = _text(item.get("url") or item.get("link"))
        if not url or url in seen_urls:
            continue
        title = _text(item.get("title") or item.get("name"))
        snippet = _text(
            item.get("content")
            or item.get("snippet")
            or item.get("description")
            or item.get("summary")
        )
        if not title and not snippet:
            continue
        seen_urls.add(url)
        results.append(
            {
                "title": title[:240],
                "url": url[:2000],
                "snippet": snippet[:1200],
                "published_at": _text(
                    item.get("published_at")
                    or item.get("date")
                    or item.get("dateLastCrawled")
                )[:80],
            }
        )
        if len(results) >= limit:
            break
    return results


async def search_web(
    query: str,
    user_id: int | None = None,
    *,
    config: dict | None = None,
    max_results: int = 5,
    timeout: float = 12,
) -> dict:
    """Search the web with a user-selected provider.

    ``config`` is intended for connection-test requests and is never persisted
    by this service. Search failures are surfaced to callers so answer
    generation can explicitly fall back to the model-only prompt.
    """
    cfg = config or get_user_search_config(user_id)
    if not cfg or cfg.get("provider") in (None, "none") or not cfg.get("api_key"):
        return {"provider": "none", "results": []}

    provider = str(cfg.get("provider", "")).strip().lower()
    if provider not in SUPPORTED_SEARCH_PROVIDERS:
        raise SearchProviderError(f"不支持的搜索服务商: {provider}")
    query = (query or "").strip()
    if not query:
        return {"provider": provider, "results": []}
    max_results = max(1, min(int(max_results), 10))
    endpoint = _endpoint(provider, cfg.get("base_url"))
    headers: dict[str, str] = {"Accept": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            if provider == "tavily":
                response = await client.post(
                    endpoint,
                    json={
                        "api_key": cfg["api_key"],
                        "query": query,
                        "search_depth": "advanced",
                        "topic": "general",
                        "max_results": max_results,
                        "include_answer": False,
                        "include_raw_content": False,
                    },
                    headers=headers,
                )
            elif provider == "brave":
                headers["X-Subscription-Token"] = cfg["api_key"]
                response = await client.get(
                    endpoint,
                    params={
                        "q": query,
                        "count": max_results,
                        "extra_snippets": "true",
                    },
                    headers=headers,
                )
            else:
                headers["Authorization"] = f"Bearer {cfg['api_key']}"
                headers["Content-Type"] = "application/json"
                response = await client.post(
                    endpoint,
                    json={
                        "query": query,
                        "freshness": "noLimit",
                        "summary": True,
                        "count": max_results,
                        "page": 1,
                    },
                    headers=headers,
                )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise SearchProviderError(f"搜索服务商返回 HTTP {status}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise SearchProviderError(f"搜索服务商连接失败: {exc}") from exc

    results = _normalize_results(provider, payload, max_results)
    return {"provider": provider, "results": results}

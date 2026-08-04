from unittest.mock import AsyncMock, patch

import httpx
import pytest


def test_search_config_migration_creates_per_user_table(test_db):
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('user_search_config')").fetchall()
    }
    assert {"user_id", "provider", "api_key", "base_url", "enabled"}.issubset(columns)


@pytest.mark.asyncio
async def test_tavily_results_are_normalized_and_deduplicated():
    from app.services.search_service import search_web

    response = httpx.Response(
        200,
        json={
            "results": [
                {"title": "Redis docs", "url": "https://redis.io/docs", "content": "official"},
                {"title": "Duplicate", "url": "https://redis.io/docs", "content": "ignored"},
                {"title": "Python docs", "url": "https://python.org", "content": "language"},
            ]
        },
        request=httpx.Request("POST", "https://api.tavily.com/search"),
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.search_service.httpx.AsyncClient", return_value=mock_client):
        result = await search_web(
            "Redis 面试题",
            config={"provider": "tavily", "api_key": "test-key", "base_url": ""},
        )

    assert result["provider"] == "tavily"
    assert [item["url"] for item in result["results"]] == [
        "https://redis.io/docs",
        "https://python.org",
    ]
    request = mock_client.post.call_args
    assert request.kwargs["json"]["api_key"] == "test-key"
    assert request.kwargs["json"]["search_depth"] == "advanced"


@pytest.mark.asyncio
async def test_search_provider_http_error_is_safe():
    from app.services.search_service import SearchProviderError, search_web

    response = httpx.Response(
        401,
        json={"error": "invalid key"},
        request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
    )
    mock_client = AsyncMock()
    mock_client.get.return_value = response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.search_service.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(SearchProviderError, match="HTTP 401"):
            await search_web(
                "Redis",
                config={"provider": "brave", "api_key": "bad-key", "base_url": ""},
            )


@pytest.mark.asyncio
async def test_exa_results_are_normalized_and_use_api_key_header():
    from app.services.search_service import search_web

    response = httpx.Response(
        200,
        json={
            "results": [
                {
                    "title": "Exa docs",
                    "url": "https://exa.ai/docs/reference/search",
                    "highlights": ["Semantic web search for AI applications."],
                    "publishedDate": "2026-08-01T00:00:00Z",
                }
            ]
        },
        request=httpx.Request("POST", "https://api.exa.ai/search"),
    )
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.services.search_service.httpx.AsyncClient", return_value=mock_client):
        result = await search_web(
            "AI 搜索",
            config={"provider": "exa", "api_key": "exa-test-key", "base_url": ""},
        )

    assert result["provider"] == "exa"
    assert result["results"][0]["snippet"] == "Semantic web search for AI applications."
    request = mock_client.post.call_args
    assert request.kwargs["headers"]["x-api-key"] == "exa-test-key"
    assert request.kwargs["json"]["numResults"] == 5
    assert request.kwargs["json"]["contents"]["highlights"] is True


@pytest.mark.asyncio
async def test_answer_prompt_falls_back_when_search_is_unavailable():
    from app.services.answer_enrichment import prepare_answer_prompt
    from app.services.search_service import SearchProviderError

    with patch(
        "app.services.answer_enrichment.search_web",
        side_effect=SearchProviderError("provider down"),
    ):
        prompt, sources = await prepare_answer_prompt("什么是 Redis？", user_id=7)

    assert sources == []
    assert "什么是 Redis？" in prompt
    assert "联网参考资料" not in prompt


@pytest.mark.asyncio
async def test_answer_prompt_includes_search_evidence_as_untrusted_context():
    from app.services.answer_enrichment import prepare_answer_prompt

    with patch(
        "app.services.answer_enrichment.search_web",
        return_value={
            "provider": "tavily",
            "results": [
                {
                    "title": "Redis 官方文档",
                    "url": "https://redis.io/docs/latest/",
                    "snippet": "Redis 是一个内存数据结构存储系统。",
                }
            ],
        },
    ):
        prompt, sources = await prepare_answer_prompt("什么是 Redis？", user_id=7)

    assert sources[0]["url"] == "https://redis.io/docs/latest/"
    assert "Redis 官方文档" in prompt
    assert "不可信外部内容" in prompt

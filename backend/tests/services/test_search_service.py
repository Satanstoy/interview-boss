from unittest.mock import AsyncMock, patch

import httpx
import pytest


def test_search_config_migration_creates_per_user_table(test_db):
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('user_search_config')").fetchall()
    }
    assert {"user_id", "provider", "api_key", "base_url", "enabled"}.issubset(columns)


def test_search_config_priority_is_personal_then_admin_public_only(test_db, monkeypatch):
    """管理员按个人→公共优先，普通用户不能读取公共配置或环境变量。"""
    from app.core.config import get_user_search_config, get_user_search_config_status

    admin_id = test_db.execute(
        "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
        ("search-normal-user", "test-hash"),
    )
    normal_id = test_db.execute(
        "SELECT id FROM users WHERE username = 'search-normal-user'"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO user_profile (key, value) VALUES (?, ?), (?, ?), (?, ?), (?, ?)",
        (
            "search_provider", "exa",
            "search_api_key", "public-key",
            "search_base_url", "",
            "search_enabled", "1",
        ),
    )
    test_db.execute(
        "INSERT INTO user_search_config (user_id, provider, api_key, base_url, enabled) "
        "VALUES (?, 'tavily', 'personal-key', '', 1)",
        (admin_id,),
    )
    test_db.commit()
    monkeypatch.setenv("SEARCH_PROVIDER", "brave")
    monkeypatch.setenv("SEARCH_API_KEY", "environment-key")

    assert get_user_search_config(admin_id)["source"] == "personal"
    assert get_user_search_config(admin_id)["api_key"] == "personal-key"

    test_db.execute("DELETE FROM user_search_config WHERE user_id = ?", (admin_id,))
    test_db.commit()
    assert get_user_search_config(admin_id)["source"] == "admin"
    assert get_user_search_config(admin_id)["provider"] == "exa"
    assert get_user_search_config(normal_id) is None
    assert get_user_search_config_status(admin_id)["source"] == "public"
    assert get_user_search_config_status(normal_id)["source"] == "none"


def test_public_search_scope_bypasses_admin_personal_provider(test_db):
    """公共参考答案必须固定使用管理员公共搜索配置。"""
    from app.core.config import get_user_search_config

    admin_id = test_db.execute(
        "SELECT id FROM users WHERE is_admin = 1 ORDER BY id LIMIT 1"
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO user_profile (key, value) VALUES (?, ?), (?, ?), (?, ?), (?, ?)",
        (
            "search_provider", "exa",
            "search_api_key", "public-key",
            "search_base_url", "",
            "search_enabled", "1",
        ),
    )
    test_db.execute(
        "INSERT INTO user_search_config (user_id, provider, api_key, base_url, enabled) "
        "VALUES (?, 'tavily', 'personal-key', '', 1)",
        (admin_id,),
    )
    test_db.commit()

    cfg = get_user_search_config(admin_id, scope="public")
    assert cfg["source"] == "admin"
    assert cfg["api_key"] == "public-key"


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
    assert "provider down" not in prompt


@pytest.mark.asyncio
async def test_answer_prompt_explicit_no_search_mode_does_not_call_search():
    from app.services.answer_enrichment import prepare_answer_prompt

    with patch(
        "app.services.answer_enrichment.search_web",
        new_callable=AsyncMock,
    ) as mock_search:
        prompt, sources = await prepare_answer_prompt(
            "什么是 Redis？", user_id=7, skip_search=True
        )

    assert sources == []
    assert "什么是 Redis？" in prompt
    mock_search.assert_not_awaited()


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

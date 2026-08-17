"""可选的真实接口 smoke tests。

离线默认不运行；设置 RUN_LIVE_LLM_TESTS=1 后，按三个协议分别验证真实服务的
请求/响应闭环。完整字段契约由 test_llm_formats_http.py 的 MockTransport 测试保证，
这里只验证 SDK、网关和模型配置在真实网络上的最低可用性。

环境变量：
LLM_TEST_API_KEY（默认 OPENAI_API_KEY）
LLM_TEST_MODEL（默认 LLM_MODEL_NAME 或 gpt-4o-mini）
LLM_TEST_CHAT_BASE_URL（默认 OPENAI_BASE_URL）
LLM_TEST_RESPONSES_BASE_URL（默认 LLM_TEST_CHAT_BASE_URL）
LLM_TEST_ANTHROPIC_BASE_URL（无默认值，需明确提供）
"""

import os

import pytest


pytestmark = pytest.mark.live_llm


def _required(name: str, fallback: str = "") -> str:
    value = os.environ.get(name) or fallback
    if not value:
        pytest.skip(f"未配置真实接口测试环境变量：{name}")
    return value


def _model() -> str:
    return _required("LLM_TEST_MODEL", os.environ.get("LLM_MODEL_NAME", "gpt-4o-mini"))


async def test_live_chat_completions_contract(monkeypatch):
    from openai import AsyncOpenAI
    from app.services import llm as llm_service

    key = _required("LLM_TEST_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    base_url = _required("LLM_TEST_CHAT_BASE_URL", os.environ.get("OPENAI_BASE_URL", ""))
    client = AsyncOpenAI(api_key=key, base_url=base_url, timeout=30)
    monkeypatch.setattr(
        llm_service,
        "_resolve_client_and_model",
        lambda _user_id: (client, _model(), 30, base_url, "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "chat")

    result = await llm_service._call_llm_with_retry(
        "只回复 OK",
        user_id=1,
        temperature=0,
        model=_model(),
    )

    assert isinstance(result, str)
    await client.close()


async def test_live_responses_contract(monkeypatch):
    from openai import AsyncOpenAI
    from app.services import llm as llm_service

    key = _required("LLM_TEST_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    base_url = _required(
        "LLM_TEST_RESPONSES_BASE_URL",
        os.environ.get("OPENAI_BASE_URL", ""),
    )
    client = AsyncOpenAI(api_key=key, base_url=base_url, timeout=30)
    monkeypatch.setattr(
        llm_service,
        "_resolve_client_and_model",
        lambda _user_id: (client, _model(), 30, base_url, "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")

    result = await llm_service._call_llm_with_retry(
        "只回复 OK",
        user_id=1,
        temperature=0,
        model=_model(),
    )

    assert isinstance(result, str)
    await client.close()


async def test_live_anthropic_messages_contract(monkeypatch):
    from anthropic import AsyncAnthropic
    from app.services import llm as llm_service

    key = _required("LLM_TEST_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
    base_url = _required("LLM_TEST_ANTHROPIC_BASE_URL")
    client = AsyncAnthropic(api_key=key, base_url=base_url, timeout=30)
    monkeypatch.setattr(
        llm_service,
        "_resolve_client_and_model",
        lambda _user_id: (client, _model(), 30, base_url, "anthropic"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "anthropic")

    result = await llm_service._call_llm_with_retry(
        "只回复 OK",
        user_id=1,
        temperature=0,
        model=_model(),
    )

    assert isinstance(result, str)
    await client.close()

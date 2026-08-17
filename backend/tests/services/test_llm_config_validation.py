"""保存前 LLM 接口格式校验的契约测试。"""

from unittest.mock import AsyncMock

import pytest


class _EndpointMismatchError(Exception):
    status_code = 404


class _AuthenticationError(Exception):
    status_code = 401


class _ModelNotFoundError(Exception):
    status_code = 404
    body = {"error": {"message": "The model test-model does not exist"}}


class _ProbeMethod:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return object()


class _ProbeClient:
    def __init__(self, error=None):
        self.chat = type("Chat", (), {})()
        self.chat.completions = _ProbeMethod(error)
        self.responses = _ProbeMethod(error)
        self.messages = _ProbeMethod(error)
        self.close = AsyncMock()


@pytest.fixture(autouse=True)
def clear_protocol_caches():
    from app.services import llm as llm_service

    llm_service.clear_api_format_cache()
    yield
    llm_service.clear_api_format_cache()


@pytest.mark.parametrize("api_format", ["chat", "responses", "anthropic"])
async def test_validate_llm_api_format_supports_each_protocol(monkeypatch, api_format):
    """用户明确选择三种协议时，校验请求应调用对应的最小探测接口。"""
    from app.services import llm as llm_service

    clients = {}

    def fake_make_client(*args, **kwargs):
        client = _ProbeClient()
        clients[kwargs["api_format"]] = client
        return client

    monkeypatch.setattr(llm_service, "_make_client", fake_make_client)

    result = await llm_service.validate_llm_api_format(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        model="test-model",
        timeout=30,
        requested_format=api_format,
    )

    assert result["connected"] is True
    assert result["compatible"] is True
    assert result["detected_format"] == api_format
    assert result["suggested_format"] is None
    probe_method = {
        "chat": clients[api_format].chat.completions,
        "responses": clients[api_format].responses,
        "anthropic": clients[api_format].messages,
    }[api_format]
    assert len(probe_method.calls) == 1
    request = probe_method.calls[0]
    assert request["model"] == "test-model"
    if api_format == "chat":
        assert request["messages"] == [{"role": "user", "content": "ping"}]
        assert request["max_tokens"] == 1
    elif api_format == "responses":
        assert request["input"] == "ping"
        assert request["max_output_tokens"] == 1
    else:
        assert request["messages"] == [{"role": "user", "content": "ping"}]
        assert request["max_tokens"] == 1


async def test_validate_llm_api_format_suggests_detected_format_after_mismatch(monkeypatch):
    """选中 Chat 但网关只接受 Responses 时，返回切换建议而不是保存错误。"""
    from app.services import llm as llm_service

    clients = {}

    def fake_make_client(*args, **kwargs):
        api_format = kwargs["api_format"]
        client = _ProbeClient(
            _EndpointMismatchError() if api_format == "chat" else None
        )
        clients[api_format] = client
        return client

    monkeypatch.setattr(llm_service, "_make_client", fake_make_client)

    result = await llm_service.validate_llm_api_format(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        model="test-model",
        timeout=30,
        requested_format="chat",
    )

    assert result == {
        "connected": True,
        "compatible": False,
        "requested_format": "chat",
        "detected_format": "responses",
        "suggested_format": "responses",
        "model": "test-model",
        "message": "检测到实际接口格式为 Responses，已为你切换建议格式，请再次保存确认",
        "error": None,
    }
    assert len(clients["chat"].chat.completions.calls) == 1
    assert len(clients["responses"].responses.calls) == 1
    clients["chat"].close.assert_awaited_once()
    clients["responses"].close.assert_awaited_once()


async def test_validate_llm_api_format_does_not_try_other_protocol_after_auth_failure(
    monkeypatch,
):
    """认证失败不是协议错配，不能为了猜格式重复发请求。"""
    from app.services import llm as llm_service

    clients = {}

    def fake_make_client(*args, **kwargs):
        api_format = kwargs["api_format"]
        client = _ProbeClient(_AuthenticationError())
        clients[api_format] = client
        return client

    monkeypatch.setattr(llm_service, "_make_client", fake_make_client)

    result = await llm_service.validate_llm_api_format(
        api_key="bad-key",
        base_url="https://gateway.example/v1",
        model="test-model",
        timeout=30,
        requested_format="chat",
    )

    assert result["connected"] is False
    assert result["compatible"] is False
    assert result["detected_format"] is None
    assert result["suggested_format"] is None
    assert result["error"] == "认证失败：请检查 API Key 是否正确"
    assert set(clients) == {"chat"}
    assert len(clients["chat"].chat.completions.calls) == 1


async def test_validate_llm_api_format_does_not_treat_model_404_as_protocol_mismatch(
    monkeypatch,
):
    """模型不存在的 404 不能触发另一种协议请求。"""
    from app.services import llm as llm_service

    clients = {}

    def fake_make_client(*args, **kwargs):
        api_format = kwargs["api_format"]
        client = _ProbeClient(_ModelNotFoundError())
        clients[api_format] = client
        return client

    monkeypatch.setattr(llm_service, "_make_client", fake_make_client)

    result = await llm_service.validate_llm_api_format(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        model="test-model",
        requested_format="chat",
    )

    assert result["connected"] is False
    assert result["suggested_format"] is None
    assert result["error"] == "模型服务未找到：请检查 Base URL 和模型名称"
    assert set(clients) == {"chat"}


async def test_validate_llm_api_format_ignores_temporary_client_close_failure(monkeypatch):
    """临时客户端清理失败不能覆盖协议探测结果。"""
    from app.services import llm as llm_service

    client = _ProbeClient()
    client.close.side_effect = RuntimeError("close failed")
    monkeypatch.setattr(llm_service, "_make_client", lambda *args, **kwargs: client)

    result = await llm_service.validate_llm_api_format(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        model="test-model",
        requested_format="chat",
    )

    assert result["connected"] is True
    assert result["detected_format"] == "chat"


async def test_validate_route_returns_detection_without_saving(monkeypatch):
    """校验端点传递未保存表单，并原样返回格式建议。"""
    from app.routers.profile_pkg.llm import validate_my_llm_config

    expected = {
        "connected": True,
        "compatible": False,
        "requested_format": "chat",
        "detected_format": "responses",
        "suggested_format": "responses",
        "model": "test-model",
        "message": "检测到实际接口格式为 Responses，已为你切换建议格式，请再次保存确认",
        "error": None,
    }
    probe = AsyncMock(return_value=expected)
    db = AsyncMock()
    monkeypatch.setattr("app.routers.profile_pkg.llm.run_db", db)
    monkeypatch.setattr("app.services.llm.validate_llm_api_format", probe)

    result = await validate_my_llm_config(
        {
            "llm_api_key": "test-key",
            "llm_base_url": "https://gateway.example/v1",
            "llm_model": "test-model",
            "llm_timeout": 30,
            "llm_api_format": "chat",
        },
        {"id": 7},
    )

    assert result == expected
    probe.assert_awaited_once_with(
        api_key="test-key",
        base_url="https://gateway.example/v1",
        model="test-model",
        timeout=30,
        requested_format="chat",
    )
    db.assert_not_awaited()

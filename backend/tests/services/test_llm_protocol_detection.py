"""协议选择、自动探测和配置缓存的契约测试。"""

from unittest.mock import MagicMock

import pytest


class EndpointMismatchError(Exception):
    status_code = 404


class AuthenticationProbeError(Exception):
    status_code = 401


class _ProbeChatCompletions:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return object()


class _ProbeResponses:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return object()


class _ProbeClient:
    def __init__(self, chat_error=None, responses_error=None):
        self.chat = MagicMock()
        self.chat.completions = _ProbeChatCompletions(chat_error)
        self.responses = _ProbeResponses(responses_error)


@pytest.fixture(autouse=True)
def clear_protocol_caches():
    from app.services import llm as llm_service

    if hasattr(llm_service, "clear_api_format_cache"):
        llm_service.clear_api_format_cache()
    llm_service.clear_user_client_cache()
    yield
    if hasattr(llm_service, "clear_api_format_cache"):
        llm_service.clear_api_format_cache()
    llm_service.clear_user_client_cache()


def test_explicit_anthropic_format_selects_anthropic_client_for_custom_relay(monkeypatch):
    """Anthropic-compatible relay 的 URL 不含 anthropic 时也必须选择 Messages client。"""
    from app.services import llm as llm_service

    cfg = {
        "api_key": "key",
        "base_url": "https://gateway.example/v1",
        "model": "claude-test",
        "timeout": 60,
        "api_format": "anthropic",
    }
    calls = []

    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda _user_id: cfg)

    def fake_make_client(*args, **kwargs):
        calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(llm_service, "_make_client", fake_make_client)

    _client, _model, _timeout, _base_url, provider = llm_service.get_llm_client_for_user(7)

    assert provider == "anthropic"
    assert calls[-1][1]["api_format"] == "anthropic"


async def test_auto_detection_probes_unknown_endpoint_once_and_caches_result():
    """未知端点应通过最小协议探测选择 Responses，并复用缓存结果。"""
    from app.services import llm as llm_service

    client = _ProbeClient(chat_error=EndpointMismatchError())

    first = await llm_service.resolve_api_format_async(
        client,
        model="model",
        timeout=5,
        base_url="https://gateway.example/v1",
        provider="openai",
        api_key="key",
    )
    second = await llm_service.resolve_api_format_async(
        client,
        model="model",
        timeout=5,
        base_url="https://gateway.example/v1",
        provider="openai",
        api_key="key",
    )

    assert first == second == "responses"
    assert client.chat.completions.calls == 1
    assert client.responses.calls == 1


async def test_auto_detection_does_not_try_other_protocol_after_auth_failure():
    """401/认证错误不能被误判成协议不支持，也不能触发第二次计费请求。"""
    from app.services import llm as llm_service

    client = _ProbeClient(chat_error=AuthenticationProbeError())

    with pytest.raises(AuthenticationProbeError):
        await llm_service.resolve_api_format_async(
            client,
            model="model",
            timeout=5,
            base_url="https://gateway.example/v1",
            provider="openai",
            api_key="key",
        )

    assert client.chat.completions.calls == 1
    assert client.responses.calls == 0


async def test_status_probe_reuses_successful_protocol_detection_request():
    """状态检查在未知网关上不能把识别请求再重复发送一次。"""
    from app.services import llm as llm_service

    client = _ProbeClient(chat_error=EndpointMismatchError())

    connected, error = await llm_service._probe_resolved(
        client,
        model="model",
        timeout=5,
        base_url="https://gateway.example/v1",
        provider="openai",
    )

    assert (connected, error) == (True, None)
    assert client.chat.completions.calls == 1
    assert client.responses.calls == 1


def test_status_fingerprint_includes_api_format(monkeypatch):
    """切换 Chat/Responses/Anthropic 后，旧的连通性结果不能继续复用。"""
    from app.services import llm as llm_service

    cfg = {
        "api_key": "key",
        "base_url": "https://gateway.example/v1",
        "model": "model",
        "api_format": "responses",
    }
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda _user_id: cfg)

    fingerprint = llm_service.llm_config_fingerprint(cfg)

    assert fingerprint[-1] == "responses"

"""LLM 供应商能力兼容层测试：矩阵匹配 / 降级 / max_tokens / override"""
import pytest


@pytest.mark.parametrize(
    "base_url,expected",
    [
        ("https://token-plan-cn.xiaomimimo.com/v1", False),
        ("https://api.siliconflow.cn/v1", True),
        ("https://api.openai.com/v1", True),
        ("https://unknown.example.com/v1", False),
    ],
)
def test_get_provider_capabilities_json_mode(base_url, expected):
    from app.services.llm import get_provider_capabilities

    assert get_provider_capabilities(base_url)["json_mode"] is expected


def test_get_provider_capabilities_max_tokens_default():
    from app.services.llm import get_provider_capabilities

    assert get_provider_capabilities("https://token-plan-cn.xiaomimimo.com/v1")["max_output_tokens"] == 4096
    assert get_provider_capabilities("https://api.openai.com/v1")["max_output_tokens"] == 4096


def test_should_use_response_format_mimo_false():
    from app.services.llm import _should_use_response_format
    assert _should_use_response_format("https://token-plan-cn.xiaomimimo.com/v1") is False


def test_should_use_response_format_siliconflow_true():
    from app.services.llm import _should_use_response_format
    assert _should_use_response_format("https://api.siliconflow.cn/v1") is True


def test_should_use_response_format_override(monkeypatch):
    from app.services.llm import _should_use_response_format
    monkeypatch.setenv("LLM_JSON_MODE_OVERRIDE", "force-on")
    assert _should_use_response_format("https://token-plan-cn.xiaomimimo.com/v1") is True
    monkeypatch.setenv("LLM_JSON_MODE_OVERRIDE", "force-off")
    assert _should_use_response_format("https://api.siliconflow.cn/v1") is False


def test_should_use_response_format_anthropic_never():
    from app.services.llm import _should_use_response_format
    assert _should_use_response_format("https://api.anthropic.com/v1") is False

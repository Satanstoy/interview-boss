"""OpenCode Go（opencode.ai/zen/go）端点的能力与调用路径优化测试。

这些断言全部来自 2026-09-27 对该网关的实测：

- ``max_tokens`` 硬上限 131072（262144 直接 400），69,008 token prompt +
  131072 仍通过；12 个可达 chat/anthropic 模型均接受 65536 与 131072。
- ``response_format: json_object`` **并非全模型通用**：mimo/glm/kimi 可用，
  hy3 返回 400。因此 opencode 的 ``json_mode`` 必须保持 False，走 prompt 指令降级。
- ``extra_body: {"thinking": {"type": "disabled"}}`` 在该网关上真实生效
  （reasoning_tokens 16 → 0），但 ``_is_mimo`` 只匹配 base_url，
  而 Go 的 URL 是 ``opencode.ai/zen/go/v1``，永远不含 "mimo"。
- grok/gpt 在 chat 端点返回 400 ``ModelProtocolUnsupported``，
  需要被当成协议错配而不是致命错误，设置页才能探测出正确协议。
"""

import pytest

from app.services.llm import (
    _is_mimo,
    _should_use_response_format,
    _supports_thinking_disable,
    llm_with_tools,
)
from app.services.llm_protocol import (
    _is_endpoint_mismatch,
    _models_list_url,
    get_provider_capabilities,
    get_provider_formats,
)
from app.services.llm_status import _validation_candidates

OPENCODE_GO = "https://opencode.ai/zen/go/v1"


# ── 1. 思考开关门控：只发给"实测接受该参数"的模型 ──────────────────
#
# 刻意不做「模型是否产出 reasoning」的推断 —— 两者是独立维度：
#   glm-5.3-flash / glm-5.1 默认 reasoning_tokens=256（确实在用 thinking），
#   但传 thinking.disabled 直接 400 invalid_request_error: thinking。
# 若按"有 thinking 就发"，探测到 reasoning 后的第二次调用就会硬失败，
# 而 BadRequestError 不在重试白名单里，无法恢复。未知一律不发。


@pytest.mark.parametrize(
    "model",
    [
        "mimo-v2.6-flash",
        "mimo-v2.6-pro",
        "mimo-v2.5-pro",
        "kimi-k2.6",
        "kimi-k3",
        "minimax-m3",
        "deepseek-v4-pro",
    ],
)
def test_thinking_disable_sent_to_verified_models(model):
    assert _supports_thinking_disable(OPENCODE_GO, model) is True


@pytest.mark.parametrize(
    "model",
    [
        "glm-5.3-flash",  # 传了 400
        "glm-5.1",  # 传了 400
        "glm-5.2",  # 传了 400
        "space-bunny-free",  # 传了 400
        "hy3",  # 接受但无效（256 → 256）
        "hy4-preview",  # 接受但无效（223 → 255）
        "longcat-2.0",  # 接受但无效（reasoning_content 仍在）
        "deepseek-v4-flash",  # 该区域不可用，未验证 → 不发
    ],
)
def test_thinking_disable_never_sent_to_rejecting_or_unverified_models(model):
    assert _supports_thinking_disable(OPENCODE_GO, model) is False


def test_thinking_gate_is_not_inferred_from_reasoning_output():
    """反例固化：glm 产出 reasoning 却拒绝参数，门控不能靠"有没有 thinking"推断。"""
    assert _supports_thinking_disable(OPENCODE_GO, "glm-5.3-flash") is False


def test_thinking_disable_legacy_mimo_endpoint_unchanged():
    assert (
        _supports_thinking_disable("https://token-plan-cn.xiaomimimo.com/v1", "any-model") is True
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.siliconflow.cn/v1",
        "https://api.openai.com/v1",
        "https://unknown.example.com/v1",
        "https://opencode.ai.evil.example/v1",
    ],
)
def test_thinking_disable_not_sent_to_other_providers(base_url):
    assert _supports_thinking_disable(base_url, "mimo-v2.5-pro") is False
    assert _supports_thinking_disable(base_url, "kimi-k2.6") is False


def test_is_mimo_is_endpoint_only_after_refactor():
    """_is_mimo 退回纯端点判定；模型维度统一由 _supports_thinking_disable 负责。"""
    assert _is_mimo("https://token-plan-cn.xiaomimimo.com/v1") is True
    assert _is_mimo(OPENCODE_GO) is False
    assert _is_mimo("https://example.com/v1") is False
    assert _is_mimo(None) is False


# ── 2. opencode.ai 能力矩阵条目 ────────────────────────────────────


def test_opencode_capability_entry_values():
    caps = get_provider_capabilities(OPENCODE_GO)
    assert caps["max_output_tokens"] == 32768
    # hy3 等模型实测不支持 response_format，不能开 json_mode
    assert caps["json_mode"] is False
    assert caps["prompt_cache_key"] is True
    assert caps["api_formats"] == ["chat", "responses", "anthropic"]


def test_opencode_formats_include_all_three_protocols():
    assert get_provider_formats(OPENCODE_GO) == ["chat", "responses", "anthropic"]


def test_opencode_json_mode_not_enabled():
    assert _should_use_response_format(OPENCODE_GO) is False


@pytest.mark.parametrize(
    "base_url",
    [
        "https://token-plan-cn.xiaomimimo.com/v1",
        "https://api.openai.com/v1",
        "https://api.siliconflow.cn/v1",
        "https://unknown.example.com/v1",
        "https://opencode.ai.evil.example/v1",  # 后缀伪造
        "https://notopencode.ai/v1",
    ],
)
def test_opencode_capability_not_applied_elsewhere(base_url):
    assert get_provider_capabilities(base_url)["max_output_tokens"] == 4096


def test_opencode_capability_is_exact_host_match():
    """能力矩阵按精确 hostname 匹配，子域不应命中条目。"""
    assert get_provider_capabilities("https://zen.opencode.ai/v1")["max_output_tokens"] == 4096


# ── 2b. 模型下拉框的 /models URL 构造 ──────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 用户按文档粘贴完整端点 → 归一化后必须仍是 .../v1/models
        ("https://opencode.ai/zen/go/v1", "https://opencode.ai/zen/go/v1/models"),
        (
            "https://opencode.ai/zen/go/v1/chat/completions",
            "https://opencode.ai/zen/go/v1/models",
        ),
        ("https://api.openai.com/v1", "https://api.openai.com/v1/models"),
        ("https://api.openai.com", "https://api.openai.com/v1/models"),
        ("https://gateway.example/v1/", "https://gateway.example/v1/models"),
    ],
)
def test_models_list_url(raw, expected):
    assert _models_list_url(raw) == expected


# ── 3. 设置页保存校验要能覆盖三种协议 ──────────────────────────────


def test_validation_candidates_cover_all_opencode_protocols():
    assert _validation_candidates(OPENCODE_GO, "auto") == [
        "chat",
        "responses",
        "anthropic",
    ]


def test_validation_candidates_respect_explicit_choice():
    candidates = _validation_candidates(OPENCODE_GO, "responses")
    assert candidates[0] == "responses"
    assert set(candidates) == {"chat", "responses", "anthropic"}


# ── 4. ModelProtocolUnsupported 是协议错配，不是致命错误 ───────────


class _Exc(Exception):
    def __init__(self, status_code, body):
        self.status_code = status_code
        self.body = body


def _unsupported_body():
    return (
        '{"type":"error","error":{"type":"ModelProtocolUnsupported",'
        '"message":"Model does not support this protocol."}}'
    )


def test_model_protocol_unsupported_counts_as_endpoint_mismatch():
    assert _is_endpoint_mismatch(_Exc(400, _unsupported_body())) is True


def test_other_bad_request_is_not_endpoint_mismatch():
    assert _is_endpoint_mismatch(_Exc(400, '{"error":"invalid temperature"}')) is False


def test_missing_session_error_is_not_endpoint_mismatch():
    """缺会话头属于配置错误，不能被当成"换个协议再试"。"""
    body = (
        '{"type":"error","error":{"type":"MissingSessionID",'
        '"message":"Request is missing x-opencode-session"}}'
    )
    assert _is_endpoint_mismatch(_Exc(400, body)) is False


def test_not_found_still_counts_as_endpoint_mismatch():
    assert _is_endpoint_mismatch(_Exc(404, "not found")) is True


def test_model_not_found_is_not_endpoint_mismatch():
    body = '{"error": {"code": "model_not_found", "message": "Model not found"}}'
    assert _is_endpoint_mismatch(_Exc(404, body)) is False


# ── 5. llm_with_tools 不得再硬编码 4096 ────────────────────────────


class _FakeMessage:
    content = "ok"
    reasoning_content = None
    tool_calls = None


class _FakeChoice:
    def __init__(self):
        self.message = _FakeMessage()
        self.finish_reason = "stop"


class _FakeResponse:
    def __init__(self):
        self.choices = [_FakeChoice()]
        self.usage = None


class _FakeClient:
    def __init__(self, captured):
        self.captured = captured
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                outer.captured.update(kwargs)
                return _FakeResponse()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


@pytest.fixture
def fake_tools_client(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (
            _FakeClient(captured),
            "mimo-v2.6-flash",
            60,
            OPENCODE_GO,
            "openai",
        ),
    )
    # 让 resolve_api_format 走显式分支，避免发起真实探测
    monkeypatch.setenv("LLM_API_FORMAT", "chat")
    return captured


async def test_llm_with_tools_uses_provider_max_output_tokens(fake_tools_client):
    """ReAct 主循环不传 max_tokens，必须落到能力矩阵而不是硬编码 4096。"""
    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)
    assert fake_tools_client["max_tokens"] == 32768


async def test_llm_with_tools_explicit_max_tokens_still_wins(fake_tools_client):
    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1, max_tokens=512)
    assert fake_tools_client["max_tokens"] == 512


async def test_llm_with_tools_other_provider_keeps_4096(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (
            _FakeClient(captured),
            "gpt-4o",
            60,
            "https://api.openai.com/v1",
            "openai",
        ),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "chat")
    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)
    assert captured["max_tokens"] == 4096

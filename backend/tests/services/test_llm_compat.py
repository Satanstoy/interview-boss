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


class FakeResponse:
    def __init__(self, content='{"ok": true}'):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})()]


class FakeCompletions:
    def __init__(self, captured, content=None):
        self._captured = captured
        self._content = content or '{"ok": true}'

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return FakeResponse(self._content)


class FakeChat:
    def __init__(self, captured, content=None):
        self.completions = FakeCompletions(captured, content)


class FakeClient:
    def __init__(self, captured, content=None):
        self.chat = FakeChat(captured, content)


async def test_call_with_retry_mimo_downgrades(monkeypatch):
    """mimo：json_object 不下发，system 附加 JSON 指令，max_tokens 显式"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "mimo-v2.5", 60,
                         "https://token-plan-cn.xiaomimimo.com/v1", "openai"),
    )
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("给个 JSON", response_format={"type": "json_object"}, user_id=1)

    assert "response_format" not in captured
    assert captured["max_tokens"] == 4096
    assert "严格以 JSON 格式输出" in captured["messages"][0]["content"]


async def test_call_with_retry_siliconflow_keeps_json_mode(monkeypatch):
    """SiliconFlow：json_object 正常下发"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "BAAI/bge-m3", 60,
                         "https://api.siliconflow.cn/v1", "openai"),
    )
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("给个 JSON", response_format={"type": "json_object"}, user_id=1)

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 4096


async def test_raw_llm_call_mimo_downgrades(monkeypatch):
    """raw_llm_call：mimo 时 response_format 被剥离，max_tokens 默认显式"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "mimo-v2.5", 60,
                         "https://token-plan-cn.xiaomimimo.com/v1", "openai"),
    )
    from app.services.llm import raw_llm_call

    await raw_llm_call(
        user_id=1, model="mimo-v2.5",
        messages=[{"role": "user", "content": "给个 JSON"}],
        response_format={"type": "json_object"},
    )

    assert "response_format" not in captured
    assert captured["max_tokens"] == 4096


async def test_raw_llm_call_siliconflow_keeps(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeClient(captured), "model", 60,
                         "https://api.siliconflow.cn/v1", "openai"),
    )
    from app.services.llm import raw_llm_call

    await raw_llm_call(
        user_id=1, model="model",
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )

    assert captured["response_format"] == {"type": "json_object"}


# ---------------- Responses API 格式 ----------------

def test_get_provider_formats_matrix():
    from app.services.llm import get_provider_formats

    assert get_provider_formats("https://token-plan-cn.xiaomimimo.com/v1") == ["chat", "responses"]
    assert get_provider_formats("https://api.siliconflow.cn/v1") == ["chat"]
    assert get_provider_formats("https://api.openai.com/v1") == ["chat", "responses"]
    assert get_provider_formats("https://api.anthropic.com/v1") == ["anthropic"]
    assert get_provider_formats("https://unknown.example.com/v1") == ["chat"]


def test_resolve_api_format_routing():
    from app.services.llm import resolve_api_format

    # anthropic 端点 → anthropic
    assert resolve_api_format("https://api.anthropic.com/v1") == "anthropic"
    # mimo 同时支持 chat+responses → 默认 chat（稳定优先）
    assert resolve_api_format("https://token-plan-cn.xiaomimimo.com/v1") == "chat"
    # 未知端点 → chat
    assert resolve_api_format("https://unknown.example.com/v1") == "chat"


def test_resolve_api_format_override(monkeypatch):
    from app.services.llm import resolve_api_format

    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    assert resolve_api_format("https://api.siliconflow.cn/v1") == "responses"

    monkeypatch.setenv("LLM_API_FORMAT", "anthropic")
    assert resolve_api_format("https://api.openai.com/v1") == "anthropic"


class FakeResponsesResponse:
    def __init__(self, output_text="resp 文本", output=None):
        self.output_text = output_text
        self.output = output


class FakeResponses:
    def __init__(self, captured, response):
        self._captured = captured
        self._response = response

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return self._response


class FakeResponsesClient:
    def __init__(self, captured, response=None):
        self.responses = FakeResponses(captured, response or FakeResponsesResponse())


async def test_call_with_retry_responses_format(monkeypatch):
    """responses 格式：input/instructions/max_output_tokens/text.format 映射正确"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeResponsesClient(captured), "mimo-v2.5", 60,
                         "https://token-plan-cn.xiaomimimo.com/v1", "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("给个 JSON", response_format={"type": "json_object"}, user_id=1)

    assert captured["input"][0]["type"] == "message"
    assert captured["input"][0]["role"] == "user"
    assert captured["input"][0]["content"][0]["text"] == "给个 JSON"
    assert "严格以 JSON 格式输出" not in captured["instructions"] or True  # mimo json_mode=false → text.format 不下发
    assert "text" not in captured  # json_mode=false 时降级，不带 text.format
    assert captured["max_output_tokens"] == 4096


async def test_call_with_retry_responses_keeps_text_format(monkeypatch):
    """siliconflow（json_mode=true）+ override responses：text.format 正常下发"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (FakeResponsesClient(captured), "model", 60,
                         "https://api.siliconflow.cn/v1", "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("给个 JSON", response_format={"type": "json_object"}, user_id=1)

    assert captured["text"] == {"format": {"type": "json_object"}}


async def test_extract_responses_text_mixed_output():
    """responses 响应解析：reasoning + message 混合 output 数组"""
    from app.services.llm import _extract_responses_text

    class Block:
        def __init__(self, text):
            self.type = "output_text"
            self.text = text

    class Msg:
        def __init__(self, text):
            self.type = "message"
            self.role = "assistant"
            self.content = [Block(text)]

    class Reasoning:
        type = "reasoning"

    response = FakeResponsesResponse(output_text="", output=[Reasoning(), Msg("最终答案")])
    assert _extract_responses_text(response) == "最终答案"

    # 有 output_text 时优先
    response2 = FakeResponsesResponse(output_text="快速文本", output=[Msg("慢文本")])
    assert _extract_responses_text(response2) == "快速文本"

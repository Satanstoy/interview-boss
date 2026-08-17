"""LLM 三格式 HTTP 层兼容性测试（httpx.MockTransport）。

模拟三种接口（OpenAI Chat / OpenAI Responses / Anthropic Messages）的
完整参数接入 llm.py，验证：
1. 发出的 HTTP 请求体与各格式官方 spec 一致（参数映射正确）
2. 各格式响应（文本/流式/工具调用）被正确解析
3. 流式 SSE 事件流正确消费
"""
import json

import httpx
import pytest
from openai import AsyncOpenAI


# ---------------- mock transport 基础设施 ----------------

def _mock_client(handler, base_url="https://mock.example.com/v1"):
    """构造带 MockTransport 的真实 OpenAI/Anthropic client（SDK 层真实发请求）。"""
    transport = httpx.MockTransport(handler)
    return AsyncOpenAI(
        api_key="test-key",
        base_url=base_url,
        http_client=httpx.AsyncClient(transport=transport),
    ), base_url


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


def _ok(json_data: dict) -> httpx.Response:
    return httpx.Response(200, json=json_data, request=request_for_response())


def request_for_response():
    return httpx.Request("POST", "https://mock.example.com/v1/chat/completions")


def _sse(events: list[str]) -> httpx.Response:
    """构造 SSE 响应（每行 data: {...}，空行分隔）。"""
    payload = "".join(f"data: {e}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=payload.encode(), request=request_for_response())


def _sse_anthropic(events: list[tuple[str, str]]) -> httpx.Response:
    """构造 Anthropic 格式 SSE（event: type + data）。"""
    payload = "".join(f"event: {t}\ndata: {d}\n\n" for t, d in events)
    return httpx.Response(200, headers={"content-type": "text/event-stream"},
                          content=payload.encode(), request=request_for_response())


# ---------------- Chat Completions ----------------

async def test_http_chat_full_params(monkeypatch):
    """chat：完整参数（messages/temperature/max_tokens/top_p/tools/tool_choice）请求体正确"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(_body(request))
        return _ok({
            "id": "chatcmpl-1", "object": "chat.completion", "model": "gpt-test",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "你好"}}],
        })

    client, base_url = _mock_client(handler, "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "test-model", 60, base_url, "openai"),
    )
    from app.services.llm import raw_llm_call

    result = await raw_llm_call(
        user_id=1, model="test-model",
        messages=[{"role": "system", "content": "你是面试官"},
                  {"role": "user", "content": "你好"}],
        temperature=0.5, max_tokens=200, top_p=0.9,
        tools=[{"type": "function", "function": {"name": "search", "description": "搜索",
                                                 "parameters": {"type": "object", "properties": {}}}}],
        tool_choice="auto",
    )
    assert result == "你好"
    assert captured["model"] == "test-model"
    assert captured["temperature"] == 0.5
    assert captured["max_tokens"] == 200
    assert captured["top_p"] == 0.9
    assert captured["messages"][0] == {"role": "system", "content": "你是面试官"}
    assert captured["tools"][0]["function"]["name"] == "search"
    assert captured["tool_choice"] == "auto"


async def test_http_chat_tool_calls_response(monkeypatch):
    """chat：工具调用响应解析（tool_calls + finish_reason=tool_calls）"""
    def handler(request):
        return _ok({
            "id": "x", "object": "chat.completion", "model": "m",
            "choices": [{"index": 0, "finish_reason": "tool_calls",
                         "message": {"role": "assistant", "content": None,
                                     "tool_calls": [{"id": "call_1", "type": "function",
                                                     "function": {"name": "search",
                                                                  "arguments": '{"q": "限流"}'}}]}}],
        })

    client, base_url = _mock_client(handler, "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    from app.services.llm import llm_with_tools

    result = await llm_with_tools(
        [{"role": "user", "content": "查限流"}],
        [{"type": "function", "function": {"name": "search", "description": "s",
                                           "parameters": {"type": "object"}}}],
        user_id=1,
    )
    assert result["finish_reason"] == "tool_calls"
    assert result["tool_calls"][0]["id"] == "call_1"
    assert result["tool_calls"][0]["function"]["name"] == "search"
    assert result["tool_calls"][0]["function"]["arguments"] == '{"q": "限流"}'


async def test_http_chat_tool_calls_normalizes_prompt_cache_usage(monkeypatch):
    """Chat Completions 的缓存 usage 应统一暴露给 ReAct 调用方。"""

    def handler(request):
        return _ok({
            "id": "x",
            "object": "chat.completion",
            "model": "m",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 10,
                "total_tokens": 130,
                "prompt_tokens_details": {
                    "cached_tokens": 96,
                    "cache_write_tokens": 0,
                },
            },
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "继续。"},
            }],
        })

    client, base_url = _mock_client(handler, "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    from app.services.llm import llm_with_tools

    result = await llm_with_tools(
        [{"role": "user", "content": "继续"}],
        [],
        user_id=1,
    )

    assert result["usage"] == {
        "input_tokens": 120,
        "output_tokens": 10,
        "total_tokens": 130,
        "cached_input_tokens": 96,
        "cache_write_input_tokens": 0,
        "cache_read_input_tokens": None,
    }


async def test_http_chat_sends_prompt_cache_key_only_to_known_openai(monkeypatch):
    """Provider-specific cache parameters must not leak to unknown endpoints."""
    captured = {}

    def handler(request):
        captured.update(_body(request))
        return _ok({
            "id": "x",
            "object": "chat.completion",
            "model": "m",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "继续。"},
            }],
        })

    client, base_url = _mock_client(handler, "https://api.openai.com/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    from app.services.llm import llm_with_tools

    await llm_with_tools(
        [{"role": "user", "content": "继续"}],
        [],
        user_id=1,
        prompt_cache_key="abc123",
    )

    assert captured["prompt_cache_key"] == "abc123"


async def test_http_chat_does_not_send_prompt_cache_key_to_openai_looking_relay(monkeypatch):
    """A relay URL containing api.openai.com must not inherit OpenAI-only fields."""
    captured = {}

    def handler(request):
        captured.update(_body(request))
        return _ok({
            "id": "x",
            "object": "chat.completion",
            "model": "m",
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "继续。"},
            }],
        })

    client, base_url = _mock_client(
        handler, "https://relay.example/api.openai.com/v1"
    )
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    from app.services.llm import llm_with_tools

    await llm_with_tools(
        [{"role": "user", "content": "继续"}],
        [],
        user_id=1,
        prompt_cache_key="abc123",
    )

    assert "prompt_cache_key" not in captured


async def test_http_chat_streaming(monkeypatch):
    """chat：流式 SSE delta 消费"""
    chunks = [
        {"id": "x", "object": "chat.completion.chunk", "model": "m",
         "choices": [{"index": 0, "delta": {"role": "assistant", "content": "你"}}]},
        {"id": "x", "object": "chat.completion.chunk", "model": "m",
         "choices": [{"index": 0, "delta": {"content": "好"}}]},
    ]

    def handler(request):
        return _sse([json.dumps(c, ensure_ascii=False) for c in chunks])

    client, base_url = _mock_client(handler, "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    from app.services.llm import stream_llm_messages

    texts = []
    async for chunk in stream_llm_messages(
        [{"role": "user", "content": "hi"}], user_id=1,
    ):
        texts.append(chunk)
    assert "".join(texts) == "你好"


# ---------------- Responses API ----------------

async def test_http_responses_full_params(monkeypatch):
    """responses：参数映射（input/instructions/max_output_tokens/text.format/tools/reasoning）"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(_body(request))
        return _ok({
            "id": "resp_1", "object": "response", "status": "completed",
            "model": "test-model",
            "output": [{"type": "message", "role": "assistant",
                        "content": [{"type": "output_text", "text": "这是回复"}]}],
            "output_text": "这是回复",
        })

    client, base_url = _mock_client(handler, "https://api.openai.com/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "test-model", 60, base_url, "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    from app.services.llm import _call_llm_with_retry

    result = await _call_llm_with_retry(
        "给个 JSON", system_msg="你是面试官",
        response_format={"type": "json_object"}, user_id=1,
    )
    assert result == "这是回复"
    assert captured["model"] == "test-model"
    assert captured["instructions"] == "你是面试官"
    assert captured["input"][0]["type"] == "message"
    assert captured["input"][0]["content"][0]["type"] == "input_text"
    assert captured["max_output_tokens"] == 4096
    assert captured["text"] == {"format": {"type": "json_object"}}


async def test_http_responses_tools_and_message_history(monkeypatch):
    """responses：工具调用 input 顶层 item（function_call/function_call_output）+ 扁平 tools"""
    captured = {}

    def handler(request):
        captured.update(_body(request))
        return _ok({
            "id": "resp_2", "object": "response", "status": "completed", "model": "m",
            "output": [{"type": "function_call", "call_id": "call_1",
                        "name": "search", "arguments": '{"q": "x"}'}],
            "output_text": "",
        })

    client, base_url = _mock_client(handler, "https://api.openai.com/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    from app.services.llm import llm_with_tools

    result = await llm_with_tools(
        [{"role": "user", "content": "查"},
         {"role": "assistant", "content": "好", "tool_calls": [
             {"id": "call_0", "function": {"name": "search", "arguments": "{}"}}]},
         {"role": "tool", "tool_call_id": "call_0", "content": "结果"}],
        [{"type": "function", "function": {"name": "search", "description": "s",
                                           "parameters": {"type": "object"}}}],
        user_id=1,
    )
    # 消息历史转换：user → message, assistant tool_calls → function_call, tool → function_call_output
    types = [i["type"] for i in captured["input"]]
    assert "message" in types and "function_call" in types and "function_call_output" in types
    assert captured["tools"][0]["type"] == "function"
    assert captured["tools"][0]["name"] == "search"  # 扁平格式
    # 响应工具调用提取
    assert result["tool_calls"][0]["id"] == "call_1"
    assert result["finish_reason"] == "tool_calls"


async def test_http_responses_streaming(monkeypatch):
    """responses：语义事件流（output_text.delta + reasoning_text.delta）"""
    events = [
        {"type": "response.created", "response": {}},
        {"type": "response.output_text.delta", "item_id": "i1", "output_index": 0,
         "content_index": 0, "delta": "你"},
        {"type": "response.reasoning_text.delta", "item_id": "i2", "output_index": 1,
         "content_index": 0, "delta": "思考中"},
        {"type": "response.output_text.delta", "item_id": "i1", "output_index": 0,
         "content_index": 0, "delta": "好"},
        {"type": "response.completed", "response": {"id": "r1"}},
    ]

    def handler(request):
        return _sse([json.dumps(e, ensure_ascii=False) for e in events])

    client, base_url = _mock_client(handler, "https://api.openai.com/v1")
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "m", 60, base_url, "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    from app.services.llm import stream_llm_messages

    texts, thinkings = [], []
    async for chunk in stream_llm_messages(
        [{"role": "user", "content": "hi"}], user_id=1, yield_thinking=True,
    ):
        if chunk["type"] == "content":
            texts.append(chunk["content"])
        elif chunk["type"] == "thinking":
            thinkings.append(chunk["content"])
    assert "".join(texts) == "你好"
    assert "".join(thinkings) == "思考中"


# ---------------- Anthropic Messages ----------------

def _anthropic_client(handler):
    from anthropic import AsyncAnthropic

    transport = httpx.MockTransport(handler)
    return AsyncAnthropic(
        api_key="test-key",
        base_url="https://api.anthropic.com",
        http_client=httpx.AsyncClient(transport=transport),
    )


async def test_http_anthropic_full_params(monkeypatch):
    """anthropic：system 顶层 + max_tokens + anthropic-version header + top_p"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = _body(request)
        captured["headers"] = dict(request.headers)
        return _ok({
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-test",
            "content": [{"type": "text", "text": "你好"}], "stop_reason": "end_turn",
        })

    client = _anthropic_client(handler)
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "claude-test", 60, "https://api.anthropic.com", "anthropic"),
    )
    from app.services.llm import _call_llm_with_retry

    result = await _call_llm_with_retry("你好", system_msg="你是面试官", user_id=1)
    assert result == "你好"
    assert captured["headers"].get("anthropic-version")
    assert captured["body"]["system"] == "你是面试官"
    assert captured["body"]["messages"][0] == {"role": "user", "content": "你好"}
    assert captured["body"]["max_tokens"] == 8192


async def test_http_anthropic_tools(monkeypatch):
    """anthropic：tools 转换（input_schema）+ tool_use 响应 + stop_reason=tool_use"""
    captured = {}

    def handler(request):
        captured.update(_body(request))
        return _ok({
            "id": "msg_2", "type": "message", "role": "assistant", "model": "c",
            "content": [{"type": "tool_use", "id": "tool_1", "name": "search",
                         "input": {"q": "x"}}],
            "stop_reason": "tool_use",
        })

    client = _anthropic_client(handler)
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "c", 60, "https://api.anthropic.com", "anthropic"),
    )
    from app.services.llm import llm_with_tools

    result = await llm_with_tools(
        [{"role": "user", "content": "查"}],
        [{"type": "function", "function": {"name": "search", "description": "s",
                                           "parameters": {"type": "object"}}}],
        user_id=1, tool_choice={"type": "function", "function": {"name": "search"}},
    )
    assert captured["tools"][0]["name"] == "search"
    assert captured["tools"][0]["input_schema"] == {"type": "object"}
    assert captured["cache_control"] == {"type": "ephemeral"}
    assert captured["tool_choice"] == {"type": "tool", "name": "search"}
    assert result["tool_calls"][0]["id"] == "tool_1"
    assert result["tool_calls"][0]["function"]["name"] == "search"
    assert result["tool_calls"][0]["function"]["arguments"] == '{"q": "x"}'
    assert result["finish_reason"] == "tool_calls"


async def test_http_anthropic_streaming(monkeypatch):
    """anthropic：SSE 事件流（content_block_start/delta + thinking_delta）"""
    events = [
        ("message_start", json.dumps({"type": "message_start", "message": {"id": "m1", "content": [], "usage": {"input_tokens": 10, "output_tokens": 10}}})),
        ("content_block_start", json.dumps({"type": "content_block_start", "index": 0,
                                            "content_block": {"type": "text", "text": ""}})),
        ("content_block_delta", json.dumps({"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "text_delta", "text": "你"}})),
        ("content_block_start", json.dumps({"type": "content_block_start", "index": 1,
                                            "content_block": {"type": "thinking", "thinking": ""}})),
        ("content_block_delta", json.dumps({"type": "content_block_delta", "index": 1,
                                            "delta": {"type": "thinking_delta", "thinking": "想"}})),
        ("content_block_delta", json.dumps({"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "text_delta", "text": "好"}})),
        ("content_block_stop", json.dumps({"type": "content_block_stop", "index": 0})),
        ("message_delta", json.dumps({"type": "message_delta",
                                      "delta": {"stop_reason": "end_turn"},
                                      "usage": {"output_tokens": 10}})),
        ("message_stop", json.dumps({"type": "message_stop"})),
    ]

    def handler(request):
        return _sse_anthropic(events)

    client = _anthropic_client(handler)
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (client, "c", 60, "https://api.anthropic.com", "anthropic"),
    )
    from app.services.llm import stream_llm_messages

    texts, thinkings = [], []
    async for chunk in stream_llm_messages(
        [{"role": "user", "content": "hi"}], user_id=1, yield_thinking=True,
    ):
        if chunk["type"] == "content":
            texts.append(chunk["content"])
        elif chunk["type"] == "thinking":
            thinkings.append(chunk["content"])
    assert "".join(texts) == "你好"
    assert "".join(thinkings) == "想"

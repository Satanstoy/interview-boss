"""OpenCode Go 端点的会话头与 base_url 归一化契约测试。

OpenCode Go 要求每个请求携带稳定的 ``x-opencode-session`` 头用于路由与
prompt cache；缺失时返回 400 ``MissingSessionID``，普通协议探测会把它误判
成"模型服务异常"。同时其文档给出的是完整端点 URL（如 ``.../v1/chat/completions``），
直接喂给 OpenAI SDK 会被二次拼接成 ``.../chat/completions/chat/completions``。
"""

import hashlib
import re

import httpx
import pytest

from app.services.llm import _make_client
from app.services.llm_protocol import (
    _normalise_llm_base_url,
    _opencode_session_id,
    _opencode_session_headers,
)
from app.services.llm_status import _classify_probe_error

OPENCODE_GO = "https://opencode.ai/zen/go/v1"
OPENCODE_GO_FULL = "https://opencode.ai/zen/go/v1/chat/completions"

_OTHER_PROVIDERS = (
    "https://api.openai.com/v1",
    "https://api.anthropic.com",
    "https://api.siliconflow.cn/v1",
    "https://token-plan-cn.xiaomimimo.com/v1",
    "https://gateway.example/v1",
)


# ── 门控：只有 OpenCode 才注入 ──────────────────────────────────────


@pytest.mark.parametrize("base_url", [OPENCODE_GO, OPENCODE_GO_FULL, "https://opencode.ai/zen/v1"])
def test_session_header_injected_for_opencode_hosts(base_url):
    assert "x-opencode-session" in _opencode_session_headers(base_url, "sk-test")


@pytest.mark.parametrize("base_url", _OTHER_PROVIDERS)
def test_session_header_not_injected_for_other_providers(base_url):
    assert _opencode_session_headers(base_url, "sk-test") == {}


@pytest.mark.parametrize(
    "base_url",
    [
        "https://opencode.ai.evil.example/v1",  # 后缀伪造域名
        "https://evilopencode.ai/v1",  # 前缀拼接域名
        "https://notopencode.ai/v1",
        "https://opencode.ai.example.com/v1",  # 子域伪造
        "http://opencode.ai.attacker.net/zen/go/v1",
        "",
        None,
    ],
)
def test_session_header_not_injected_for_spoofed_hosts(base_url):
    assert _opencode_session_headers(base_url, "sk-test") == {}


# ── session id：稳定、按密钥区分、不泄露密钥 ──────────────────────


def test_session_id_is_stable_across_calls():
    assert _opencode_session_id(OPENCODE_GO, "sk-abc") == _opencode_session_id(
        OPENCODE_GO, "sk-abc"
    )


def test_session_id_differs_per_api_key():
    assert _opencode_session_id(OPENCODE_GO, "sk-abc") != _opencode_session_id(
        OPENCODE_GO, "sk-xyz"
    )


def test_session_id_does_not_leak_api_key():
    api_key = "sk-super-secret-value-123456"
    sid = _opencode_session_id(OPENCODE_GO, api_key)
    assert api_key not in sid
    assert sid == hashlib.sha256(f"{OPENCODE_GO}|{api_key}".encode()).hexdigest()[:32]
    assert re.fullmatch(r"[0-9a-f]{32}", sid)


def test_session_id_is_32_hex_chars_for_header_safety():
    sid = _opencode_session_id(OPENCODE_GO, "sk-test")
    assert len(sid) == 32
    assert all(c in "0123456789abcdef" for c in sid)


def test_session_id_is_identical_for_either_paste_form():
    """用户粘 ``.../v1`` 还是 ``.../v1/chat/completions`` 必须落到同一 session，
    否则改一次 Base URL 就会丢失路由与 prompt cache。"""
    assert _opencode_session_id(OPENCODE_GO, "sk-test") == _opencode_session_id(
        OPENCODE_GO_FULL, "sk-test"
    )


# ── base_url 归一化：剥掉 SDK 会重新拼接的后缀 ────────────────────
#
# OpenAI SDK 拼 ``/chat/completions``（responses 模式拼 ``/responses``）；
# Anthropic SDK 拼 ``/v1/messages`` —— 注意是 `/v1/messages` 而非 `/messages`。


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (OPENCODE_GO_FULL, OPENCODE_GO),
        ("https://opencode.ai/zen/go/v1/responses", OPENCODE_GO),
        ("https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1"),
        ("https://gateway.example/v1/chat/completions/", "https://gateway.example/v1"),
    ],
)
def test_normalise_base_url_openai_strips_protocol_suffix(raw, expected):
    assert _normalise_llm_base_url(raw) == expected
    assert _normalise_llm_base_url(raw, "openai") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.anthropic.com/v1/messages", "https://api.anthropic.com"),
        ("https://api.anthropic.com/v1", "https://api.anthropic.com"),
        # Go 文档给的完整端点 URL
        ("https://opencode.ai/zen/go/v1/messages", "https://opencode.ai/zen/go"),
        # 纯 base URL：SDK 拼 /v1/messages 后必须正好落在 /zen/go/v1/messages
        (OPENCODE_GO, "https://opencode.ai/zen/go"),
    ],
)
def test_normalise_base_url_anthropic_strips_v1_messages(raw, expected):
    assert _normalise_llm_base_url(raw, "anthropic") == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        OPENCODE_GO,
        "https://api.openai.com/v1",
        "https://api.anthropic.com",
        "https://api.siliconflow.cn/v1",
        "https://example.com/anthropic",
        "https://gateway.example/v1/anthropic",  # 路径含 anthropic 但不是协议后缀
        "https://gateway.example/v1/responses/format",  # 后缀不在末尾
    ],
)
def test_normalise_base_url_openai_leaves_unrelated_urls_untouched(raw):
    assert _normalise_llm_base_url(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "https://api.anthropic.com",
        "https://example.com/anthropic",
        "https://gateway.example/v1/anthropic",  # 末尾不是 /v1，规则不触发
        "https://gateway.example/api",
        "https://gateway.example/v2/messages",  # 只剥 /v1/messages 与 /v1
    ],
)
def test_normalise_base_url_anthropic_leaves_unrelated_urls_untouched(raw):
    assert _normalise_llm_base_url(raw, "anthropic") == raw


def test_anthropic_strips_trailing_v1_because_sdk_appends_v1_messages():
    """anthropic provider 下 base 以 `/v1` 结尾必然产生 `/v1/v1/messages`，
    所以即使不带 `/messages` 后缀也必须剥掉。"""
    assert _normalise_llm_base_url("https://api.siliconflow.cn/v1", "anthropic") == (
        "https://api.siliconflow.cn"
    )
    # 同一个 base 在 openai provider 下是完全合法的，绝不能被剥
    assert _normalise_llm_base_url("https://api.siliconflow.cn/v1") == (
        "https://api.siliconflow.cn/v1"
    )


# ── 端到端：头真的上了 wire ────────────────────────────────────────


class _CapturingTransport:
    """记录真实发出的请求头，并回一个合法的 chat completion。"""

    def __init__(self):
        self.headers: dict[str, str] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.headers = dict(request.headers)
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "cmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "mimo-v2.6-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "pong"},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def capture_transport(monkeypatch):
    """把 llm 模块的传输层换成捕获型，其余逻辑保持真实。"""
    created: dict[str, _CapturingTransport] = {}

    def factory(base_url):
        cap = _CapturingTransport()
        created["cap"] = cap
        return cap.transport()

    monkeypatch.setattr("app.services.llm.build_pinned_async_http_transport", factory)
    monkeypatch.setattr("app.services.llm.assert_safe_outbound_url_sync", lambda url: None)
    return created


async def test_make_client_sends_session_header_on_wire(capture_transport):
    client = _make_client("sk-test-key", OPENCODE_GO_FULL, 30, "openai")
    try:
        await client.chat.completions.create(
            model="mimo-v2.6-flash",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=5,
        )
    finally:
        await client.close()

    captured = capture_transport["cap"].headers
    assert "x-opencode-session" in captured
    assert captured["x-opencode-session"] == _opencode_session_id(OPENCODE_GO_FULL, "sk-test-key")
    # 同时验证 base_url 已被归一化，否则 URL 会变成 .../chat/completions/chat/completions
    assert str(client.base_url).rstrip("/") == OPENCODE_GO


async def test_make_client_omits_session_header_for_other_providers(capture_transport):
    client = _make_client("sk-test-key", "https://api.openai.com/v1", 30, "openai")
    try:
        await client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": "hi"}], max_tokens=5
        )
    finally:
        await client.close()

    assert "x-opencode-session" not in capture_transport["cap"].headers


async def test_make_client_sends_same_session_header_across_requests(capture_transport):
    """连续请求必须复用同一 session id，否则路由与 prompt cache 会失效。"""
    client = _make_client("sk-test-key", OPENCODE_GO, 30, "openai")
    seen: list[str] = []
    try:
        for _ in range(2):
            await client.chat.completions.create(
                model="mimo-v2.6-flash",
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            seen.append(capture_transport["cap"].headers["x-opencode-session"])
    finally:
        await client.close()

    assert len(set(seen)) == 1


# ── 400 MissingSessionID 的错误分类不应被"模型服务异常"掩盖 ───────


class _MissingSessionError(Exception):
    status_code = 400
    body = (
        '{"type":"error","error":{"type":"MissingSessionID",'
        '"message":"Request is missing x-opencode-session"}}'
    )


class _GenericBadRequest(Exception):
    status_code = 400
    body = '{"error":"invalid temperature"}'


def test_missing_session_id_has_dedicated_error_message():
    message = _classify_probe_error(_MissingSessionError())
    assert "x-opencode-session" in message
    assert "模型服务异常" not in message


def test_other_bad_request_keeps_generic_message():
    assert _classify_probe_error(_GenericBadRequest()) == (
        "模型服务异常：请检查 Base URL、模型名称和 API Key"
    )

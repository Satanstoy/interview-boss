"""mimo 深度思考关闭（thinking disabled）测试：mimo 默认关思考提速，其他 provider 不受影响。"""


class _FakeResponse:
    def __init__(self, content='{"ok": true}'):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})})()]


class _FakeCompletions:
    def __init__(self, captured, content=None):
        self._captured = captured
        self._content = content or '{"ok": true}'

    async def create(self, **kwargs):
        self._captured.update(kwargs)
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, captured, content=None):
        self.completions = _FakeCompletions(captured, content)


class _FakeClient:
    def __init__(self, captured, content=None):
        self.chat = _FakeChat(captured, content)


def _patch_resolve(monkeypatch, captured, base_url, model="mimo-v2.5-pro", provider="openai"):
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (_FakeClient(captured), model, 60, base_url, provider),
    )


async def test_mimo_default_disables_thinking(monkeypatch):
    """mimo base_url + 默认参数 → 下发 extra_body thinking disabled（提速）"""
    captured = {}
    _patch_resolve(monkeypatch, captured, "https://token-plan-cn.xiaomimimo.com/v1")
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("测试", user_id=1)

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


async def test_mimo_thinking_true_keeps_thinking(monkeypatch):
    """mimo + thinking=True → 不传 extra_body（保留深度思考）"""
    captured = {}
    _patch_resolve(monkeypatch, captured, "https://token-plan-cn.xiaomimimo.com/v1")
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("测试", user_id=1, thinking=True)

    assert "extra_body" not in captured


async def test_non_mimo_provider_never_sends_thinking(monkeypatch):
    """非 mimo provider（SiliconFlow/OpenAI）→ 不传 extra_body，避免未知参数报错"""
    for base_url in (
        "https://api.siliconflow.cn/v1",
        "https://api.openai.com/v1",
    ):
        captured = {}
        _patch_resolve(monkeypatch, captured, base_url)
        from app.services.llm import _call_llm_with_retry

        await _call_llm_with_retry("测试", user_id=1)

        assert "extra_body" not in captured


async def test_mimo_with_response_format_still_disables_thinking(monkeypatch):
    """mimo + response_format（refine loop critic 场景）→ 两者同时下发，不冲突"""
    captured = {}
    _patch_resolve(monkeypatch, captured, "https://token-plan-cn.xiaomimimo.com/v1")
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("测试", response_format={"type": "json_object"}, user_id=1)

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


# ── ReAct 主循环（llm_with_tools）此前完全忽略 thinking ──────────────
# react_loop.py 不传 thinking，llm_with_tools 也不处理它，导致面试官 agent
# 在 mimo 上思考常开、temperature 失效。


class _ToolsResponse:
    def __init__(self, reasoning=None):
        self.choices = [
            type(
                "C",
                (),
                {
                    "message": type(
                        "M",
                        (),
                        {"content": "ok", "tool_calls": None, "reasoning_content": reasoning},
                    )(),
                    "finish_reason": "stop",
                },
            )()
        ]
        self.usage = None


class _ToolsClient:
    def __init__(self, captured, reasoning=None):
        self._captured = captured
        self._reasoning = reasoning
        outer = self

        class _Completions:
            async def create(self, **kwargs):
                outer._captured.update(kwargs)
                return _ToolsResponse(outer._reasoning)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _patch_tools(monkeypatch, captured, base_url, model="mimo-v2.6-flash", provider="openai"):
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (_ToolsClient(captured), model, 60, base_url, provider),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "chat")


async def test_tools_loop_disables_thinking_by_default(monkeypatch):
    """ReAct 主循环默认走用户配置（默认关）→ 必须下发 thinking disabled"""
    captured = {}
    _patch_tools(monkeypatch, captured, "https://opencode.ai/zen/go/v1")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


async def test_tools_loop_honors_global_credential_scope(monkeypatch):
    """公共题库工具调用必须选择系统凭据，不能读取管理员个人 thinking 配置。"""
    from unittest.mock import AsyncMock

    captured = {}
    scopes = []
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id, llm_scope="user": (
            scopes.append(llm_scope)
            or (_ToolsClient(captured), "test-model", 60, "https://api.example.test/v1", "openai")
        ),
    )
    monkeypatch.setattr(
        "app.services.llm.resolve_api_format_async",
        AsyncMock(return_value="chat"),
    )

    def _unexpected_user_config_read(_user_id):
        raise AssertionError("global scope must not read a user's LLM config")

    monkeypatch.setattr("app.core.config.get_user_llm_config", _unexpected_user_config_read)
    from app.services.llm import llm_with_tools

    await llm_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[],
        user_id=201,
        llm_scope="global",
    )

    assert scopes == ["global"]


async def test_tools_loop_honours_user_thinking_opt_in(monkeypatch):
    """用户开了 llm_thinking → 保留思考，不下发 extra_body"""
    captured = {}
    _patch_tools(monkeypatch, captured, "https://opencode.ai/zen/go/v1")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": True})
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert "extra_body" not in captured


async def test_tools_loop_explicit_thinking_overrides_config(monkeypatch):
    captured = {}
    _patch_tools(monkeypatch, captured, "https://opencode.ai/zen/go/v1")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1, thinking=True)

    assert "extra_body" not in captured


async def test_tools_loop_non_mimo_model_never_sends_thinking(monkeypatch):
    """glm 等模型传 thinking 参数会 400（2026-09-28 实测）→ 必须守住 model 门槛"""
    captured = {}
    _patch_tools(monkeypatch, captured, "https://opencode.ai/zen/go/v1", model="glm-5.3-flash")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert "extra_body" not in captured


async def test_tools_loop_sends_thinking_for_other_verified_models(monkeypatch):
    """kimi / minimax 实测同样受益（kimi 234→1、minimax 30→None），门控不能只认 mimo"""
    for model in ("kimi-k2.6", "minimax-m3", "deepseek-v4-pro"):
        captured = {}
        _patch_tools(monkeypatch, captured, "https://opencode.ai/zen/go/v1", model=model)
        monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
        from app.services.llm import llm_with_tools

        await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

        assert captured["extra_body"] == {"thinking": {"type": "disabled"}}, model


async def test_tools_loop_non_opencode_provider_never_sends_thinking(monkeypatch):
    captured = {}
    _patch_tools(monkeypatch, captured, "https://api.siliconflow.cn/v1", model="mimo-v2.5-pro")
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert "extra_body" not in captured


async def test_tools_loop_still_returns_reasoning_content_when_thinking_on(monkeypatch):
    """思考开启时 reasoning_content 仍要透出（react_loop 的 _emit_reasoning_content 依赖它）"""
    captured = {}
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (
            _ToolsClient(captured, reasoning="分析中…"),
            "mimo-v2.6-flash",
            60,
            "https://opencode.ai/zen/go/v1",
            "openai",
        ),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "chat")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": True})
    from app.services.llm import llm_with_tools

    result = await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert "extra_body" not in captured
    assert result["reasoning_content"] == "分析中…"


async def test_tools_loop_reasoning_content_absent_when_thinking_off(monkeypatch):
    captured = {}
    _patch_tools(monkeypatch, captured, "https://opencode.ai/zen/go/v1")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
    from app.services.llm import llm_with_tools

    result = await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    # _emit_reasoning_content 对 None/空串静默返回，不会崩
    assert result["reasoning_content"] is None


class _ToolsResponsesClient:
    def __init__(self, captured):
        self._captured = captured
        outer = self

        class _Responses:
            async def create(self, **kwargs):
                outer._captured.update(kwargs)
                return type("R", (), {"output_text": "ok", "status": "completed", "usage": None})()

        self.responses = _Responses()


def _patch_tools_responses(monkeypatch, captured, base_url, model="mimo-v2.5"):
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (_ToolsResponsesClient(captured), model, 60, base_url, "openai"),
    )
    monkeypatch.setenv("LLM_API_FORMAT", "responses")


async def test_tools_loop_responses_format_disables_thinking(monkeypatch):
    """responses 分支与 raw_llm_call 对齐：mimo 关思考发 reasoning.effort=none"""
    captured = {}
    _patch_tools_responses(monkeypatch, captured, "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert captured.get("reasoning") == {"effort": "none"}


async def test_tools_loop_responses_format_keeps_thinking(monkeypatch):
    captured = {}
    _patch_tools_responses(monkeypatch, captured, "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": True})
    from app.services.llm import llm_with_tools

    await llm_with_tools([{"role": "user", "content": "hi"}], tools=[], user_id=1)

    assert "reasoning" not in captured


# ── _resolve_thinking 解析规则 ──────────────────────────────────────


def test_resolve_thinking_rule(monkeypatch):
    from app.services.llm import _resolve_thinking

    # 显式参数永远优先
    assert _resolve_thinking(1, True) is True
    assert _resolve_thinking(1, False) is False
    # global scope 恒为关
    assert _resolve_thinking(1, None, llm_scope="global") is False
    # 读用户配置
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": True})
    assert _resolve_thinking(1, None) is True
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: {"thinking": False})
    assert _resolve_thinking(1, None) is False
    # 无配置 / 读取异常 → 保守关闭
    monkeypatch.setattr("app.core.config.get_user_llm_config", lambda uid: None)
    assert _resolve_thinking(1, None) is False

    def _boom(uid):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.core.config.get_user_llm_config", _boom)
    assert _resolve_thinking(1, None) is False


def test_resolve_thinking_without_user_never_reads_config(monkeypatch):
    """user_id=None → 不读配置直接关（与 get_user_llm_config(None) 返回 None 等价）。"""
    from app.services.llm import _resolve_thinking

    def _boom(uid):
        raise RuntimeError("should not be called")

    monkeypatch.setattr("app.core.config.get_user_llm_config", _boom)
    assert _resolve_thinking(None, None) is False

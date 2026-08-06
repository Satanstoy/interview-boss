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

    await _call_llm_with_retry(
        "测试", response_format={"type": "json_object"}, user_id=1
    )

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}

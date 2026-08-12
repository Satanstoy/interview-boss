"""LLM 配置增强测试：api_format（接口类型校验）+ thinking（深度思考开关）per-user 生效。"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


def test_migration_creates_llm_api_format_columns(test_db):
    """user_llm_config 应有 api_format / thinking 列"""
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('user_llm_config')").fetchall()
    }
    assert "api_format" in columns
    assert "thinking" in columns


def test_get_user_llm_config_returns_new_fields(test_db):
    """get_user_llm_config 返回 api_format / thinking（默认 auto / 0）"""
    from app.core.config import get_user_llm_config

    test_db.execute(
        "INSERT INTO user_llm_config (user_id, api_key, base_url, model, timeout) "
        "VALUES (1, 'tp-test', 'https://token-plan-cn.xiaomimimo.com/v1', 'mimo-v2.5-pro', 120)"
    )
    test_db.commit()

    cfg = get_user_llm_config(1)
    assert cfg["api_format"] == "auto"
    assert cfg["thinking"] == 0


def test_global_llm_scope_ignores_admin_personal_config(monkeypatch):
    """管理员公共答案必须绕过管理员账号的 user_llm_config。"""
    from app.services import llm as llm_service

    global_cfg = {
        "api_key": "global-key",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
        "timeout": 120,
    }
    personal_cfg = {
        "api_key": "personal-key",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "timeout": 120,
    }
    sentinel = object()
    monkeypatch.setattr(
        "app.core.config._get_global_llm_config", lambda: global_cfg
    )
    monkeypatch.setattr(
        "app.core.config.get_user_llm_config", lambda _user_id: personal_cfg
    )
    monkeypatch.setattr(llm_service, "_make_client", lambda *args, **kwargs: sentinel)

    client, model, timeout, base_url, _provider = llm_service.get_llm_client_for_user(
        1014, llm_scope="global"
    )

    assert client is sentinel
    assert (model, timeout, base_url) == (
        "mimo-v2.5-pro",
        120,
        "https://token-plan-cn.xiaomimimo.com/v1",
    )


async def test_update_llm_config_rejects_unsupported_api_format(monkeypatch):
    """mimo OpenAI 端点选 anthropic 接口 → 400 报错"""
    from app.routers.profile_pkg.llm import update_my_llm_config

    def _exec(fn):
        return fn()

    with patch(
        "app.routers.profile_pkg.llm.run_db", new_callable=AsyncMock
    ) as mock_run_db:
        mock_run_db.side_effect = _exec
        with patch("app.routers.profile_pkg.llm.get_db_connection") as mock_get_conn:
            conn = MagicMock()
            conn.__enter__.return_value = conn
            conn.__exit__.return_value = None
            conn.execute.return_value.fetchone.return_value = None
            mock_get_conn.return_value = conn
            try:
                await update_my_llm_config(
                    {
                        "llm_base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                        "llm_model": "mimo-v2.5-pro",
                        "llm_api_format": "anthropic",
                    },
                    {"id": 1},
                )
                raise AssertionError("应抛出 400")
            except HTTPException as e:
                assert e.status_code == 400
                assert "anthropic" in str(e.detail)
                assert "chat" in str(e.detail) or "responses" in str(e.detail)


async def test_update_llm_config_accepts_supported_api_format(monkeypatch):
    """mimo OpenAI 端点选 responses → 保存成功"""
    from app.routers.profile_pkg.llm import update_my_llm_config

    def _exec(fn):
        return fn()

    with patch(
        "app.routers.profile_pkg.llm.run_db", new_callable=AsyncMock
    ) as mock_run_db:
        mock_run_db.side_effect = _exec
        with patch("app.routers.profile_pkg.llm.get_db_connection") as mock_get_conn:
            conn = MagicMock()
            conn.__enter__.return_value = conn
            conn.__exit__.return_value = None
            conn.execute.return_value.fetchone.return_value = None
            mock_get_conn.return_value = conn
            result = await update_my_llm_config(
                {
                    "llm_base_url": "https://token-plan-cn.xiaomimimo.com/v1",
                    "llm_model": "mimo-v2.5-pro",
                    "llm_api_format": "responses",
                    "llm_thinking": False,
                },
                {"id": 1},
            )

    assert result["status"] == "success"
    # upsert 写入 api_format / thinking
    sql, params = conn.execute.call_args_list[-1][0]
    assert "api_format" in sql
    assert "thinking" in sql
    assert "responses" in params
    assert params[-1] == 0


def test_resolve_api_format_prefers_user_config(monkeypatch):
    """用户配置了 api_format 时优先于自动检测"""
    from app.services.llm import resolve_api_format

    monkeypatch.setattr(
        "app.core.config.get_user_llm_config",
        lambda user_id: {
            "api_key": "tp-test",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo-v2.5-pro",
            "timeout": 120,
            "api_format": "responses",
            "thinking": 0,
        },
    )
    assert (
        resolve_api_format("https://token-plan-cn.xiaomimimo.com/v1", user_id=1)
        == "responses"
    )


def test_resolve_api_format_auto_falls_back_to_detection(monkeypatch):
    """api_format=auto → 按端点能力自动检测（mimo 默认 chat）"""
    from app.services.llm import resolve_api_format

    monkeypatch.setattr(
        "app.core.config.get_user_llm_config",
        lambda user_id: {
            "api_key": "tp-test",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo-v2.5-pro",
            "timeout": 120,
            "api_format": "auto",
            "thinking": 0,
        },
    )
    assert (
        resolve_api_format("https://token-plan-cn.xiaomimimo.com/v1", user_id=1)
        == "chat"
    )


async def test_call_llm_thinking_reads_user_config(monkeypatch):
    """thinking 参数为 None 时从用户配置读取（mimo + thinking=1 → 不传 extra_body）"""
    captured = {}

    class _FakeCompletions:
        def __init__(self, captured):
            self._captured = captured

        async def create(self, **kwargs):
            self._captured.update(kwargs)
            return type(
                "R",
                (),
                {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})})()]},
            )()

    class _FakeChat:
        def __init__(self, captured):
            self.completions = _FakeCompletions(captured)

    class _FakeClient:
        def __init__(self, captured):
            self.chat = _FakeChat(captured)

    fake_client = _FakeClient(captured)
    monkeypatch.setattr(
        "app.services.llm._resolve_client_and_model",
        lambda user_id: (
            fake_client,
            "mimo-v2.5-pro",
            60,
            "https://token-plan-cn.xiaomimimo.com/v1",
            "openai",
        ),
    )
    monkeypatch.setattr(
        "app.core.config.get_user_llm_config",
        lambda user_id: {
            "api_key": "tp-test",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo-v2.5-pro",
            "timeout": 120,
            "api_format": "auto",
            "thinking": 1,
        },
    )
    from app.services.llm import _call_llm_with_retry

    await _call_llm_with_retry("测试", user_id=1)

    assert "extra_body" not in captured

"""Model status probe tests — check_llm_status 探测、缓存与路由。"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError

from app.services import llm as llm_service

USER_ID = 42
CFG = {
    "api_key": "sk-test-placeholder-key",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o",
    "timeout": 120,
}
ANTHROPIC_CFG = {**CFG, "base_url": "https://api.anthropic.com"}


@pytest.fixture(autouse=True)
def _clear_caches():
    llm_service._llm_status_cache.clear()
    llm_service._user_client_cache.clear()
    yield
    llm_service._llm_status_cache.clear()
    llm_service._user_client_cache.clear()


def _patch_config(monkeypatch, cfg):
    monkeypatch.setattr(
        "app.core.config.get_user_llm_config",
        lambda uid: dict(cfg) if cfg else None,
    )


def _fail_probe(mock_llm, exc):
    mock_llm.chat.completions.create = AsyncMock(side_effect=exc)


# ── 未配置 ──


async def test_not_configured_returns_configured_false(monkeypatch, mock_llm):
    _patch_config(monkeypatch, None)
    status = await llm_service.check_llm_status(USER_ID)
    assert status == {
        "configured": False,
        "connected": False,
        "error": None,
        "model": None,
    }
    mock_llm.chat.completions.create.assert_not_called()


# ── 探测成功（OpenAI / Anthropic）──


async def test_probe_success_openai(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    status = await llm_service.check_llm_status(USER_ID)
    assert status["configured"] is True
    assert status["connected"] is True
    assert status["error"] is None
    assert status["model"] == "gpt-4o"
    mock_llm.chat.completions.create.assert_awaited_once()


async def test_probe_success_anthropic(monkeypatch):
    _patch_config(monkeypatch, ANTHROPIC_CFG)
    with patch("app.services.llm.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_cls.return_value = mock_client
        status = await llm_service.check_llm_status(USER_ID)
    assert status["connected"] is True
    mock_client.messages.create.assert_awaited_once()


# ── 探测失败分类 ──


async def test_probe_auth_failure_classified(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    _fail_probe(
        mock_llm,
        AuthenticationError("bad key", response=MagicMock(status_code=401), body=None),
    )
    status = await llm_service.check_llm_status(USER_ID)
    assert status["configured"] is True
    assert status["connected"] is False
    assert "API Key" in status["error"]


async def test_probe_connection_failure_classified(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    _fail_probe(mock_llm, APIConnectionError(request=MagicMock()))
    status = await llm_service.check_llm_status(USER_ID)
    assert status["connected"] is False
    assert "Base URL" in status["error"]


async def test_probe_timeout_classified(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    _fail_probe(mock_llm, APITimeoutError(request=MagicMock()))
    status = await llm_service.check_llm_status(USER_ID)
    assert status["connected"] is False
    assert "超时" in status["error"]


async def test_probe_unknown_error_has_message(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    _fail_probe(mock_llm, RuntimeError("boom"))
    status = await llm_service.check_llm_status(USER_ID)
    assert status["connected"] is False
    assert status["error"]


# ── 缓存 ──


async def test_cached_status_skips_second_probe(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    first = await llm_service.check_llm_status(USER_ID)
    second = await llm_service.check_llm_status(USER_ID)
    assert first["connected"] is True and second["connected"] is True
    assert mock_llm.chat.completions.create.await_count == 1


async def test_cached_failure_is_reused(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    _fail_probe(mock_llm, RuntimeError("boom"))
    await llm_service.check_llm_status(USER_ID)
    await llm_service.check_llm_status(USER_ID)
    assert mock_llm.chat.completions.create.await_count == 1


async def test_force_probe_bypasses_cache(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    await llm_service.check_llm_status(USER_ID)
    await llm_service.check_llm_status(USER_ID, force_probe=True)
    assert mock_llm.chat.completions.create.await_count == 2


async def test_expired_cache_triggers_probe(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    llm_service._llm_status_cache[USER_ID] = (
        (CFG["api_key"], CFG["base_url"], CFG["model"]),
        True,
        None,
        time.time() - llm_service._LLM_STATUS_CACHE_TTL - 1,
    )
    await llm_service.check_llm_status(USER_ID)
    assert mock_llm.chat.completions.create.await_count == 1


async def test_config_fingerprint_change_invalidates_cache(monkeypatch, mock_llm):
    _patch_config(monkeypatch, CFG)
    llm_service._llm_status_cache[USER_ID] = (
        ("old-key", "old-url", "old-model"),
        True,
        None,
        time.time(),
    )
    await llm_service.check_llm_status(USER_ID)
    assert mock_llm.chat.completions.create.await_count == 1


def test_clear_status_cache_removes_entry():
    llm_service._llm_status_cache[USER_ID] = (
        ("a", "b", "c"),
        True,
        None,
        time.time(),
    )
    llm_service.clear_llm_status_cache(USER_ID)
    assert USER_ID not in llm_service._llm_status_cache


# ── 路由 ──


def _create_user(conn, username="testuser"):
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, "hashed"),
    )
    conn.commit()
    return conn.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()["id"]


@pytest.fixture
def auth_client(client, test_db):
    """带认证的 TestClient"""
    from app.asgi import app
    from app.core.auth import get_current_user

    user_id = _create_user(test_db)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": user_id,
        "username": "testuser",
        "is_admin": 0,
    }

    yield client, user_id

    app.dependency_overrides.clear()


def test_status_route_not_configured(auth_client, monkeypatch):
    client, _ = auth_client
    _patch_config(monkeypatch, None)
    resp = client.get("/api/profile/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is False
    assert data["connected"] is False


def test_status_route_with_probe_flag(auth_client, monkeypatch, mock_llm):
    client, _ = auth_client
    _patch_config(monkeypatch, CFG)
    resp = client.get("/api/profile/llm/status?probe=1")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True
    mock_llm.chat.completions.create.assert_awaited_once()


def test_update_llm_config_clears_status_cache(auth_client, test_db):
    client, user_id = auth_client
    llm_service._llm_status_cache[user_id] = (
        ("a", "b", "c"),
        True,
        None,
        time.time(),
    )
    resp = client.put(
        "/api/profile/llm",
        json={
            "llm_api_key": "sk-new-placeholder-key",
            "llm_base_url": "https://api.openai.com/v1",
            "llm_model": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 200
    assert user_id not in llm_service._llm_status_cache

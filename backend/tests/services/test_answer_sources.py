import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.migrations import _migration_063_answer_sources


def test_migration_creates_answer_sources_column(test_db):
    """question_bank 应有 answer_sources 列（联网搜索来源 JSON）"""
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    assert "answer_sources" in columns


def test_migration_is_idempotent(test_db):
    """重复执行 063 迁移不抛异常，列保持存在"""
    _migration_063_answer_sources(test_db)
    test_db.commit()
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    assert "answer_sources" in columns


def _executing_run_db(mock_run_db, mock_question):
    """模拟真实 run_db 语义：第一次调用返回 mock_question，后续调用执行传入的函数"""

    calls = 0

    async def _run(func):
        nonlocal calls
        calls += 1
        return mock_question if calls == 1 else func()

    mock_run_db.side_effect = _run


@pytest.mark.asyncio
async def test_generate_answer_admin_writes_answer_sources():
    """管理员单题生成：有搜索结果时 answer_sources 落库为 JSON"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}
    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "官方文档"}
    ]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        _executing_run_db(mock_run_db, mock_question)
        with patch("app.routers.answers.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn
            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "微服务是一种架构风格..."
                with patch(
                    "app.routers.answers.prepare_answer_prompt",
                    new_callable=AsyncMock,
                ) as mock_prep:
                    mock_prep.return_value = ("prompt", sources)
                    result = await generate_master_answer(10, user)

    assert result["search_sources"] == sources
    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert json.loads(params[1]) == sources


@pytest.mark.asyncio
async def test_generate_answer_writes_null_when_no_sources():
    """无搜索结果（未配置搜索/搜索失败）时 answer_sources 写 NULL"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        _executing_run_db(mock_run_db, mock_question)
        with patch("app.routers.answers.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_get_conn.return_value = mock_conn
            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "微服务是一种架构风格..."
                with patch(
                    "app.routers.answers.prepare_answer_prompt",
                    new_callable=AsyncMock,
                ) as mock_prep:
                    mock_prep.return_value = ("prompt", [])
                    result = await generate_master_answer(10, user)

    assert result["search_sources"] == []
    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert params[1] is None

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


def _exec(fn):
    return fn()


@pytest.mark.asyncio
async def test_agent_generate_answer_node_writes_answer_sources(test_db):
    """Agent 批量生成节点：有搜索结果时 answer_sources 落库为 JSON"""
    from app.agents.batch_generate.nodes import generate_answer_node

    test_db.execute(
        "INSERT INTO question_bank (id, question, ai_answer) VALUES (20, 'Redis持久化', NULL)"
    )
    test_db.commit()

    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "x"}
    ]

    async def _run_db_sync(func):
        return func()

    with patch(
        "app.db.connection.run_db", side_effect=_run_db_sync
    ), patch(
        "app.db.connection.get_db_connection", return_value=test_db
    ), patch(
        # 节点内是函数级 import（from app.services.answer_enrichment import ...），
        # 必须 patch 源模块，不能 patch nodes 模块属性
        "app.services.answer_enrichment.prepare_answer_prompt",
        new_callable=AsyncMock,
    ) as mock_prep, patch(
        "app.services.llm._call_llm_with_retry", new_callable=AsyncMock
    ) as mock_llm:
        mock_prep.return_value = ("prompt", sources)
        mock_llm.return_value = "Redis 支持 RDB 和 AOF 两种持久化"

        state = {
            "question_ids": [20],
            "current_index": 0,
            "user_id": 1,
            "success_count": 0,
            "fail_count": 0,
        }
        result = await generate_answer_node(state)

    assert result["success_count"] == 1
    row = test_db.execute(
        "SELECT ai_answer, answer_sources FROM question_bank WHERE id = 20"
    ).fetchone()
    assert row["ai_answer"] == "Redis 支持 RDB 和 AOF 两种持久化"
    assert json.loads(row["answer_sources"]) == sources


@pytest.mark.asyncio
async def test_background_generate_answer_writes_answer_sources():
    """后台流水线生成：answer_sources 随 ai_answer 一起写库"""
    from app.services.submit_service import background_generate_answer

    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "x"}
    ]

    # 注意：submit_service.background_generate_answer 的 prepare_answer_prompt /
    # _call_llm_with_retry 是函数内 import（from app.services.answer_enrichment / llm），
    # 必须 patch 源模块，不能 patch submit_service 模块属性。
    with patch(
        "app.services.answer_enrichment.prepare_answer_prompt",
        new_callable=AsyncMock,
    ) as mock_prep:
        mock_prep.return_value = ("prompt", sources)
        with patch(
            "app.services.llm._call_llm_with_retry", new_callable=AsyncMock
        ) as mock_llm:
            mock_llm.return_value = "答案内容"
            with patch(
                "app.services.submit_service.run_db", new_callable=AsyncMock
            ) as mock_run_db:
                # run_db 必须 mock 成「执行传入函数」的版本（AsyncMock side_effect
                # 列表不会执行函数），否则 _update 闭包不会运行
                mock_run_db.side_effect = _exec
                with patch(
                    "app.services.submit_service.get_db_connection"
                ) as mock_get_conn:
                    mock_conn = MagicMock()
                    mock_conn.__enter__.return_value = mock_conn
                    mock_conn.__exit__.return_value = None
                    mock_get_conn.return_value = mock_conn
                    await background_generate_answer(10, "什么是微服务？", user_id=1)

    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert json.loads(params[1]) == sources


@pytest.mark.asyncio
async def test_batch_generate_writes_answer_sources():
    """批量生成：_gen_one 的 UPDATE 落库 answer_sources（SSE 流驱动）"""
    from app.models.schemas import BatchGenerateAnswersRequest
    from app.routers.answers import batch_generate_answers

    user = {"id": 1, "is_admin": True}
    rows = [{"id": 10, "question": "什么是微服务？", "ai_answer": None}]
    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = _exec
        with patch("app.routers.answers.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn
            mock_conn.__exit__.return_value = None
            # _load 阶段：conn.execute(...).fetchall() 返回待生成题目行
            mock_conn.execute.return_value.fetchall.return_value = rows
            mock_get_conn.return_value = mock_conn
            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "答案内容"
                with patch(
                    "app.routers.answers.prepare_answer_prompt",
                    new_callable=AsyncMock,
                ) as mock_prep:
                    mock_prep.return_value = ("prompt", sources)
                    req = BatchGenerateAnswersRequest(ids=[10])
                    resp = await batch_generate_answers(req, user)
                    # SSE StreamingResponse：驱动 event_stream 生成器消费事件
                    chunks = []
                    async for chunk in resp.body_iterator:
                        chunks.append(chunk)

    assert "".join(chunks)  # SSE 流正常产出事件
    update_calls = [
        call
        for call in mock_conn.execute.call_args_list
        if call.args and "answer_sources" in call.args[0]
    ]
    assert len(update_calls) == 1
    assert json.loads(update_calls[0].args[1][1]) == sources


@pytest.mark.asyncio
async def test_master_bank_list_returns_answer_sources_array():
    """列表 API 返回解析后的 answer_sources 数组"""
    from app.routers.questions import get_master_bank

    row = {
        "id": 10,
        "question": "什么是微服务？",
        "cat1": "架构",
        "cat2": "",
        "tags": "",
        "difficulty": "L2",
        "ai_answer": "答",
        "sources": "[]",
        "original_questions": "[]",
        "original_question_sources": "[]",
        "is_starred": 0,
        "user_answer": "",
        "review_state": "new",
        "proficiency": 0,
        "review_count": 0,
        "last_rating": None,
        "last_reviewed_at": None,
        "next_review_at": None,
        "interval_days": 0,
        "ease_factor": 2.3,
        "owner_id": None,
        "status": "approved",
        "job_position": "",
        "answer_sources": json.dumps(
            [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
        ),
    }
    filter_counts = {
        "overall_total": 1,
        "category_counts": [],
        "popular_tags": [],
        "filtered_tag_counts": [],
    }
    user = {"id": 1, "is_admin": True}

    with patch("app.routers.questions.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [(1, [row]), {}, filter_counts]
        resp = await get_master_bank(
            page=1, page_size=50, compact=False, filter="all", user=user
        )

    item = resp["items"][0]
    assert item["answer_sources"] == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]


@pytest.mark.asyncio
async def test_master_bank_list_returns_null_without_sources():
    """无来源时列表 API 返回 answer_sources = None"""
    from app.routers.questions import get_master_bank

    row = {
        "id": 11,
        "question": "什么是微服务？",
        "cat1": "架构",
        "cat2": "",
        "tags": "",
        "difficulty": "L2",
        "ai_answer": "答",
        "sources": "[]",
        "original_questions": "[]",
        "original_question_sources": "[]",
        "is_starred": 0,
        "user_answer": "",
        "review_state": "new",
        "proficiency": 0,
        "review_count": 0,
        "last_rating": None,
        "last_reviewed_at": None,
        "next_review_at": None,
        "interval_days": 0,
        "ease_factor": 2.3,
        "owner_id": None,
        "status": "approved",
        "job_position": "",
        "answer_sources": None,
    }
    filter_counts = {
        "overall_total": 1,
        "category_counts": [],
        "popular_tags": [],
        "filtered_tag_counts": [],
    }
    user = {"id": 1, "is_admin": True}

    with patch("app.routers.questions.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [(1, [row]), {}, filter_counts]
        resp = await get_master_bank(
            page=1, page_size=50, compact=False, filter="all", user=user
        )

    assert resp["items"][0]["answer_sources"] is None


@pytest.mark.asyncio
async def test_question_detail_returns_answer_sources(test_db):
    """详情 API 返回解析后的 answer_sources 数组"""
    from app.routers.questions import get_question_detail

    row = {
        "id": 10,
        "ai_answer": "答",
        "user_answer": "",
        "original_question_sources": "[]",
        "answer_sources": json.dumps(
            [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
        ),
    }
    with patch("app.routers.questions.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.return_value = row
        result = await get_question_detail(10, {"id": 1, "is_admin": True})

    assert result["answer_sources"] == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]


def test_compact_merge_inherits_answer_sources_from_merged(test_db):
    """孤岛合并：survivor 无答案时，从被合并题继承 ai_answer 和 answer_sources"""
    from app.services.pipeline.compact import _do_merge_to_existing

    test_db.execute(
        "INSERT INTO question_bank (id, question, ai_answer, answer_sources, frequency, status, sources, original_questions, original_question_sources) "
        "VALUES (1, '什么是 Redis？', NULL, NULL, 2, 'approved', '[]', '[]', '[]')"
    )
    test_db.commit()

    entry = {
        "id": 2,
        "question": "Redis 是什么",
        "sources": [],
        "original_questions": [],
        "original_question_sources": [],
        "ai_answer": "Redis 是内存数据库",
        "answer_sources": json.dumps(
            [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
        ),
    }
    _do_merge_to_existing(
        1,
        entry,
        operation_type="auto",
        phase="test",
        cat2="",
        operator_id=1,
        confidence=0.5,
    )

    row = test_db.execute(
        "SELECT ai_answer, answer_sources FROM question_bank WHERE id = 1"
    ).fetchone()
    assert row["ai_answer"] == "Redis 是内存数据库"
    assert json.loads(row["answer_sources"]) == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]


def test_apply_matched_keeps_existing_answer_sources(test_db):
    """apply_matched：survivor 已有答案时 answer_sources 保持不变"""
    from app.services.pipeline.writer import apply_matched

    test_db.execute(
        "INSERT INTO question_bank (id, question, ai_answer, answer_sources, frequency, status, sources, original_questions, original_question_sources, job_position, deleted_at) "
        "VALUES (1, '什么是 Redis？', '已有答案', ?, 2, 'approved', '[]', '[]', '[]', '后端开发', NULL)",
        (
            json.dumps(
                [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
            ),
        ),
    )
    test_db.commit()

    matched = [
        {
            "cluster_id": 1,
            "url": "https://example.com/mianshi",
            "company": "某公司",
            "round": "一面",
            "question": "Redis 集群怎么搭建",
        }
    ]
    apply_matched(test_db, matched, "后端开发", {})

    row = test_db.execute(
        "SELECT ai_answer, answer_sources FROM question_bank WHERE id = 1"
    ).fetchone()
    assert row["ai_answer"] == "已有答案"
    assert json.loads(row["answer_sources"]) == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]

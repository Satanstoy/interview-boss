import asyncio
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
    """管理员单题生成改为持久化 ARQ 任务，结果由 worker 写入 answer_sources。"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}
    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "官方文档"}
    ]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
         patch("app.routers.answers._queue_answer_job", new_callable=AsyncMock) as mock_queue:
        mock_run_db.return_value = mock_question
        mock_queue.return_value = {"status": "queued", "job_id": 7}
        result = await generate_master_answer(10, user, allow_no_search=True)

    assert result == {"status": "queued", "job_id": 7}
    mock_queue.assert_awaited_once_with(
        "generate_answer", 10, mock_question["question"], 1,
        llm_scope="global", search_scope="public", skip_search=True
    )


@pytest.mark.asyncio
async def test_generate_answer_writes_null_when_no_sources():
    """答案来源由 ARQ worker 结果负责写入，接口只创建 durable job。"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
         patch("app.routers.answers._queue_answer_job", new_callable=AsyncMock) as mock_queue:
        mock_run_db.return_value = mock_question
        mock_queue.return_value = {"status": "pending", "job_id": 8}
        result = await generate_master_answer(10, user)

    assert result == {"status": "pending", "job_id": 8}


@pytest.mark.asyncio
async def test_generate_answer_force_requeues_existing_answer():
    """管理员强制刷新时，已有旧答案也必须进入最新生成接口。"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {
        "id": 10,
        "question": "什么是微服务？",
        "ai_answer": "旧答案（没有 Exa 来源）",
    }

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
         patch("app.routers.answers._queue_answer_job", new_callable=AsyncMock) as mock_queue:
        mock_run_db.return_value = mock_question
        mock_queue.return_value = {"status": "queued", "job_id": 9}
        result = await generate_master_answer(10, user, force=True, allow_no_search=True)

    assert result == {"status": "queued", "job_id": 9}
    mock_queue.assert_awaited_once_with(
        "generate_answer", 10, mock_question["question"], 1,
        llm_scope="global", search_scope="public", skip_search=True
    )


@pytest.mark.asyncio
async def test_generate_answer_requires_explicit_no_search_confirmation():
    """没有个人或公共搜索配置时，接口先返回可识别的确认错误。"""
    from fastapi import HTTPException

    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [mock_question, {"configured": False}]
        with pytest.raises(HTTPException) as exc_info:
            await generate_master_answer(10, user, allow_no_search=False)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "SEARCH_NOT_CONFIGURED"


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
    assert row["ai_answer"].startswith("Redis 支持 RDB 和 AOF 两种持久化")
    assert "[Redis 官方文档](https://redis.io/docs)" in row["ai_answer"]
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
                    with patch(
                        "app.services.answer_enrichment.refine_answer",
                        new_callable=AsyncMock,
                    ) as mock_refine:
                        mock_refine.return_value = ("答案内容", [])
                        await background_generate_answer(10, "什么是微服务？", user_id=1)

    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert json.loads(params[1]) == sources


@pytest.mark.asyncio
async def test_background_generate_answer_does_not_overwrite_existing_answer():
    """外部接口失败时，已有参考答案不能被失败占位符覆盖。"""
    from app.services.submit_service import background_generate_answer

    with patch(
        "app.services.answer_enrichment.prepare_answer_prompt",
        new_callable=AsyncMock,
    ) as mock_prep, patch(
        "app.services.llm._call_llm_with_retry",
        new_callable=AsyncMock,
    ) as mock_llm, patch(
        "app.services.submit_service.run_db",
        new_callable=AsyncMock,
    ) as mock_run_db, patch(
        "app.services.submit_service.get_db_connection"
    ) as mock_get_conn:
        mock_prep.return_value = ("prompt", [])
        mock_llm.side_effect = TimeoutError("upstream timeout")
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.__exit__.return_value = None
        mock_get_conn.return_value = mock_conn
        mock_run_db.side_effect = _exec

        await background_generate_answer(
            10,
            "什么是微服务？",
            user_id=1,
            raise_on_error=False,
        )

    sql, params = mock_conn.execute.call_args[0]
    assert "CASE" in sql
    assert "TRIM(ai_answer)" in sql
    assert params == (10,)


@pytest.mark.asyncio
async def test_batch_generate_writes_answer_sources():
    """批量生成通过 durable child jobs 派发，不在 SSE 请求内调用 LLM。"""
    from app.models.schemas import BatchGenerateAnswersRequest
    from app.routers.answers import batch_generate_answers

    user = {"id": 1, "is_admin": True}
    rows = [{"id": 10, "question": "什么是微服务？", "ai_answer": None}]
    async def _consume(resp):
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
         patch("app.routers.answers._dispatch_persisted_answer_job", new_callable=AsyncMock) as mock_dispatch:
        mock_run_db.side_effect = [
            rows,
            {"configured": False},
            (99, [100]),
            [{"id": 10, "status": "completed", "error": None}],
        ]
        response = await batch_generate_answers(
            BatchGenerateAnswersRequest(ids=[10], allow_no_search=True), user
        )
        body = await _consume(response)

    assert '"type": "init"' in body
    assert '"type": "done"' in body
    mock_dispatch.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_batch_generate_force_includes_existing_answers():
    """批量强制刷新不得把已有旧答案计入 skipped。"""
    from app.models.schemas import BatchGenerateAnswersRequest
    from app.routers.answers import batch_generate_answers

    user = {"id": 1, "is_admin": True}
    rows = [{"id": 10, "question": "什么是微服务？", "ai_answer": "旧答案"}]

    async def _consume(resp):
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
         patch("app.routers.answers._dispatch_persisted_answer_job", new_callable=AsyncMock) as mock_dispatch:
        mock_run_db.side_effect = [
            rows,
            {"configured": False},
            (99, [100]),
            [{"id": 10, "status": "completed", "error": None}],
        ]
        response = await batch_generate_answers(
            BatchGenerateAnswersRequest(ids=[10], force=True, allow_no_search=True), user
        )
        body = await _consume(response)

    assert '"skipped": 0' in body
    mock_dispatch.assert_awaited_once_with(100)


@pytest.mark.asyncio
async def test_batch_generate_emits_init_and_done_from_durable_status():
    """批量 SSE 根据 durable child job 状态收尾。"""
    from app.models.schemas import BatchGenerateAnswersRequest
    from app.routers import answers as answers_router

    user = {"id": 1, "is_admin": True}
    rows = [{"id": 11, "question": "慢题", "ai_answer": None}]
    async def consume(resp):
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
        return [
            json.loads(line[6:])
            for chunk in chunks
            for line in (chunk.decode() if isinstance(chunk, bytes) else chunk).splitlines()
            if line.startswith("data: ")
        ]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
        patch("app.routers.answers._dispatch_persisted_answer_job", new_callable=AsyncMock):
        mock_run_db.side_effect = [
            rows,
            {"configured": False},
            (101, [111]),
            [{"id": 11, "status": "completed", "error": None}],
        ]

        response = await answers_router.batch_generate_answers(
            BatchGenerateAnswersRequest(ids=[11], allow_no_search=True), user
        )
        events = await consume(response)

    assert events[0]["type"] == "init"
    assert events[-1]["type"] == "done"
    assert events[-1]["generated"] == 1


@pytest.mark.asyncio
async def test_batch_generate_reports_terminal_child_failure():
    """子任务最终失败时，批量 SSE 返回失败统计。"""
    from app.models.schemas import BatchGenerateAnswersRequest
    from app.routers import answers as answers_router

    user = {"id": 1, "is_admin": True}
    rows = [{"id": 12, "question": "超时题", "ai_answer": None}]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db, \
        patch("app.routers.answers._dispatch_persisted_answer_job", new_callable=AsyncMock):
        mock_run_db.side_effect = [
            rows,
            {"configured": False},
            (102, [112]),
            [{"id": 12, "status": "failed", "error": "API 限流"}],
        ]

        response = await answers_router.batch_generate_answers(
            BatchGenerateAnswersRequest(ids=[12], allow_no_search=True), user
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    events = [
        json.loads(line[6:])
        for chunk in chunks
        for line in (chunk.decode() if isinstance(chunk, bytes) else chunk).splitlines()
        if line.startswith("data: ")
    ]
    assert events[-2]["type"] == "progress"
    assert events[-2]["success"] is False
    assert events[-1] == {
        "type": "done",
        "job_id": 102,
        "generated": 0,
        "failed": 1,
        "skipped": 0,
    }


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
async def test_master_bank_compact_list_keeps_answer_source_links():
    """compact 列表也必须带来源链接，供题卡直接显示来源数量。"""
    from app.routers.questions import get_master_bank

    row = {
        "id": 12,
        "question": "Redis 为什么快？",
        "cat1": "后端",
        "cat2": "缓存",
        "tags": "",
        "difficulty": "L2",
        "ai_answer": "完整答案",
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
            [
                {
                    "title": "Redis 官方文档",
                    "url": "https://redis.io/docs",
                    "snippet": "长摘要不应进入 compact 列表",
                }
            ]
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
            page=1, page_size=50, compact=True, filter="all", user=user
        )

    item = resp["items"][0]
    assert item["ai_answer"] is None
    assert item["answer_sources"] == [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs"}
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

"""MCP job-position discovery, normalization, and session safety tests."""

import asyncio

import pytest


def test_position_aliases_resolve_without_fuzzy_matching():
    from app.services.job_position_service import resolve_job_position

    rows = [
        {
            "id": 1,
            "name": "agent开发/大模型应用开发/大模型开发",
            "description": "",
        },
        {"id": 2, "name": "后端开发", "description": ""},
    ]

    for value in (
        "Agent开发",
        "Agent 开发",
        "Agent开发/大模型应用开发/大模型开发",
        " agent开发 / 大模型应用开发 / 大模型开发 ",
    ):
        resolution = resolve_job_position(value, position_rows=rows)
        assert resolution is not None
        assert resolution.canonical_name == "Agent开发"
        assert resolution.position_id == 1

    assert resolve_job_position("前端和后端都做", position_rows=rows) is None
    assert resolve_job_position("", position_rows=rows) is None


def test_list_job_positions_uses_active_rows_and_returns_aliases(test_db):
    from app.services.job_position_service import list_job_positions

    columns = {row[1] for row in test_db.execute("PRAGMA table_info(job_positions)")}
    if "is_deleted" not in columns:
        test_db.execute(
            "ALTER TABLE job_positions ADD COLUMN is_deleted INTEGER DEFAULT 0"
        )
    test_db.execute(
        "INSERT INTO job_positions (id, name, description, is_deleted) "
        "VALUES (901, ?, ?, 0)",
        (
            "agent开发/大模型应用开发/大模型开发",
            "Agent、LLM 应用和大模型应用开发岗位",
        ),
    )
    test_db.execute(
        "INSERT INTO job_positions (id, name, description, is_deleted) "
        "VALUES (902, ?, ?, 0)",
        ("后端开发", "后端服务开发岗位"),
    )
    test_db.execute(
        "INSERT INTO job_positions (id, name, description, is_deleted) "
        "VALUES (903, ?, ?, 1)",
        ("已删除岗位", "不应出现"),
    )
    test_db.commit()

    items = list_job_positions()
    names = [item["name"] for item in items]

    assert "Agent开发" in names
    assert "后端开发" in names
    assert all("并发测试岗位" not in name for name in names)
    agent = next(item for item in items if item["name"] == "Agent开发")
    assert "Agent 开发" in agent["aliases"]
    assert "Agent开发/大模型应用开发/大模型开发" in agent["aliases"]
    assert agent["description"]


@pytest.mark.asyncio
async def test_list_job_positions_db_error_is_stable(monkeypatch):
    from app.mcp_server import interview_tools

    async def fail():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(interview_tools, "_list_job_positions_for_tool", fail)
    result = await interview_tools.list_job_positions_tool({}, {})

    assert result["ok"] is False
    assert result["tool"] == "list_job_positions"
    assert result["items"] == []
    assert result["error"]["error_code"] == "SERVICE_ERROR"


@pytest.mark.asyncio
async def test_search_alias_passes_canonical_position_and_id(test_db, monkeypatch):
    from app.mcp_server import interview_tools

    captured = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [
            {
                "id": 1,
                "question": "Agent 架构如何拆分？",
                "cat1": "Agent",
                "cat2": "架构",
                "tags": "agent",
            }
        ]

    monkeypatch.setattr(interview_tools, "_hybrid_search_for_tool", fake_search)
    result = await interview_tools.search_questions_tool(
        {"keywords": ["Agent"]},
        {"user_id": 7, "bank_mode": "public", "job_position": "Agent 开发"},
    )

    assert result["ok"] is True
    assert captured["job_position"] == "Agent开发"
    assert captured["job_position_id"] == 1


@pytest.mark.asyncio
async def test_unknown_position_is_not_a_database_error(test_db, monkeypatch):
    from app.mcp_server import interview_tools

    async def should_not_search(**kwargs):
        raise AssertionError("unknown position must be rejected before retrieval")

    monkeypatch.setattr(interview_tools, "_hybrid_search_for_tool", should_not_search)
    result = await interview_tools.search_questions_tool(
        {"keywords": ["RAG"]},
        {"user_id": 7, "bank_mode": "public", "job_position": "不存在岗位"},
    )

    assert result["ok"] is False
    assert result["error"]["error_code"] == "UNKNOWN_JOB_POSITION"
    assert result["metadata"]["empty_reason"] == "unknown_job_position"
    assert "后端开发" in result["metadata"]["suggestions"]


@pytest.mark.asyncio
async def test_draw_alias_is_filtered_and_empty_does_not_fallback(test_db, monkeypatch):
    from app.mcp_server import interview_tools

    captured = {}

    async def fake_draw(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(interview_tools, "_draw_questions_for_tool", fake_draw)
    result = await interview_tools.draw_questions_tool(
        {"topic": "Agent架构", "count": 2},
        {
            "user_id": 7,
            "bank_mode": "public",
            "job_position": "Agent开发/大模型应用开发/大模型开发",
        },
    )

    assert result["ok"] is True
    assert result["items"] == []
    assert result["metadata"]["empty_reason"] == "no_match"
    assert result["metadata"]["fallback_used"] is False
    assert "题库为空" in result["metadata"]["message"]
    assert captured["job_position"] == "Agent开发"


def test_select_rejects_mismatched_server_source():
    from app.mcp_server.interview_tools import select_question_tool

    result = select_question_tool(
        {"question_source": "search"},
        {
            "user_id": 7,
            "question_source": "draw",
            "candidate_questions": [{"id": 1, "question": "Q"}],
        },
        candidate_index=0,
    )

    assert result["ok"] is False
    assert result["error"]["error_code"] == "QUESTION_SOURCE_MISMATCH"


@pytest.mark.asyncio
async def test_mcp_schema_exposes_position_discovery_without_required_arguments():
    from app.mcp_server.app import mcp

    tools = await mcp.list_tools()
    position_tool = next(tool for tool in tools if tool.name == "list_job_positions")
    assert position_tool.inputSchema.get("required", []) == []
    assert "先调用" in position_tool.description


@pytest.mark.asyncio
async def test_redis_session_lock_serializes_same_session(monkeypatch):
    from app.mcp_server import session

    monkeypatch.setenv("ENV", "production")

    shared_lock = asyncio.Lock()

    class FakeLock:
        async def acquire(self):
            await shared_lock.acquire()
            return True

        async def release(self):
            shared_lock.release()

    class FakeRedis:
        def lock(self, name, timeout, blocking_timeout):
            return FakeLock()

    monkeypatch.setattr(session, "_get_redis_pool", lambda: FakeRedis())
    events = []

    async def run(label):
        async with session.mcp_session_lock("same", user_id=7):
            events.append(f"{label}:enter")
            await asyncio.sleep(0.01)
            events.append(f"{label}:exit")

    await asyncio.gather(run("a"), run("b"))
    assert events in (
        ["a:enter", "a:exit", "b:enter", "b:exit"],
        ["b:enter", "b:exit", "a:enter", "a:exit"],
    )


@pytest.mark.asyncio
async def test_concurrent_draws_keep_one_serialized_candidate_set(monkeypatch):
    """A concurrent same-session draw must load the previous committed state."""

    from app.agents.chat.tool_gateway import build_success_envelope
    from app.mcp_server import app as mcp_app_module
    from app.mcp_server.principal import MCPPrincipal

    session_id = "concurrent-draw-contract"
    persisted = {}
    observed_before: dict[str, list[int]] = {}

    monkeypatch.setenv("ENV", "test")
    monkeypatch.setattr(
        mcp_app_module,
        "get_mcp_principal",
        lambda: MCPPrincipal(user_id=7, bank_mode="all"),
    )
    monkeypatch.setattr(mcp_app_module, "_activate_mcp_usage_skill", lambda state: None)

    async def load_state(sid, user_id=None):
        value = persisted.get((user_id, sid))
        return dict(value) if value is not None else None

    async def save_state(sid, state, user_id=None):
        persisted[(user_id, sid)] = dict(state)

    monkeypatch.setattr(mcp_app_module, "load_mcp_session_async", load_state)
    monkeypatch.setattr(mcp_app_module, "save_mcp_session_async", save_state)

    async def fake_draw(args, state):
        topic = args.get("topic") or "unknown"
        observed_before[topic] = [item["id"] for item in state.get("candidate_questions", [])]
        await asyncio.sleep(0.01 if topic == "slow" else 0)
        question_id = 101 if topic == "slow" else 202
        item = {
            "id": question_id,
            "question": f"{topic} question",
            "cat1": "Agent",
            "cat2": "架构",
            "tags": "agent",
        }
        state["candidate_questions"] = [item]
        state["retrieved_questions"] = [item]
        state["question_source"] = "draw"
        return build_success_envelope(
            tool="draw_questions",
            items=[item],
            total_ms=1,
            debug_reason="test_draw",
            fallback_used=False,
        )

    def fake_select(args, state, candidate_index=0):
        item = state["candidate_questions"][candidate_index]
        return build_success_envelope(
            tool="select_question",
            items=[item],
            total_ms=1,
            debug_reason="test_select",
        )

    monkeypatch.setattr(mcp_app_module.interview_tools, "draw_questions_tool", fake_draw)
    monkeypatch.setattr(mcp_app_module.interview_tools, "select_question_tool", fake_select)

    results = await asyncio.gather(
        mcp_app_module.draw_questions(topic="slow", session_id=session_id),
        mcp_app_module.draw_questions(topic="fast", session_id=session_id),
    )

    assert all(result["ok"] for result in results)
    assert sorted(len(value) for value in observed_before.values()) == [0, 1]
    final_state = persisted[(7, session_id)]
    assert len(final_state["candidate_questions"]) == 1

    selected = await mcp_app_module.select_question(
        session_id=session_id,
        candidate_index=0,
    )
    assert selected["ok"] is True
    assert selected["items"][0]["id"] == final_state["candidate_questions"][0]["id"]

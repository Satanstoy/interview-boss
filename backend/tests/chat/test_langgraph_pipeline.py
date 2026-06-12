"""Tests for the LangGraph-backed chat pipeline."""

import asyncio

import pytest


def test_tool_policy_overrides_legacy_routing():
    from app.agents.chat.nodes import route_after_classify

    assert route_after_classify({"tool_policy": "draw_question"}) == "draw_question"
    assert route_after_classify({"tool_policy": "none", "answer_complete": True}) == "direct_respond"
    assert route_after_classify({"tool_policy": "retrieve_related"}) == "rag_retrieve"


def test_strategy_topic_shift_uses_draw_question_policy():
    from app.agents.chat.nodes import plan_skill_guided_strategy

    result = plan_skill_guided_strategy(
        {
            "intent": "interview_question",
            "answer_complete": True,
            "user_message": "我这个方案主要通过 RRF 和 rerank 解决召回不稳定的问题。",
            "message_history": [
                {"role": "assistant", "content": "介绍一下项目。"},
                {"role": "user", "content": "我做了一个模拟面试系统。"},
                {"role": "assistant", "content": "检索链路怎么做？"},
                {"role": "user", "content": "用混合检索。"},
                {"role": "assistant", "content": "怎么做精排？"},
                {"role": "user", "content": "用 LLM。"},
                {"role": "assistant", "content": "引用如何显示？"},
                {"role": "user", "content": "后端返回 basis。"},
            ],
            "active_skills": ["interview-rhythm"],
            "active_skill_strategy_rules": {},
            "search_query": "后端 高频题",
        }
    )

    assert result["strategy"] == "topic_shift"
    assert result["tool_policy"] == "draw_question"
    assert result["strategy_should_retrieve"] is True


def test_strategy_clarification_does_not_retrieve():
    from app.agents.chat.nodes import plan_skill_guided_strategy

    result = plan_skill_guided_strategy(
        {
            "intent": "interview_question",
            "answer_complete": False,
            "user_message": "不知道。",
            "message_history": [],
            "active_skills": ["interview-rhythm"],
            "active_skill_strategy_rules": {},
        }
    )

    assert result["strategy"] == "clarification"
    assert result["tool_policy"] == "none"
    assert result["strategy_should_retrieve"] is False


def test_chat_graph_contains_expected_nodes():
    from app.agents.chat.graph import chat_graph

    mermaid = chat_graph.get_graph().draw_mermaid()
    for node_name in [
        "resolve_strategy",
        "retrieve_and_rerank",
        "draw_question",
        "generate_direct",
        "extract_memory",
    ]:
        assert node_name in mermaid


@pytest.mark.asyncio
async def test_extract_memory_node_runs_in_background(monkeypatch):
    from app.agents.chat import graph

    started = asyncio.Event()
    completed = asyncio.Event()

    async def slow_extract_memory(state):
        started.set()
        await asyncio.sleep(0.02)
        completed.set()
        return {"session_notes": "should not merge into graph state"}

    monkeypatch.setattr(graph, "extract_memory", slow_extract_memory)

    start = asyncio.get_running_loop().time()
    result = await graph.extract_memory_node({"conversation_id": "c1", "user_id": 7})
    elapsed = asyncio.get_running_loop().time() - start

    assert result == {}
    assert elapsed < 0.01
    await asyncio.wait_for(started.wait(), timeout=0.1)
    await asyncio.wait_for(completed.wait(), timeout=0.1)


@pytest.mark.asyncio
async def test_draw_question_node_emits_selected_basis(monkeypatch):
    from app.agents.chat import graph
    from app.agents.shared.events import _event_queue_var

    questions = [
        {"id": 101, "question": "Redis 缓存穿透怎么解决？", "cat1": "后端", "cat2": "Redis"},
        {"id": 102, "question": "MySQL 索引为什么会失效？", "cat1": "数据库", "cat2": "索引"},
        {"id": 103, "question": "TCP 三次握手的目的是什么？", "cat1": "网络", "cat2": "TCP"},
    ]
    calls = []

    def fake_draw_questions(**kwargs):
        calls.append(kwargs)
        excluded = kwargs.get("exclude_ids") or set()
        return [q for q in questions if q["id"] not in excluded]

    queue = asyncio.Queue()
    token = _event_queue_var.set(queue)
    monkeypatch.setattr(graph, "draw_questions", fake_draw_questions)
    monkeypatch.setattr(graph.chat_service, "get_conversation_question_ids", lambda _cid: {102})
    try:
        result = await graph.draw_question_node(
            {
                "conversation_id": "c1",
                "user_id": 7,
                "bank_mode": "public",
                "strategy_target_topic": "后端",
                "strategy_preferred_question_type": "knowledge_probe",
                "retrieved_questions": [{"id": 99}],
            }
        )
        step_event = await queue.get()
        retrieved_event = await queue.get()
    finally:
        _event_queue_var.reset(token)

    assert calls[0]["user"] == {"id": 7, "bank_mode": "public"}
    assert calls[0]["cat1"] == "后端"
    assert calls[0]["question_type"] == "knowledge_probe"
    assert calls[0]["exclude_ids"] == {99, 102}
    assert step_event["type"] == "step"
    assert step_event["step"] == "drawing"
    assert retrieved_event["type"] == "retrieved"
    assert [q["id"] for q in retrieved_event["questions"]] == [101, 103]
    assert result["basis_type"] == "drawn_question"
    assert [q["id"] for q in result["retrieved_questions"]] == [101, 103]
    assert result["rerank_metadata"]["selected_basis_ids"] == [101, 103]
    assert result["rerank_metadata"]["should_show_references"] is True
    assert result["next_question_plan"]["question_id"] == 101
    assert result["next_question_plan"]["must_ask"] is True


def test_basis_guidance_is_metadata_only():
    from app.agents.chat.prompts import BASIS_EXTRACT_GUIDANCE

    assert "[BASIS]" in BASIS_EXTRACT_GUIDANCE
    assert "不要在回复正文中输出" in BASIS_EXTRACT_GUIDANCE
    assert "必须输出一个 JSON 块" not in BASIS_EXTRACT_GUIDANCE


def test_basis_alignment_filters_unasked_rerank_basis():
    from app.agents.chat.nodes import _filter_basis_ids_by_response

    retrieved = [
        {"id": 1, "question": "说一下RRF融合算法，它的公式是什么？K参数一般怎么设？"},
        {"id": 2, "question": "cosine similarity 和 inner product 有什么区别？"},
    ]

    aligned = _filter_basis_ids_by_response(
        "你项目里用了 bge-small 做向量召回。cosine similarity 和 inner product 有什么区别？",
        [1, 2],
        retrieved,
    )

    assert aligned == [2]


def test_question_plan_adherence_detects_topic_drift():
    from app.agents.chat.nodes import _question_plan_adherence

    plan = {
        "must_ask": True,
        "question_text": "当Agent执行一个较长链路，出现死循环，如何做自动恢复？",
        "allowed_focus": ["Agent", "死循环", "自动恢复"],
    }

    aligned = _question_plan_adherence(
        "当 Agent 链路出现死循环时，你会怎么做自动恢复？", plan
    )
    drifted = _question_plan_adherence(
        "换个方向，讲一下 HNSW 索引的核心原理。", plan
    )

    assert aligned["adheres"] is True
    assert drifted["adheres"] is False

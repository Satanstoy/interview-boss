"""End-to-end tests for the ReAct chat pipeline."""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat.pipeline import MAX_REACT_STEPS, run_chat
from app.agents.shared.events import _event_queue_var

pytestmark = pytest.mark.asyncio


def _tool_call(name: str, args: dict, tc_id: str = "call_1") -> dict:
    return {
        "id": tc_id,
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


def _stream_chunks(*chunks: str):
    async def _gen():
        for chunk in chunks:
            yield chunk

    return _gen()


async def _mock_stream(*chunks: str):
    for c in chunks:
        yield c


def _routerize_events(events: list[dict]) -> list[dict]:
    """Mirror the router's SSE conversion for the run_chat event stream."""
    sse_events: list[dict] = []
    for event in events:
        event_type = event.get("type")
        if event_type == "basis":
            continue
        if event_type == "done":
            meta = event.get("metadata", {})
            basis_type = meta.get("basis_type")
            if basis_type:
                sse_events.append(
                    {
                        "type": "basis",
                        "basis_type": basis_type,
                        "basis_question_ids": meta.get("basis_question_ids", []),
                        "basis_confidence": meta.get("basis_confidence", 0.0),
                        "should_show_references": meta.get(
                            "should_show_references", False
                        ),
                        "selected_basis_questions": meta.get(
                            "selected_basis_questions", []
                        ),
                        "resume_ref": meta.get("resume_ref", ""),
                        "jd_ref": meta.get("jd_ref", ""),
                    }
                )
            if meta.get("resume_ref"):
                sse_events.append({"type": "resume_ref", "name": meta["resume_ref"]})
            if meta.get("jd_ref"):
                sse_events.append({"type": "jd_ref", "title": meta["jd_ref"]})
            sse_events.append({"type": "done"})
            continue
        sse_events.append(event)
    return sse_events


async def test_done_metadata_can_emit_question_plan_event():
    """Router-style metadata splitting should expose question_plan as its own SSE event."""
    from app.routers.chat import _metadata_events_from_done

    meta = {
        "selected_question": {
            "id": 7,
            "question": "RAG 检索怎么设计？",
            "cat1": "B",
            "cat2": "RAG",
        },
        "question_source": "search",
        "question_source_reason": "question_plan_bound",
        "question_plan": {
            "type": "internal_plan",
            "question_id": 7,
            "source": "search",
            "selection_reason": "top_ranked_candidate",
            "adherence": {"adheres": True, "score": 0.5, "reason": "keyword_overlap"},
            "repaired": False,
            "fallback_used": False,
            "question_text": "内部题面不应直接透出",
            "strategy": "internal_strategy",
            "allowed_focus": ["RAG"],
            "forbidden_focus": ["闲聊"],
        },
    }

    events = _metadata_events_from_done(meta)

    selected = next(event for event in events if event["type"] == "selected_question")
    assert selected["question"]["id"] == 7
    assert selected["reason"] == "question_plan_bound"

    plan = next(event for event in events if event["type"] == "question_plan")
    assert plan["question_id"] == 7
    assert plan["source"] == "search"
    assert plan["selection_reason"] == "top_ranked_candidate"
    assert plan["adherence"]["score"] == 0.5
    assert plan["repaired"] is False
    assert plan["fallback_used"] is False
    assert plan["type"] == "question_plan"
    assert "question_text" not in plan
    assert "strategy" not in plan
    assert "allowed_focus" not in plan
    assert "forbidden_focus" not in plan


def _make_question(
    qid: int,
    question: str,
    *,
    cat1: str = "中间件",
    cat2: str = "缓存",
    company: str = "腾讯",
    round_name: str = "一面",
) -> dict:
    return {
        "id": qid,
        "question": question,
        "cat1": cat1,
        "cat2": cat2,
        "tags": "redis,cache",
        "sources": [{"company": company, "round": round_name}],
    }


async def _run_react_case(
    *,
    user_message: str,
    classify_updates: dict,
    llm_responses: list[dict],
    stream_chunks: tuple[str, ...],
    tool_patches: list = None,
) -> tuple[list[dict], dict, AsyncMock]:
    captured_state: dict = {}
    state_ready = asyncio.Event()

    async def mock_load_context(state):
        state.update(
            {
                "message_history": [],
                "recent_messages": [],
                "compressed_context": None,
                "session_notes": "",
                "interview_context": "目标岗位：后端开发",
                "job_position": "后端开发",
                "memory_summaries": [],
                "retrieved_questions": [],
            }
        )
        return state

    async def mock_classify(state):
        state.update(classify_updates)
        return state

    async def mock_extract_memory(snapshot):
        captured_state.clear()
        captured_state.update(snapshot)
        state_ready.set()

    llm_mock = AsyncMock(side_effect=llm_responses)

    def stream_side_effect(*args, **kwargs):
        return _stream_chunks(*stream_chunks)

    patchers = [
        patch(
            "app.agents.chat.nodes.build_react_system_prompt",
            return_value="Test ReAct prompt.",
        ),
        patch(
            "app.agents.chat.pipeline._step_load_context",
            new_callable=AsyncMock,
            side_effect=mock_load_context,
        ),
        patch(
            "app.agents.chat.pipeline._step_classify",
            new_callable=AsyncMock,
            side_effect=mock_classify,
        ),
        patch(
            "app.agents.chat.pipeline._step_extract_memory",
            new_callable=AsyncMock,
            side_effect=mock_extract_memory,
        ),
        patch("app.services.llm.llm_with_tools", new=llm_mock),
        patch(
            "app.services.llm.stream_llm_messages",
            side_effect=stream_side_effect,
        ),
    ]
    if tool_patches:
        patchers.extend(tool_patches)

    with ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)

        raw_events: list[dict] = []
        async for event in run_chat(
            conversation_id="conv-react-e2e",
            user_id=1,
            user_message=user_message,
            mode="free_practice",
            bank_mode="public",
        ):
            raw_events.append(event)

    await asyncio.wait_for(state_ready.wait(), timeout=1)
    return _routerize_events(raw_events), captured_state, llm_mock


class TestReactE2E:
    async def test_simple_dialogue_without_tools(self):
        events, state, llm_mock = await _run_react_case(
            user_message="你好",
            classify_updates={
                "intent": "chat",
                "keywords": [],
                "search_query": "",
                "answer_complete": False,
                "retrieval_intent": None,
                "search_positive_terms": [],
                "search_negative_terms": [],
                "question_type": None,
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": None,
                    "finish_reason": "stop",
                }
            ],
            stream_chunks=("你好，我在。",),
        )

        assert llm_mock.call_count == 1
        assert [e["type"] for e in events] == ["step", "chunk", "basis", "done"]
        assert events[0]["step"] == "generating"
        assert events[2]["basis_type"] == "conversation"
        assert events[2]["basis_question_ids"] == []
        assert events[2]["should_show_references"] is False
        assert events[2]["selected_basis_questions"] == []
        assert state["retrieved_questions"] == []
        assert state["metadata"]["basis_type"] == "conversation"
        assert state["metadata"]["basis_question_ids"] == []
        assert "[BASIS]" not in state["response"]

    async def test_search_questions_then_answer(self):
        search_results = [
            _make_question(101, "Redis 有哪些常见数据结构？", round_name="一面"),
            _make_question(102, "Redis 分布式锁如何实现？", round_name="二面"),
            _make_question(103, "Redis 缓存击穿怎么处理？", round_name="三面"),
            _make_question(104, "Redis 持久化策略有哪些？", round_name="四面"),
            _make_question(105, "Redis 大 key 怎么治理？", round_name="五面"),
        ]
        search_mock = MagicMock(return_value=search_results)

        events, state, llm_mock = await _run_react_case(
            user_message="给我出一道 Redis 相关的题",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["Redis", "缓存"],
                "search_query": "Redis 缓存",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["Redis", "缓存"],
                "search_negative_terms": [],
                "question_type": "knowledge_probe",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        _tool_call(
                            "search_questions",
                            {
                                "keywords": ["Redis", "缓存"],
                                "question_type": "knowledge_probe",
                            },
                        )
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": (
                        "你先讲讲 Redis 缓存穿透和布隆过滤器的关系。"
                        '[BASIS]{"type":"interview_question","question_ids":[101,102],'
                        '"confidence":0.88,"show_refs":true}[/BASIS]'
                    ),
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=(
                "你先讲讲 Redis 缓存穿透和布隆过滤器的关系。",
                '[BASIS]{"type":"interview_question","question_ids":[101,102],"confidence":0.88,"show_refs":true}[/BASIS]',
            ),
            tool_patches=[
                patch(
                    "app.mcp_server.interview_tools._hybrid_search_for_tool",
                    search_mock,
                ),
            ],
        )

        search_mock.assert_called_once()
        assert search_mock.call_args.kwargs["query_text"] == "Redis 缓存"
        assert search_mock.call_args.kwargs["question_type"] == "knowledge_probe"

        step_events = [e for e in events if e["type"] == "step"]
        assert [e["step"] for e in step_events] == ["search_questions", "generating"]

        retrieved_events = [e for e in events if e["type"] == "retrieved"]
        assert len(retrieved_events) == 1
        assert len(retrieved_events[0]["questions"]) == 5
        assert retrieved_events[0]["questions"][0]["id"] == 101
        assert retrieved_events[0]["questions"][0]["company"] == "腾讯"
        assert retrieved_events[0]["questions"][0]["round"] == "一面"
        assert retrieved_events[0]["questions"][-1]["id"] == 105

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "interview_question"
        assert basis_event["basis_question_ids"] == [101, 102]
        assert basis_event["should_show_references"] is True
        assert len(basis_event["selected_basis_questions"]) == 2
        assert basis_event["selected_basis_questions"][0]["id"] == 101

        assert state["retrieved_questions"] == search_results
        assert state["metadata"]["basis_type"] == "interview_question"
        assert len(state["metadata"]["retrieved_questions"]) == 5
        assert len(state["metadata"]["candidate_questions"]) == 5
        assert state["metadata"]["selected_question"]["id"] == 101
        assert state["metadata"]["question_source"] == "search"
        assert len(state["metadata"]["selected_basis_questions"]) == 2
        assert "[BASIS]" not in state["response"]
        assert llm_mock.call_count == 2

    async def test_load_skill_then_draw_questions(self):
        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = (
            "## Algorithm Coding\n\nAsk algorithm problems."
        )

        registry = MagicMock()
        registry.get.return_value = mock_skill

        draw_results = [
            _make_question(
                201,
                "写一个二分查找",
                cat1="算法",
                cat2="数组",
                company="字节",
                round_name="一面",
            ),
            _make_question(
                202,
                "实现一个 LRU Cache",
                cat1="算法",
                cat2="缓存",
                company="阿里",
                round_name="二面",
            ),
        ]
        draw_mock = MagicMock(return_value=draw_results)

        events, state, llm_mock = await _run_react_case(
            user_message="开始算法面试",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["算法", "面试"],
                "search_query": "算法面试",
                "answer_complete": True,
                "retrieval_intent": "expand_knowledge",
                "search_positive_terms": ["算法"],
                "search_negative_terms": [],
                "question_type": "new_question",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        _tool_call("load_skill", {"skill_name": "algorithm-coding"}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": None,
                    "tool_calls": [
                        _tool_call("draw_questions", {"count": 2}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": (
                        "我们先从写一个二分查找，再实现一个 LRU Cache 开始。"
                        '[BASIS]{"type":"interview_question","question_ids":[201,202],'
                        '"confidence":0.91,"show_refs":true}[/BASIS]'
                    ),
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=(
                "我们先从写一个二分查找，再实现一个 LRU Cache 开始。",
                '[BASIS]{"type":"interview_question","question_ids":[201,202],"confidence":0.91,"show_refs":true}[/BASIS]',
            ),
            tool_patches=[
                patch(
                    "app.agents.chat.tools._get_skill_registry", return_value=registry
                ),
                patch(
                    "app.mcp_server.interview_tools._draw_questions_for_tool", draw_mock
                ),
            ],
        )

        assert registry.get.call_args_list[0].args[0] == "algorithm-coding"
        assert draw_mock.call_count == 1
        assert draw_mock.call_args.kwargs["user"]["bank_mode"] == "public"
        assert draw_mock.call_args.kwargs["count"] == 2

        visible_events = [e for e in events if e["type"] != "insight"]
        visible_types = [e["type"] for e in visible_events]
        assert visible_types[:4] == ["step", "step", "retrieved", "step"]
        assert visible_types[-2:] == ["basis", "done"]
        assert visible_types[4:-2] == ["chunk", "chunk"]
        assert [e["step"] for e in events if e["type"] == "step"] == [
            "load_skill",
            "draw_questions",
            "generating",
        ]
        chunk_text = "".join(
            e.get("content", "") for e in events if e["type"] == "chunk"
        )
        assert "二分查找" in chunk_text
        assert "[BASIS]" in chunk_text

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "interview_question"
        assert basis_event["basis_question_ids"] == [202]
        assert len(basis_event["selected_basis_questions"]) == 1
        assert basis_event["selected_basis_questions"][0]["id"] == 202

        assert state["active_skills"] == ["algorithm-coding"]
        assert state["retrieved_questions"] == draw_results
        assert state["metadata"]["basis_type"] == "interview_question"
        assert state["metadata"]["selected_question"]["id"] == 201
        assert state["metadata"]["question_source"] == "draw"
        assert len(state["metadata"]["selected_basis_questions"]) == 1
        assert "[BASIS]" not in state["response"]
        assert mock_skill.get_instruction.call_count == 1
        assert llm_mock.call_count == 3

    async def test_tool_failure_recovers_to_direct_answer(self):
        search_mock = MagicMock(side_effect=RuntimeError("search service unavailable"))

        events, state, llm_mock = await _run_react_case(
            user_message="给我出一道 Redis 相关的题",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["Redis"],
                "search_query": "Redis",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["Redis"],
                "search_negative_terms": [],
                "question_type": "knowledge_probe",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        _tool_call("search_questions", {"keywords": ["Redis"]}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "搜索出错了，我直接给你一道基础题。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("搜索出错了，我直接给你一道基础题。",),
            tool_patches=[
                patch(
                    "app.mcp_server.interview_tools._hybrid_search_for_tool",
                    search_mock,
                ),
            ],
        )

        assert search_mock.call_count == 1
        assert [e["type"] for e in events] == ["step", "step", "chunk", "basis", "done"]
        assert [e["step"] for e in events if e["type"] == "step"] == [
            "search_questions",
            "generating",
        ]

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "conversation"
        assert basis_event["basis_question_ids"] == []
        assert basis_event["selected_basis_questions"] == []
        assert state["retrieved_questions"] == []
        assert state["metadata"]["basis_type"] == "conversation"
        assert "[BASIS]" not in state["response"]
        assert llm_mock.call_count == 2

    async def test_loop_cap_forces_final_answer(self):
        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = (
            "## Theory QA\n\nAsk theory questions."
        )

        registry = MagicMock()
        registry.get.return_value = mock_skill

        events, state, llm_mock = await _run_react_case(
            user_message="继续",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["继续"],
                "search_query": "继续",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["继续"],
                "search_negative_terms": [],
                "question_type": None,
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        _tool_call("load_skill", {"skill_name": "theory-qa", "turn": i})
                    ],
                    "finish_reason": "tool_calls",
                }
                for i in range(MAX_REACT_STEPS)
            ],
            stream_chunks=("工具轮次已满，我直接给出最终结论。",),
            tool_patches=[
                patch(
                    "app.agents.chat.tools._get_skill_registry", return_value=registry
                ),
            ],
        )

        assert llm_mock.call_count == MAX_REACT_STEPS
        assert registry.get.call_count == MAX_REACT_STEPS
        assert state["active_skills"] == ["theory-qa"]

        step_events = [e for e in events if e["type"] == "step"]
        assert [e["step"] for e in step_events[:-1]] == ["load_skill"] * MAX_REACT_STEPS
        assert step_events[-1]["step"] == "generating"

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "conversation"
        assert basis_event["should_show_references"] is False
        assert state["retrieved_questions"] == []
        assert state["metadata"]["basis_type"] == "conversation"
        assert "[BASIS]" not in state["response"]


class TestRealLinkSkillInjection:
    """验证 load_skill → state 更新 → system prompt 注入 的真实链路。"""

    async def test_load_skill_then_system_prompt_contains_instruction(self):
        """真实调用 load_skill → build_react_system_prompt，验证指令注入。"""
        from app.agents.chat.tools import execute_tool
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "retrieved_questions": [],
        }

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_skill = MagicMock()
        mock_skill.name = "theory-qa"
        mock_skill.description = "理论问答策略"
        mock_skill.get_instruction.return_value = (
            "## Theory QA\nAsk deep theory questions about CS fundamentals."
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        with (
            patch(
                "app.agents.chat.tools._get_skill_registry",
                return_value=mock_registry,
            ),
            patch(
                "app.agents.chat.nodes.get_default_registry",
                return_value=mock_registry,
            ),
        ):
            result = await execute_tool(tool_call, state)

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["metadata"]["status"] == "loaded"

        assert "theory-qa" in state["active_skills"]
        assert len(state["active_skill_instructions"]) == 1

        prompt = build_react_system_prompt(state)
        assert "Theory QA" in prompt
        assert "Ask deep theory questions" in prompt

    async def test_full_react_loop_with_real_tools(self):
        """完整 ReAct loop：LLM 调 load_skill → 真实 execute_tool → 真实 build_react_system_prompt → LLM 回答。"""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "介绍一下你自己",
            "model": None,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "retrieved_questions": [],
            "intent": "interview_question",
            "answer_complete": True,
        }

        step1 = {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "load_skill",
                        "arguments": json.dumps({"skill_name": "theory-qa"}),
                    },
                }
            ],
            "finish_reason": "tool_calls",
        }
        step2 = {
            "content": "请解释一下 JVM 内存模型。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        call_count = 0
        captured_system_prompts: list[str] = []

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                messages = args[0] if args else kwargs.get("messages", [])
                if messages and messages[0].get("role") == "system":
                    captured_system_prompts.append(messages[0]["content"])
            return step1 if call_count == 1 else step2

        mock_skill = MagicMock()
        mock_skill.name = "theory-qa"
        mock_skill.description = "理论问答策略"
        mock_skill.get_instruction.return_value = (
            "## Theory QA\nAsk deep theory questions."
        )

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.services.llm.llm_with_tools",
                    side_effect=mock_llm,
                ),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream(
                        "请解释一下 JVM 内存模型。"
                    ),
                ),
                patch(
                    "app.agents.chat.tools._get_skill_registry",
                    return_value=mock_registry,
                ),
                patch(
                    "app.agents.chat.nodes.get_default_registry",
                    return_value=mock_registry,
                ),
            ):
                collected: list[dict] = []
                async for event in _react_loop(state):
                    collected.append(event)
        finally:
            _event_queue_var.reset(token)

        assert len(captured_system_prompts) == 1
        assert "Theory QA" in captured_system_prompts[0]
        assert "Ask deep theory questions" in captured_system_prompts[0]

        all_events = emitted + collected
        assert any(e.get("type") == "done" for e in all_events)

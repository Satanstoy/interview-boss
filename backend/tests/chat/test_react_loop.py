"""TDD tests for _react_loop — ReAct agent core loop in pipeline.py."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.chat.pipeline import MAX_REACT_STEPS
from app.agents.shared.events import _event_queue_var


# ── Helpers ───────────────────────────────────────────────


def _tc(name: str, args: dict, tc_id: str = "call_1") -> dict:
    """Create a tool_call dict in OpenAI format."""
    return {
        "id": tc_id,
        "function": {
            "name": name,
            "arguments": json.dumps(args),
        },
    }


async def _mock_stream_strings(*chunks: str):
    """Async generator that yields plain strings (like stream_llm_messages)."""
    for c in chunks:
        yield c


# ── TestReactLoop ─────────────────────────────────────────


class TestReactLoop:
    """Tests for the _react_loop async generator."""

    async def test_direct_answer_no_tools(self):
        """LLM returns no tool_calls -> should stream final answer directly."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "Hello",
            "model": None,
        }

        with (
            patch(
                "app.agents.chat.pipeline.build_react_system_prompt",
                return_value="You are an interviewer.",
            ),
            patch(
                "app.agents.chat.pipeline.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": None,
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ),
            patch(
                "app.agents.chat.pipeline.stream_llm_messages",
                side_effect=lambda *a, **kw: _mock_stream_strings(
                    "Hello", " World"
                ),
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert len(chunk_events) == 2
        assert chunk_events[0]["content"] == "Hello"
        assert chunk_events[1]["content"] == " World"
        # Last event should be "done"
        assert events[-1]["type"] == "done"

    async def test_tool_call_then_answer(self):
        """LLM calls search_questions then answers in second turn.

        Step/retrieved events go via _emit (queue), chunks via yield.
        """
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "Give me a JVM question",
            "model": "gpt-4",
        }

        tc_search = _tc("search_questions", {"keywords": ["JVM"]})

        mock_llm_with_tools = AsyncMock(
            side_effect=[
                {
                    "content": None,
                    "tool_calls": [tc_search],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "Here is your question",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ]
        )

        tool_result = json.dumps(
            [{"id": 10, "question": "Explain JVM memory model", "sources": []}]
        )

        async def _mock_execute(tc, st):
            st["retrieved_questions"] = [
                {"id": 10, "question": "Explain JVM memory model", "sources": []}
            ]
            return tool_result

        # Set up mock event queue to capture _emit side-effect events
        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.pipeline.build_react_system_prompt",
                    return_value="Interviewer prompt.",
                ),
                patch(
                    "app.agents.chat.pipeline.llm_with_tools",
                    mock_llm_with_tools,
                ),
                patch(
                    "app.agents.chat.pipeline.execute_tool",
                    side_effect=_mock_execute,
                ),
                patch(
                    "app.agents.chat.pipeline.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "Here is your question"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        # All events in order: emitted (step, retrieved) + yielded (chunk, done)
        events = emitted + yielded

        # Event sequence: step(search_questions) + retrieved + chunk + done
        assert events[0]["type"] == "step"
        assert events[0]["step"] == "search_questions"
        assert events[1]["type"] == "retrieved"
        assert events[1]["questions"][0]["id"] == 10
        assert events[-2]["type"] == "chunk"
        assert events[-2]["content"] == "Here is your question"
        assert events[-1]["type"] == "done"

        # LLM called twice (once for tool, once for answer)
        assert mock_llm_with_tools.call_count == 2

    async def test_max_steps_limit(self):
        """LLM always returns tool_calls (infinite loop scenario) -> capped at MAX_REACT_STEPS."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "test",
            "model": None,
        }

        # Always return a tool call
        tc = _tc("load_skill", {"skill_name": "theory-qa"})

        tool_responses = [
            {
                "content": None,
                "tool_calls": [tc],
                "finish_reason": "tool_calls",
            }
            for _ in range(MAX_REACT_STEPS)
        ]

        mock_llm = AsyncMock(side_effect=tool_responses)

        async def _mock_execute_tool(tc, st):
            return json.dumps({"instruction": "Ask theory questions."})

        with (
            patch(
                "app.agents.chat.pipeline.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch("app.agents.chat.pipeline.llm_with_tools", mock_llm),
            patch(
                "app.agents.chat.pipeline.execute_tool",
                side_effect=_mock_execute_tool,
            ),
            patch(
                "app.agents.chat.pipeline.stream_llm_messages",
                side_effect=lambda *a, **kw: _mock_stream_strings(
                    "Final answer after max steps"
                ),
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        # LLM called exactly MAX_REACT_STEPS times (loop capped)
        assert mock_llm.call_count == MAX_REACT_STEPS

        # stream_llm_messages was still called (generates answer after loop)
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert len(chunk_events) > 0
        assert chunk_events[0]["content"] == "Final answer after max steps"


# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def base_state():
    return {
        "conversation_id": "test-conv-1",
        "user_id": 1,
        "user_message": "你好",
        "mode": "free_practice",
        "jd_id": None,
        "jd_text": None,
        "resume_text": None,
        "model": None,
        "bank_mode": "public",
        "memories": [],
        "memory_summaries": [],
        "resume_summary": None,
        "session_notes": "",
        "interview_context": "目标岗位：后端开发",
        "job_position": "后端开发",
        "message_history": [],
        "compressed_context": None,
        "recent_messages": [],
        "budget_snapshot": None,
        "intent": "chat",
        "answer_complete": False,
        "keywords": [],
        "search_query": "",
        "retrieval_intent": None,
        "search_positive_terms": [],
        "search_negative_terms": [],
        "question_type": None,
        "retrieved_questions": [],
        "selected_basis_questions": [],
        "rerank_metadata": {},
        "response": "",
        "metadata": {},
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "active_skills": [],
    }


# ── TestReactLoopIntegration ───────────────────────────────


class TestReactLoopIntegration:
    """Integration tests for the full ReAct loop tool chain."""

    async def test_load_skill_then_search_then_answer(self, base_state):
        """LLM loads skill, searches questions, then answers."""
        from app.agents.chat.pipeline import _react_loop

        # Step 1: load_skill
        step1 = {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": "load_skill",
                    "arguments": json.dumps({"skill_name": "algorithm-coding"}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        # Step 2: search_questions
        step2 = {
            "content": None,
            "tool_calls": [{
                "id": "call_2",
                "function": {
                    "name": "search_questions",
                    "arguments": json.dumps({"keywords": ["排序算法"]}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        # Step 3: answer
        step3 = {
            "content": "好的，请实现一个快速排序。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        call_count = 0

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return [step1, step2, step3][call_count - 1]

        async def mock_stream(*args, **kwargs):
            yield "好的，"
            yield "请实现一个快速排序。"

        collected = []
        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with patch("app.agents.chat.pipeline.build_react_system_prompt", return_value="Test prompt."):
                with patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm):
                    with patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=mock_stream):
                        with patch("app.agents.chat.pipeline.execute_tool", new_callable=AsyncMock, return_value="mock result"):
                            async for event in _react_loop(base_state):
                                collected.append(event)
        finally:
            _event_queue_var.reset(token)

        # Combine emitted (step) and yielded (chunk, done) events
        all_events = emitted + collected
        types = [e.get("type") for e in all_events]
        assert "step" in types
        assert "chunk" in types
        assert "done" in types

        # llm_with_tools called 3 times
        assert call_count == 3

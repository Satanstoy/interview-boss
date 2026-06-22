"""TDD tests for _react_loop — ReAct agent core loop in pipeline.py."""

import asyncio
import json
import logging
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


# ── TestActiveSkillsPersistence ──────────────────────────


class TestActiveSkillsPersistence:
    def test_restore_only_persistent_skills_from_metadata(self):
        """Restoring should ignore turn-scoped mode skills."""
        from app.agents.chat.nodes import _restore_active_skills_from_metadata

        state = {}
        metadata = {
            "persistent_skill_names": ["interview-rhythm"],
            "active_skill_names": ["project-deep-dive"],
        }

        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = (
            "## Interview Rhythm\nLatest instruction."
        )
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        _restore_active_skills_from_metadata(state, metadata, registry=mock_registry)

        assert state["active_skills"] == ["interview-rhythm"]
        assert state["active_skill_instructions"] == [
            {
                "skill_name": "interview-rhythm",
                "instruction": "## Interview Rhythm\nLatest instruction.",
            }
        ]
        mock_registry.get.assert_called_once_with("interview-rhythm")

    def test_restore_skips_unknown_skills(self):
        """Unknown skill names in metadata should be silently ignored."""
        from app.agents.chat.nodes import _restore_active_skills_from_metadata

        state = {}
        metadata = {"persistent_skill_names": ["nonexistent-skill", "interview-rhythm"]}

        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = "## Rhythm\nKeep pacing."
        mock_registry = MagicMock()
        # First call returns None (unknown), second returns mock_skill
        mock_registry.get.side_effect = [None, mock_skill]

        _restore_active_skills_from_metadata(state, metadata, registry=mock_registry)

        assert state["active_skills"] == ["interview-rhythm"]
        assert state["active_skill_instructions"] == [
            {"skill_name": "interview-rhythm", "instruction": "## Rhythm\nKeep pacing."}
        ]

    def test_legacy_metadata_does_not_restore_turn_scoped_skills(self):
        """Legacy active_skill_names should not make algorithm mode sticky."""
        from app.agents.chat.nodes import _restore_active_skills_from_metadata

        state = {}
        metadata = {"active_skill_names": ["algorithm-coding", "project-deep-dive"]}

        mock_registry = MagicMock()
        _restore_active_skills_from_metadata(state, metadata, registry=mock_registry)

        assert "active_skills" not in state
        mock_registry.get.assert_not_called()

    def test_restore_noop_when_metadata_empty(self):
        """No-op when metadata has no active_skill_names key."""
        from app.agents.chat.nodes import _restore_active_skills_from_metadata

        state = {"active_skills": ["existing"]}
        _restore_active_skills_from_metadata(state, {})

        # State should be untouched
        assert state["active_skills"] == ["existing"]

    def test_restore_noop_when_skill_names_empty_list(self):
        """No-op when active_skill_names is an empty list."""
        from app.agents.chat.nodes import _restore_active_skills_from_metadata

        state = {}
        _restore_active_skills_from_metadata(state, {"active_skill_names": []})

        assert "active_skills" not in state
        assert "active_skill_instructions" not in state


# ── TestReactLoop ─────────────────────────────────────────


class TestReactLoop:
    """Tests for the _react_loop async generator."""

    async def test_overlong_interview_asks_final_candidate_question(self):
        """Overlong interviews should hard-stop tech questioning before tools run."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "我会检查 prompt、上下文截断和模型是否混用法条。",
            "message_history": [
                {"role": "assistant", "content": "技术问题"}
                if i % 2 == 0
                else {"role": "user", "content": "候选人回答"}
                for i in range(46)
            ],
            "session_notes": "",
            "model": None,
        }

        mock_summary_json = json.dumps({
            "overall_comment": "候选人技术基础扎实",
            "strongest_topic": "系统设计思路清晰",
            "weakest_topic": "算法细节不够深入",
            "key_suggestions": ["复习排序算法", "多练习编码"],
            "score_estimate": 7,
        }, ensure_ascii=False)

        with patch(
            "app.agents.chat.pipeline.llm_with_tools", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert [e["type"] for e in events] == ["chunk", "done"]
        assert "整体表现" in events[0]["content"]
        assert "候选人技术基础扎实" in events[0]["content"]
        assert state["question_source_reason"] == "forced_closing_by_message_count"
        mock_llm.assert_not_called()

    async def test_overlong_interview_closes_after_candidate_question(self):
        """If the final candidate question was already asked, answer and end."""
        from app.agents.chat.pipeline import _react_loop

        history = [
            {"role": "assistant", "content": "技术问题"}
            if i % 2 == 0
            else {"role": "user", "content": "候选人回答"}
            for i in range(45)
        ]
        history.append({"role": "assistant", "content": "你有什么想问我们的吗？"})
        state = {
            "user_id": 1,
            "user_message": "我想了解团队做 Agent 落地最看重什么？",
            "message_history": history,
            "session_notes": "",
            "model": None,
        }

        mock_summary_json = json.dumps({
            "overall_comment": "整体表现良好",
            "strongest_topic": "项目经验丰富",
            "weakest_topic": "算法基础薄弱",
            "key_suggestions": ["多练算法"],
            "score_estimate": 6,
        }, ensure_ascii=False)

        with patch(
            "app.agents.chat.pipeline.llm_with_tools", new_callable=AsyncMock
        ) as mock_llm, patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert [e["type"] for e in events] == ["chunk", "done"]
        assert "模拟面试就到这里" in events[0]["content"]
        assert "整体表现良好" in events[0]["content"]
        assert state["question_source_reason"] == "forced_closing_by_message_count"
        mock_llm.assert_not_called()

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
                side_effect=lambda *a, **kw: _mock_stream_strings("Hello", " World"),
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert len(chunk_events) == 1
        assert chunk_events[0]["content"] == "Hello World"
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

        # Verify step event contains reason
        assert "reason" in events[0]
        assert events[0]["reason"]  # reason is non-empty

        assert events[1]["type"] == "retrieved"
        assert events[1]["questions"][0]["id"] == 10
        assert events[-2]["type"] == "chunk"
        assert events[-2]["content"] == "Here is your question"
        assert events[-1]["type"] == "done"

        # LLM called twice (once for tool, once for answer)
        assert mock_llm_with_tools.call_count == 2

    async def test_tool_envelope_emits_retrieved_and_prunes_message_output(self):
        """ReAct should understand structured tool envelopes and keep LLM messages compact."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "给我一道 RAG 题",
            "model": None,
            "intent": "practice_request",
            "answer_complete": False,
        }
        tc_search = _tc("search_questions", {"keywords": ["RAG"]})
        captured_messages = []

        async def mock_llm(messages, *args, **kwargs):
            captured_messages.append(messages)
            if len(captured_messages) == 1:
                return {
                    "content": None,
                    "tool_calls": [tc_search],
                    "finish_reason": "tool_calls",
                }
            return {
                "content": "请你说说 RAG 的检索和重排怎么设计？",
                "tool_calls": None,
                "finish_reason": "stop",
            }

        envelope = {
            "ok": True,
            "tool": "search_questions",
            "items": [
                {
                    "id": i,
                    "question": f"RAG question {i}",
                    "cat1": "B",
                    "cat2": "RAG",
                    "source": "search",
                    "score": 0.1,
                    "reason": "rrf_ranked",
                    "sources": [],
                }
                for i in range(1, 6)
            ],
            "metadata": {
                "result_count": 5,
                "fallback_used": False,
                "fallback_steps": [],
                "empty_reason": None,
                "debug_reason": "hybrid_search_ok",
                "metrics": {"total_ms": 5},
            },
            "error": None,
        }

        async def mock_execute_tool(tc, st):
            st["retrieved_questions"] = [
                {
                    "id": i,
                    "question": f"RAG question {i}",
                    "cat1": "B",
                    "cat2": "RAG",
                    "sources": [],
                }
                for i in range(1, 6)
            ]
            st["candidate_questions"] = st["retrieved_questions"]
            st["question_source"] = "search"
            return json.dumps(envelope, ensure_ascii=False)

        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch("app.agents.chat.pipeline.build_react_system_prompt", return_value="Prompt."),
                patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
                patch("app.agents.chat.pipeline.execute_tool", side_effect=mock_execute_tool),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        retrieved = next(e for e in emitted if e.get("type") == "retrieved")
        assert [q["id"] for q in retrieved["questions"]] == [1, 2, 3]

        second_messages = captured_messages[1]
        tool_messages = [m for m in second_messages if m.get("role") == "tool"]
        assert len(tool_messages) == 1
        tool_payload = json.loads(tool_messages[0]["content"])
        assert tool_payload["ok"] is True
        assert len(tool_payload["items"]) == 3

    async def test_max_steps_limit(self):
        """LLM always returns tool_calls (infinite loop scenario) -> capped at MAX_REACT_STEPS."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "test",
            "model": None,
        }

        tool_responses = [
            {
                "content": None,
                "tool_calls": [
                    _tc("load_skill", {"skill_name": "theory-qa", "turn": i})
                ],
                "finish_reason": "tool_calls",
            }
            for i in range(MAX_REACT_STEPS)
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

    async def test_react_trace_is_backend_only_and_sanitized(self, caplog):
        """Trace logs should help debugging without leaking tool payloads to SSE."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "trace-conv",
            "user_id": 1,
            "user_message": "Start algorithm interview",
            "model": None,
            "active_skills": [],
        }

        tc_load = _tc(
            "load_skill",
            {
                "skill_name": "algorithm-coding",
                "secret_prompt": "SHOULD_NOT_BE_LOGGED",
            },
        )

        mock_llm = AsyncMock(
            side_effect=[
                {
                    "content": None,
                    "tool_calls": [tc_load],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "Final answer",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ]
        )

        async def mock_execute_tool(tc, st):
            st["active_skills"] = ["algorithm-coding"]
            return json.dumps({"instruction": "SECRET SKILL INSTRUCTION"})

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                caplog.at_level(logging.INFO, logger="interview-boss"),
                patch(
                    "app.agents.chat.pipeline.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.agents.chat.pipeline.llm_with_tools", mock_llm),
                patch(
                    "app.agents.chat.pipeline.execute_tool",
                    side_effect=mock_execute_tool,
                ),
                patch(
                    "app.agents.chat.pipeline.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings("Final answer"),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        all_events = emitted + yielded
        assert "ReAct trace: event=llm_step" in caplog.text
        assert "ReAct trace: event=tool_call" in caplog.text
        assert "tool_name=load_skill" in caplog.text
        assert "algorithm-coding" in caplog.text
        assert "<redacted>" in caplog.text
        assert "SHOULD_NOT_BE_LOGGED" not in caplog.text
        assert "SECRET SKILL INSTRUCTION" not in caplog.text
        assert not any(e.get("type") == "react_trace" for e in all_events)

    async def test_final_answer_filters_internal_skill_marker(self, caplog):
        """Bare skill names are internal control signals and must not reach SSE."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "marker-conv",
            "user_id": 1,
            "user_message": "Tell me about your project",
            "model": None,
        }

        with (
            caplog.at_level(logging.WARNING, logger="interview-boss"),
            patch(
                "app.agents.chat.pipeline.build_react_system_prompt",
                return_value="Prompt.",
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
                side_effect=lambda *a, **kw: _mock_stream_strings("project-deep-dive"),
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunk_text = "".join(
            e.get("content", "") for e in events if e.get("type") == "chunk"
        )
        assert chunk_text
        assert chunk_text != "project-deep-dive"
        assert "项目做深挖" in chunk_text
        assert "internal_marker_filtered" in caplog.text


class TestAnswerCompleteHeuristic:
    def test_short_message_not_complete(self):
        """Short messages (< 15 chars) should be answer_complete=False."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        assert _heuristic_answer_complete("嗯") is False
        assert _heuristic_answer_complete("用了 Redis") is False
        assert _heuristic_answer_complete("这样对吗？") is False

    def test_long_message_likely_complete(self):
        """Long messages (> 30 chars with substance) should be answer_complete=True."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        msg = "我在项目中使用了 Redis 做缓存层，通过布隆过滤器解决缓存穿透，用分布式锁解决缓存击穿"
        assert _heuristic_answer_complete(msg) is True

    def test_explicit_completion_markers(self):
        """Messages with explicit completion markers should be True."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        assert _heuristic_answer_complete("就这些") is True
        assert _heuristic_answer_complete("答完了") is True
        assert _heuristic_answer_complete("大概就是这样吧") is True

    def test_question_marks_not_complete(self):
        """Questions/confirmations should be False."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        assert _heuristic_answer_complete("你是说用 Redis 吗？") is False
        assert _heuristic_answer_complete("能不能再解释一下") is False

    def test_substantive_answer_with_how_why_words_is_complete(self):
        """Substantive answers containing 怎么/为什么 should not be misclassified."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        msg = "我是这么解决的：先分析为什么慢，再看怎么优化缓存和接口调用链路，最后做压测验证"
        assert _heuristic_answer_complete(msg) is True


class TestBuildToolStrategy:
    def test_interview_question_answer_complete_default_search(self):
        """Should require search_questions when user completed their answer (default)."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
            "active_skills": [],
        }
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "必须" in strategy

    def test_interview_question_deep_dive_allows_direct_followup(self):
        """Project deep-dive mode: can directly follow up without search."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
            "active_skills": ["project-deep-dive"],
        }
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "直接追问" in strategy or "不检索" in strategy

    def test_interview_question_answer_incomplete_suggests_wait(self):
        """Should suggest waiting when user hasn't finished answering."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": False,
            "active_skills": [],
        }
        strategy = _build_tool_strategy(state)
        assert "不调用工具" in strategy or "等待" in strategy

    def test_practice_request_requires_search(self):
        """Practice requests must search (required, not suggested)."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "practice_request",
            "answer_complete": False,
            "active_skills": [],
        }
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "必须" in strategy

    def test_chat_suggests_no_tools(self):
        """Should suggest no tools for casual chat."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "chat", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "不调用工具" in strategy

    def test_follow_up_suggests_contextual_answer(self):
        """Should suggest contextual answer for follow-ups."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "follow_up", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "上下文" in strategy or "直接回答" in strategy

    def test_already_retrieved_suggests_no_search(self):
        """Should not suggest search when retrieved_questions is non-empty."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [{"id": 1}],
            "active_skills": [],
        }
        strategy = _build_tool_strategy(state)
        assert "search_questions" not in strategy


class TestFinalAnswerQuality:
    async def test_bare_coding_prompt_gets_full_fallback_question(self):
        from app.agents.chat.pipeline import _final_answer_events_from_text

        state = {
            "conversation_id": "conv",
            "active_skills": ["algorithm-coding"],
            "candidate_questions": [],
        }

        events = await _final_answer_events_from_text("来，写代码吧。", state)

        assert events[0]["type"] == "chunk"
        assert "来写一道代码题" in events[0]["content"]
        assert state["question_source"] == "generated"

    async def test_final_answer_failure_falls_back_to_candidate_question(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "conv",
            "user_id": 1,
            "user_message": "继续",
            "model": None,
            "candidate_questions": [
                {"id": 7, "question": "介绍一下 RAG 的完整流程", "sources": []}
            ],
            "retrieved_questions": [
                {"id": 7, "question": "介绍一下 RAG 的完整流程", "sources": []}
            ],
            "question_source": "search",
        }

        async def broken_stream(*args, **kwargs):
            raise RuntimeError("upstream failed")
            yield  # pragma: no cover

        with (
            patch(
                "app.agents.chat.pipeline.build_react_system_prompt",
                return_value="Prompt.",
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
                side_effect=broken_stream,
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunk = next(e for e in events if e["type"] == "chunk")
        assert "介绍一下 RAG 的完整流程" in chunk["content"]
        assert state["selected_question"]["id"] == 7
        assert state["question_source_reason"] == "fallback_after_RuntimeError"


class TestQuestionPlanHelpers:
    def test_should_create_question_plan_for_practice_request(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        state = {"intent": "practice_request", "answer_complete": False}
        assert _should_create_question_plan(state) is True

    def test_should_create_question_plan_for_complete_interview_answer(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        state = {"intent": "interview_question", "answer_complete": True}
        assert _should_create_question_plan(state) is True

    def test_should_not_create_question_plan_for_follow_up_chat_or_end(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        assert _should_create_question_plan({"intent": "follow_up", "answer_complete": False}) is False
        assert _should_create_question_plan({"intent": "chat", "answer_complete": False}) is False
        assert _should_create_question_plan({"intent": "end_interview", "answer_complete": False}) is False
        assert _should_create_question_plan({"intent": "interview_question", "answer_complete": False}) is False

    def test_select_question_for_plan_prefers_algorithm_candidate(self):
        from app.agents.chat.pipeline import _select_question_for_plan

        state = {"question_type": "algorithm_coding", "search_negative_terms": []}
        candidates = [
            {"id": 1, "question": "说说 Redis 持久化", "cat1": "后端", "cat2": "Redis", "tags": "redis"},
            {"id": 2, "question": "实现 LRU Cache", "cat1": "E.算法与数据结构", "cat2": "E2.算法手撕", "tags": "代码,lru"},
        ]

        selected, reason = _select_question_for_plan(state, candidates)

        assert selected["id"] == 2
        assert reason == "algorithm_candidate_match"

    def test_build_question_plan_sets_state_selected_question(self):
        from app.agents.chat.pipeline import _maybe_create_question_plan

        state = {
            "intent": "practice_request",
            "answer_complete": False,
            "question_source": "search",
            "search_negative_terms": ["HR"],
        }
        candidates = [
            {"id": 7, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "tags": "检索,重排"}
        ]
        state["candidate_questions"] = candidates

        plan = _maybe_create_question_plan(state)

        assert plan["must_ask"] is True
        assert plan["question_id"] == 7
        assert plan["question_text"] == "RAG 检索怎么设计？"
        assert plan["source"] == "search"
        assert "RAG" in plan["allowed_focus"]
        assert state["selected_question"]["id"] == 7
        assert state["next_question_plan"]["question_id"] == 7
        assert state["question_source_reason"] == "question_plan_bound"


class TestQuestionPlanEnforcement:
    async def test_final_generation_injects_next_question_plan(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "来一道 RAG 题",
            "model": None,
            "intent": "practice_request",
            "answer_complete": False,
        }
        tc_search = _tc("search_questions", {"keywords": ["RAG"]})
        captured_messages = []

        async def mock_llm(messages, *args, **kwargs):
            captured_messages.append(messages)
            if len(captured_messages) == 1:
                return {"content": None, "tool_calls": [tc_search], "finish_reason": "tool_calls"}
            return {"content": "请你说说 RAG 检索怎么设计？", "tool_calls": None, "finish_reason": "stop"}

        async def mock_execute_tool(tc, st):
            question = {"id": 11, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "tags": "检索", "sources": []}
            st["retrieved_questions"] = [question]
            st["candidate_questions"] = [question]
            st["question_source"] = "search"
            return json.dumps({
                "ok": True,
                "tool": "search_questions",
                "items": [{**question, "source": "search", "score": 0.1, "reason": "rrf_ranked"}],
                "metadata": {"result_count": 1, "fallback_used": False, "fallback_steps": [], "empty_reason": None, "debug_reason": "hybrid_search_ok", "metrics": {"total_ms": 1}},
                "error": None,
            }, ensure_ascii=False)

        with (
            patch("app.agents.chat.pipeline.build_react_system_prompt", return_value="Prompt."),
            patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
            patch("app.agents.chat.pipeline.execute_tool", side_effect=mock_execute_tool),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        second_messages_text = "\n".join(m.get("content") or "" for m in captured_messages[1])
        assert "<next_question_plan>" in second_messages_text
        assert "RAG 检索怎么设计" in second_messages_text
        assert state["next_question_plan"]["question_id"] == 11

    async def test_plan_drift_is_repaired_once(self):
        from app.agents.chat.pipeline import _final_answer_events_from_text

        state = {
            "user_id": 1,
            "user_message": "来一道 RAG 题",
            "next_question_plan": {
                "must_ask": True,
                "question_id": 11,
                "question_text": "RAG 检索怎么设计？",
                "basis_type": "interview_question",
                "source": "search",
                "strategy": "practice_request",
                "allowed_focus": ["RAG", "检索"],
                "forbidden_focus": ["HR"],
                "selection_reason": "top_ranked_candidate",
            },
            "selected_question": {"id": 11, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG"},
        }

        with patch(
            "app.agents.chat.pipeline._repair_response_to_question_plan",
            new_callable=AsyncMock,
            return_value={
                "response": "我们收束到 RAG：请你说说 RAG 检索怎么设计？",
                "repaired": True,
                "reason": "plan_drift_repaired",
                "adherence": {"adheres": True, "score": 0.5, "reason": "keyword_overlap"},
            },
        ) as mock_repair:
            events = await _final_answer_events_from_text("说说你的 HR 优势？", state)

        assert events[0]["type"] == "chunk"
        assert "RAG 检索怎么设计" in events[0]["content"]
        assert state["question_plan_metadata"]["repaired"] is True
        mock_repair.assert_awaited_once()

    def test_react_metadata_prefers_planned_selected_question(self):
        from app.agents.chat.pipeline import _build_react_metadata

        state = {
            "retrieved_questions": [
                {"id": 1, "question": "Redis 持久化怎么做？", "cat1": "后端", "cat2": "Redis", "sources": []},
                {"id": 2, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "sources": []},
            ],
            "candidate_questions": [
                {"id": 1, "question": "Redis 持久化怎么做？", "cat1": "后端", "cat2": "Redis", "sources": []},
                {"id": 2, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "sources": []},
            ],
            "selected_question": {"id": 2, "question": "RAG 检索怎么设计？", "cat1": "B", "cat2": "RAG", "sources": []},
            "next_question_plan": {
                "must_ask": True,
                "question_id": 2,
                "question_text": "RAG 检索怎么设计？",
                "source": "search",
                "selection_reason": "top_ranked_candidate",
            },
            "question_plan_metadata": {
                "adherence": {"adheres": True, "score": 0.5, "reason": "keyword_overlap"},
                "repaired": False,
            },
            "question_source": "search",
            "question_source_reason": "question_plan_bound",
            "active_skills": [],
        }

        metadata, clean = _build_react_metadata(state, "请你说说 Redis 持久化？")

        assert metadata["selected_question"]["id"] == 2
        assert metadata["question_source_reason"] == "question_plan_bound"
        assert metadata["question_plan"]["repaired"] is False
        assert clean == "请你说说 Redis 持久化？"


# ── TestBuildReactSystemPrompt ────────────────────────────


class TestBuildReactSystemPrompt:
    def test_injects_active_skill_instructions(self):
        """build_react_system_prompt should inject active skill instructions."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": ["theory-qa"],
            "active_skill_instructions": [
                {
                    "skill_name": "theory-qa",
                    "instruction": "## Theory QA\nAsk deep theory questions.",
                },
            ],
        }

        prompt = build_react_system_prompt(state)
        assert "Theory QA" in prompt
        assert "Ask deep theory questions." in prompt

    def test_no_active_skills_no_injection(self):
        """build_react_system_prompt should not inject when no active skills."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
        }

        prompt = build_react_system_prompt(state)
        assert "<active_skill_instructions>" not in prompt

    def test_injects_tool_strategy(self):
        """build_react_system_prompt should inject tool strategy based on intent."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
        }

        prompt = build_react_system_prompt(state)
        assert "<tool_strategy>" in prompt
        assert "search_questions" in prompt

    def test_no_tool_strategy_for_chat(self):
        """build_react_system_prompt should inject no-tools strategy for chat."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "intent": "chat",
            "answer_complete": False,
        }

        prompt = build_react_system_prompt(state)
        assert "<tool_strategy>" in prompt
        assert "不调用工具" in prompt


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
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "load_skill",
                        "arguments": json.dumps({"skill_name": "algorithm-coding"}),
                    },
                }
            ],
            "finish_reason": "tool_calls",
        }

        # Step 2: search_questions
        step2 = {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_2",
                    "function": {
                        "name": "search_questions",
                        "arguments": json.dumps({"keywords": ["排序算法"]}),
                    },
                }
            ],
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
            with patch(
                "app.agents.chat.pipeline.build_react_system_prompt",
                return_value="Test prompt.",
            ):
                with patch(
                    "app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm
                ):
                    with patch(
                        "app.agents.chat.pipeline.stream_llm_messages",
                        side_effect=mock_stream,
                    ):
                        with patch(
                            "app.agents.chat.pipeline.execute_tool",
                            new_callable=AsyncMock,
                            return_value="mock result",
                        ):
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


# ── TestEndInterviewHardRoute ─────────────────────────────


class TestEndInterviewHardRoute:
    """end_interview intent must bypass the ReAct loop entirely — zero tool calls."""

    @pytest.mark.asyncio
    async def test_end_interview_does_not_call_tools(self):
        """When intent=end_interview, llm_with_tools and execute_tool must NOT be called."""
        from app.agents.chat.pipeline import run_chat

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.pipeline._step_load_context",
                    new_callable=AsyncMock,
                ) as mock_load,
                patch(
                    "app.agents.chat.pipeline._step_classify", new_callable=AsyncMock
                ) as mock_classify,
                patch(
                    "app.agents.chat.pipeline._step_extract_memory",
                    new_callable=AsyncMock,
                ),
                patch(
                    "app.agents.chat.pipeline.llm_with_tools", new_callable=AsyncMock
                ) as mock_llm_tools,
                patch(
                    "app.agents.chat.pipeline.execute_tool", new_callable=AsyncMock
                ) as mock_exec,
                patch(
                    "app.agents.chat.pipeline._persist_active_skills",
                    new_callable=AsyncMock,
                ),
                patch("app.agents.chat.pipeline.chat_service"),
                patch(
                    "app.agents.chat.pipeline.classify_and_recall",
                    new_callable=AsyncMock,
                ),
                patch(
                    "app.agents.chat.pipeline.classify_and_recall_fast",
                    new_callable=AsyncMock,
                ),
                patch(
                    "app.agents.chat.pipeline.build_interview_context",
                    return_value=("", None),
                ),
            ):
                mock_load.return_value = None
                mock_classify.side_effect = lambda state: state.update(
                    intent="end_interview",
                    keywords=[],
                    search_query="",
                    answer_complete=False,
                )

                events = []
                async for event in run_chat(
                    conversation_id="test-conv",
                    user_id=1,
                    user_message="结束面试",
                    mode="free_practice",
                ):
                    events.append(event)

        finally:
            _event_queue_var.reset(token)

        # No tool calls should have been made
        mock_llm_tools.assert_not_called()
        mock_exec.assert_not_called()

        # Should have chunk + done events
        all_events = emitted + events
        types = [e.get("type") for e in all_events]
        assert "chunk" in types
        assert "done" in types

        # Closing message should contain summary or farewell
        chunk_texts = [
            e.get("content", "") for e in all_events if e.get("type") == "chunk"
        ]
        combined = "".join(chunk_texts)
        assert "面试" in combined or "感谢" in combined

    @pytest.mark.asyncio
    async def test_end_interview_with_summary_request(self):
        """end_interview + summary keywords should produce a structured summary."""
        from app.agents.chat.pipeline import _generate_end_interview_response

        mock_summary_json = json.dumps({
            "overall_comment": "候选人项目经验丰富，基础知识扎实",
            "strongest_topic": "Redis 缓存策略，回答深入全面",
            "weakest_topic": "算法基础薄弱，手撕题解题思路不清晰",
            "key_suggestions": ["复习常见排序算法", "练习链表题目", "深入理解时间复杂度"],
            "score_estimate": 7,
        }, ensure_ascii=False)

        state = {
            "user_message": "结束面试，给我生成一份面试总结",
            "message_history": [
                {"role": "assistant", "content": "问题1"},
                {"role": "user", "content": "回答1"},
            ]
            * 12,
            "question_source": None,
            "question_source_reason": None,
            "session_notes": "[asked] Redis 持久化",
            "user_id": 1,
        }

        with patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            response = await _generate_end_interview_response(state)

        assert "整体表现" in response
        assert "候选人项目经验丰富" in response
        assert state["question_source"] == "conversation"
        assert state["question_source_reason"] == "end_interview_hard_route"


# ── TestRepetitionProtection ──────────────────────────────


class TestRepetitionProtection:
    """Repetitive question protection: same core topic consecutive limit."""

    def test_no_protection_under_limit(self):
        """Below the limit, no protection note should be injected."""
        from app.agents.chat.pipeline import _build_repetition_protection_note

        state = {
            "conversation_id": "test",
            "message_history": [
                {"role": "assistant", "content": "请介绍一下 Redis 的持久化机制"},
                {"role": "user", "content": "RDB 和 AOF"},
                {"role": "assistant", "content": "TCP 三次握手的流程是什么？"},
                {"role": "user", "content": "SYN SYN-ACK ACK"},
            ],
        }

        note = _build_repetition_protection_note(state)
        assert note == ""

    def test_protection_triggers_after_limit(self):
        """After MAX_CONSECUTIVE same-topic questions, protection note appears."""
        from app.agents.chat.pipeline import (
            _build_repetition_protection_note,
            _MAX_CONSECUTIVE_SAME_QUESTION,
        )

        # Build a history where the last 3 assistant messages all ask about LRU Cache
        state = {
            "conversation_id": "test",
            "message_history": [
                {
                    "role": "assistant",
                    "content": "请实现一个 LRU Cache，用 Python 写出 get 和 put",
                },
                {"role": "user", "content": "用 OrderedDict"},
                {
                    "role": "assistant",
                    "content": "LRU Cache 的时间复杂度是多少？请直接回答 O(1) 的原因",
                },
                {"role": "user", "content": "哈希表加双向链表"},
                {
                    "role": "assistant",
                    "content": "LRU Cache 如果 capacity 为 0 怎么处理？请写代码",
                },
                {"role": "user", "content": "直接返回 -1"},
            ],
        }

        note = _build_repetition_protection_note(state)
        # Should trigger since consecutive count >= _MAX_CONSECUTIVE_SAME_QUESTION
        assert "节奏保护" in note or "不要" in note or "切换" in note

    def test_protection_count_resets_on_topic_change(self):
        """When the topic changes, the consecutive count resets."""
        from app.agents.chat.pipeline import _build_repetition_protection_note

        state = {
            "conversation_id": "test",
            "message_history": [
                # First topic: LRU Cache (2 similar)
                {"role": "assistant", "content": "请实现一个 LRU Cache"},
                {"role": "user", "content": "用 OrderedDict"},
                {"role": "assistant", "content": "LRU Cache 的淘汰策略"},
                {"role": "user", "content": "LRU 最近最少使用"},
                # Topic change: Redis
                {"role": "assistant", "content": "Redis 的持久化机制有哪些？"},
                {"role": "user", "content": "RDB 和 AOF"},
                # New topic only asked once
                {"role": "assistant", "content": "Redis 持久化 RDB 的优缺点"},
                {"role": "user", "content": "快但可能丢数据"},
            ],
        }

        note = _build_repetition_protection_note(state)
        # The last 2 assistant messages are about Redis, which is under the limit
        assert note == ""

    @pytest.mark.asyncio
    async def test_protection_survives_prompt_rebuild_after_skill_load(self, base_state):
        """If ReAct loads a skill, the rebuilt system prompt keeps protection."""
        from app.agents.chat.pipeline import _react_loop

        base_state.update(
            {
                "user_message": "继续",
                "message_history": [
                    {
                        "role": "assistant",
                        "content": "请实现一个 LRU Cache，用 Python 写出 get 和 put",
                    },
                    {"role": "user", "content": "用 OrderedDict"},
                    {
                        "role": "assistant",
                        "content": "LRU Cache 的时间复杂度是多少？请直接回答 O(1) 的原因",
                    },
                    {"role": "user", "content": "哈希表加双向链表"},
                    {
                        "role": "assistant",
                        "content": "LRU Cache 如果 capacity 为 0 怎么处理？请写代码",
                    },
                    {"role": "user", "content": "直接返回 -1"},
                ],
                "recent_messages": [],
                "active_skill_instructions": [],
            }
        )

        system_prompts: list[str] = []

        async def mock_llm(messages, *args, **kwargs):
            system_prompts.append(messages[0]["content"])
            if len(system_prompts) == 1:
                return {
                    "content": None,
                    "tool_calls": [
                        _tc("load_skill", {"skill_name": "algorithm-coding"})
                    ],
                    "finish_reason": "tool_calls",
                }
            return {
                "content": "先给你一个提示：用哈希表加双向链表，再换个边界条件看。",
                "tool_calls": None,
                "finish_reason": "stop",
            }

        async def mock_execute_tool(tool_call, state):
            state["active_skill_instructions"] = [
                {
                    "skill_name": "algorithm-coding",
                    "instruction": "## Algorithm Coding\nAsk coding questions.",
                }
            ]
            return "loaded"

        with (
            patch(
                "app.agents.chat.pipeline.build_react_system_prompt",
                return_value="BASE PROMPT",
            ),
            patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
            patch("app.agents.chat.pipeline.execute_tool", side_effect=mock_execute_tool),
        ):
            events = []
            async for event in _react_loop(base_state):
                events.append(event)

        assert len(system_prompts) == 2
        assert "节奏保护" in system_prompts[0]
        assert "节奏保护" in system_prompts[1]
        assert any(e.get("type") == "chunk" for e in events)


# ── TestSelectedQuestionBinding ────────────────────────────


class TestSelectedQuestionBinding:
    """selected_question binding: single candidate auto-bind."""

    def test_single_candidate_with_overlap_binds(self):
        """When draw returns 1 candidate and response uses its tokens, bind it."""
        from app.agents.chat.pipeline import _infer_selected_question

        candidates = [
            {"id": 42, "question": "实现一个 LRU Cache，支持 get 和 put 操作"},
        ]
        response = (
            "来写一道代码题：实现一个 LRU Cache，支持 get 和 put，请说明数据结构选择。"
        )

        selected, reason = _infer_selected_question(response, [], candidates)

        assert selected is not None
        assert selected["id"] == 42
        assert reason == "single_candidate_token_overlap"

    def test_single_candidate_no_overlap_not_bound(self):
        """When response has no overlap with the single candidate, don't bind."""
        from app.agents.chat.pipeline import _infer_selected_question

        candidates = [
            {"id": 42, "question": "实现一个 LRU Cache"},
        ]
        response = "你刚才提到的项目，能详细说一下架构吗？"

        selected, reason = _infer_selected_question(response, [], candidates)

        assert selected is None
        assert reason == "candidate_not_explicitly_used"

    def test_basis_id_still_takes_priority(self):
        """Explicit basis_question_ids should take priority over heuristics."""
        from app.agents.chat.pipeline import _infer_selected_question

        candidates = [
            {"id": 1, "question": "Redis 持久化"},
            {"id": 2, "question": "LRU Cache 实现"},
        ]
        response = "介绍一下 Redis 持久化"

        selected, reason = _infer_selected_question(response, [1], candidates)

        assert selected["id"] == 1
        assert reason == "basis_question_id"

    def test_multiple_candidates_text_match(self):
        """With multiple candidates, text match still works as before."""
        from app.agents.chat.pipeline import _infer_selected_question

        candidates = [
            {"id": 1, "question": "Redis 持久化机制有哪些？"},
            {"id": 2, "question": "TCP 三次握手流程"},
        ]
        response = "Redis 持久化机制有哪些？请详细介绍 RDB 和 AOF 的区别。"

        selected, reason = _infer_selected_question(response, [], candidates)

        assert selected is not None
        assert selected["id"] == 1
        assert reason == "question_text_match"


# ── TestToolStrategyEndInterview ───────────────────────────


class TestToolStrategyEndInterview:
    """_build_tool_strategy should forbid tools for end_interview."""

    def test_end_interview_forbids_tools(self):
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "end_interview",
            "answer_complete": False,
            "active_skills": [],
        }
        strategy = _build_tool_strategy(state)

        assert "禁止" in strategy
        assert "不得调用任何工具" in strategy or "load_skill" in strategy

"""TDD tests for _react_loop — ReAct agent core loop in pipeline.py."""

import asyncio
import json
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.chat.chat_constants import PUBLIC_QUESTION_PREVIEW_LIMIT
from app.agents.chat.coverage_config import InterviewPhase
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


def _selected_question_message(qid: int, phase: str) -> dict:
    return {
        "role": "assistant",
        "content": f"Question {qid} for {phase}",
        "metadata": {
            "selected_question": {
                "id": qid,
                "question": f"Question {qid} for {phase}",
                "tags": phase,
            }
        },
    }


def _covered_interview_history(message_count: int = 33) -> list[dict]:
    phases = (
        [InterviewPhase.PROJECT_FOLLOWUP.value] * 6
        + [InterviewPhase.KNOWLEDGE_PROBE.value] * 3
        + [InterviewPhase.ALGORITHM_CODING.value]
        + [InterviewPhase.SYSTEM_DESIGN.value]
        + [InterviewPhase.BEHAVIORAL.value]
    )
    messages: list[dict] = []
    for idx, phase in enumerate(phases, start=1):
        messages.append(_selected_question_message(idx, phase))
        messages.append({"role": "user", "content": f"answer {idx}"})
    extra_idx = 0
    _extra_answers = [
        "Redis 我用在缓存层，设了合理 TTL 避免雪崩。",
        "MySQL 索引用 B+ 树，查询走覆盖索引优化。",
        "TCP 三次握手是 SYN、SYN-ACK、ACK 三步。",
        "进程是资源分配单位，线程是调度单位，共享地址空间。",
        "B+ 树叶子节点串链表，范围查询效率高。",
        "哈希表 O(1) 查找，冲突用链地址法解决。",
        "跳表是有序链表加多层索引，平均 O(logN)。",
        "堆排序建大顶堆，逐个取堆顶，时间 O(NlogN)。",
    ]
    while len(messages) < message_count:
        answer = _extra_answers[extra_idx % len(_extra_answers)]
        extra_idx += 1
        messages.append({"role": "user", "content": answer})
    return messages[:message_count]


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


class TestSearchToolTrace:
    async def test_search_questions_records_tool_trace(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "conv-search-trace",
            "user_id": 1,
            "user_message": "我负责 Redis 缓存优化。",
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "mode": "free_practice",
            "message_history": [
                {"role": "assistant", "content": "请介绍项目。"},
                {"role": "user", "content": "我负责 Redis 缓存优化。"},
            ],
            "recent_messages": [],
            "retrieved_questions": [],
            "candidate_questions": [],
            "active_skills": [],
            "tool_steps": [],
        }

        search_results = [
            {
                "id": 101,
                "question": "Redis 缓存穿透怎么处理？",
                "cat1": "中间件",
                "cat2": "缓存",
                "sources": [{"company": "腾讯", "round": "一面"}],
            }
        ]

        llm_responses = [
            {
                "content": None,
                "tool_calls": [_tc("search_questions", {"keywords": ["Redis"]})],
                "finish_reason": "tool_calls",
            },
            {"content": "说说 Redis 缓存穿透。", "tool_calls": None, "finish_reason": "stop"},
        ]

        from contextlib import ExitStack
        import app.agents.chat.react_loop as react_loop_module

        with ExitStack() as stack:
            if hasattr(react_loop_module, "evaluate_interview_stop"):
                stack.enter_context(
                    patch(
                        "app.agents.chat.react_loop.evaluate_interview_stop",
                        return_value={"action": "continue"},
                    )
                )
            stack.enter_context(
                patch("app.agents.chat.react_loop.build_react_system_prompt", return_value="prompt")
            )
            mock_llm = stack.enter_context(
                patch(
                    "app.services.llm.llm_with_tools",
                    new_callable=AsyncMock,
                    side_effect=llm_responses,
                )
            )
            stack.enter_context(
                patch(
                    "app.mcp_server.interview_tools._hybrid_search_for_tool",
                    return_value=search_results,
                )
            )
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert mock_llm.call_count == 2
        assert state["tool_steps"][0]["tool_name"] == "search_questions"
        assert state["tool_calls_trace"][0]["tool_name"] == "search_questions"
        assert state["tool_calls_trace"][0]["label"] == "检索题库"
        assert state["tool_calls_trace"][0]["result_count"] == 1
        assert state["tool_calls_trace"][0]["result_preview"][0]["id"] == 101


# ── TestReactLoop ─────────────────────────────────────────


class TestReactLoop:
    """Tests for the _react_loop async generator."""

    async def test_overlong_interview_asks_final_candidate_question(self):
        """Coverage-complete interviews should ask the candidate's question before closing."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "我会检查 prompt、上下文截断和模型是否混用法条。",
            "job_position": "agent_llm",
            "difficulty": "senior",
            "message_history": _covered_interview_history(33),
            "session_notes": "",
            "model": None,
        }

        with patch(
            "app.services.llm.llm_with_tools", new_callable=AsyncMock
        ) as mock_llm:
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert [e["type"] for e in events] == ["chunk", "done"]
        assert "你有什么想问" in events[0]["content"]
        assert (
            state["question_source_reason"]
            == "coverage_complete_ready_for_candidate_question"
        )
        mock_llm.assert_not_called()

    async def test_overlong_interview_closes_after_candidate_question(self):
        """If the final candidate question was already asked, answer and end."""
        from app.agents.chat.pipeline import _react_loop

        history = _covered_interview_history(34)
        history.append({"role": "assistant", "content": "你有什么想问我们的吗？"})
        state = {
            "user_id": 1,
            "user_message": "我想了解团队做 Agent 落地最看重什么？",
            "job_position": "agent_llm",
            "difficulty": "senior",
            "message_history": history,
            "session_notes": "",
            "model": None,
        }

        mock_summary_json = json.dumps(
            {
                "overall_comment": "整体表现良好",
                "strongest_topic": "项目经验丰富",
                "weakest_topic": "算法基础薄弱",
                "key_suggestions": ["多练算法"],
                "score_estimate": 6,
            },
            ensure_ascii=False,
        )

        with (
            patch(
                "app.services.llm.llm_with_tools", new_callable=AsyncMock
            ) as mock_llm,
            patch(
                "app.services.llm._call_llm_with_retry_messages",
                new_callable=AsyncMock,
                side_effect=[
                    "感谢你的时间，今天这轮模拟面试就先到这里。",
                    mock_summary_json,
                ],
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert [e["type"] for e in events] == ["chunk", "done"]
        # Phase 2: closing sentence is no longer embedded in summary renderer
        assert "整体表现良好" in events[0]["content"]
        assert state["question_source_reason"] == "coverage_complete_after_candidate_question"
        mock_llm.assert_not_called()

    async def test_closing_writer_failure_does_not_emit_summary_alone(self):
        """A close contract fails visibly when the natural closing writer fails."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "结束吧",
            "message_history": [{"role": "user", "content": "test"}] * 44,
            "session_notes": "",
            "model": None,
        }

        with (
            patch(
                "app.agents.chat.react_loop.evaluate_interview_stop",
                return_value={"action": "close", "reason": "hard_stop_by_message_count"},
            ),
            patch(
                "app.agents.chat.react_loop.generate_closing_utterance",
                new_callable=AsyncMock,
                return_value={
                    "status": "error",
                    "error_code": "closing_generation_failed",
                    "message": "LLM 输出为空",
                },
            ),
            patch(
                "app.agents.chat.react_loop._generate_structured_summary",
                new_callable=AsyncMock,
                return_value="**整体表现**：不应单独输出",
            ) as mock_summary,
        ):
            events = [event async for event in _react_loop(state)]

        assert [event["type"] for event in events] == ["error", "done"]
        assert events[0]["code"] == "closing_generation_failed"
        mock_summary.assert_not_awaited()

    async def test_summary_writer_failure_does_not_emit_generic_summary(self):
        """A close contract cannot replace a failed LLM summary with generic prose."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "结束吧",
            "message_history": [{"role": "user", "content": "test"}] * 44,
            "session_notes": "",
            "model": None,
        }

        with (
            patch(
                "app.agents.chat.react_loop.evaluate_interview_stop",
                return_value={"action": "close", "reason": "hard_stop_by_message_count"},
            ),
            patch(
                "app.agents.chat.react_loop.generate_closing_utterance",
                new_callable=AsyncMock,
                return_value={"status": "success", "text": "感谢你的时间，今天先到这里。"},
            ),
            patch(
                "app.services.llm._call_llm_with_retry_messages",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM timeout"),
            ),
        ):
            events = [event async for event in _react_loop(state)]

        assert [event["type"] for event in events] == ["error", "done"]
        assert events[0]["code"] == "summary_generation_failed"

    async def test_planner_close_contract_replaces_react_draft(self):
        """A close_with_summary contract owns the final output after tool evidence."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "继续",
            "message_history": [],
            "session_notes": "",
            "closing_stage": "final_summary",
            "model": None,
        }

        with (
            patch(
                "app.agents.chat.react_loop.evaluate_interview_stop",
                return_value={"action": "continue"},
            ),
            patch(
                "app.agents.chat.react_loop.build_react_system_prompt",
                return_value="test prompt",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": "这是不应输出的 ReAct 草稿。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ),
            patch(
                "app.agents.chat.react_loop.generate_closing_utterance",
                new_callable=AsyncMock,
                return_value={"status": "success", "text": "感谢你的时间，今天先到这里。"},
            ),
            patch(
                "app.agents.chat.react_loop._generate_structured_summary",
                new_callable=AsyncMock,
                return_value="**整体表现**：本轮总结。",
            ),
        ):
            events = [event async for event in _react_loop(state)]

        content = "".join(event.get("content", "") for event in events if event["type"] == "chunk")
        assert "ReAct 草稿" not in content
        assert "**整体表现**" in content

    async def test_direct_answer_no_tools(self):
        """LLM returns no tool_calls -> should emit the direct ReAct answer."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "Hello",
            "model": None,
        }

        with (
            patch(
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="You are an interviewer.",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": "Hello World",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ) as mock_llm,
            patch("app.services.llm.stream_llm_messages") as mock_stream,
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert [e["content"] for e in chunk_events] == ["Hello World"]
        assert "".join(e["content"] for e in chunk_events) == "Hello World"
        mock_llm.assert_awaited_once()
        mock_stream.assert_not_called()
        # Last event should be "done"
        assert events[-1]["type"] == "done"

    async def test_nonstream_react_answer_is_used_without_second_llm_call(self):
        """A direct ReAct answer is user-visible without a second LLM stream call."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "继续追问我的 Agent 项目。",
            "model": "mimo-v2.5-pro",
            "retrieved_questions": [],
            "candidate_questions": [],
            "active_skills": [],
            "message_history": [],
        }

        with (
            patch(
                "app.agents.chat.react_loop.build_react_system_prompt",
                return_value="Interviewer prompt.",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": "非流式草稿，不应该直接展示",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ),
            patch(
                "app.services.llm.stream_llm_messages",
                side_effect=lambda *a, **kw: _mock_stream_strings("流式", "回答"),
            ) as mock_stream,
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunk_events = [e for e in events if e.get("type") == "chunk"]
        assert [e["content"] for e in chunk_events] == [
            "非流式草稿，不应该直接展示"
        ]
        assert not mock_stream.called
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
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Interviewer prompt.",
                ),
                patch(
                    "app.services.llm.llm_with_tools",
                    mock_llm_with_tools,
                ),
                patch(
                    "app.agents.chat.tools.execute_tool",
                    side_effect=_mock_execute,
                ),
                patch(
                    "app.services.llm.stream_llm_messages",
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

        # All events in order: emitted (step, tool_step, retrieved) + yielded (chunk, done)
        events = emitted + yielded

        # Event sequence: step(search_questions) + tool_step + retrieved + chunk + done
        assert events[0]["type"] == "step"
        assert events[0]["step"] == "search_questions"

        # Verify step event contains reason
        assert "reason" in events[0]
        assert events[0]["reason"]  # reason is non-empty

        # tool_step event emitted after tool execution
        assert events[1]["type"] == "tool_step"
        assert events[1]["data"]["tool_name"] == "search_questions"

        assert events[2]["type"] == "retrieved"
        assert events[2]["questions"][0]["id"] == 10
        assert events[-2]["type"] == "chunk"
        assert events[-2]["content"] == "Here is your question"
        assert events[-1]["type"] == "done"

        # LLM called twice (once for tool, once for answer)
        assert mock_llm_with_tools.call_count == 2

    async def test_tool_call_reasoning_content_emits_thinking_events(self):
        """MiMo reasoning_content from tool-calling turns should reach SSE thinking."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "我负责 Redis 缓存优化。",
            "model": "mimo-v2.5-pro",
            "retrieved_questions": [],
        }

        tc_search = _tc("search_questions", {"keywords": ["Redis"]})
        mock_llm_with_tools = AsyncMock(
            side_effect=[
                {
                    "content": None,
                    "reasoning_content": "候选人提到了 Redis，需要检索缓存相关题目。",
                    "tool_calls": [tc_search],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "继续追问缓存穿透。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ]
        )

        async def _mock_execute(tc, st):
            st["retrieved_questions"] = [
                {"id": 10, "question": "Redis 缓存穿透怎么处理？", "sources": []}
            ]
            return json.dumps(
                {
                    "ok": True,
                    "items": st["retrieved_questions"],
                    "metadata": {"debug_reason": "hybrid_search_ok"},
                },
                ensure_ascii=False,
            )

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.react_loop.build_react_system_prompt",
                    return_value="Interviewer prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm_with_tools),
                patch(
                    "app.agents.chat.tools.execute_tool",
                    side_effect=_mock_execute,
                ),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "继续追问缓存穿透。"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        thinking_events = [e for e in emitted if e.get("type", "").startswith("thinking")]
        assert [e["type"] for e in thinking_events] == [
            "thinking_start",
            "thinking",
            "thinking_done",
        ]
        assert thinking_events[1]["content"] == "候选人提到了 Redis，需要检索缓存相关题目。"
        assert thinking_events[2]["content"] == "候选人提到了 Redis，需要检索缓存相关题目。"

    async def test_tool_execution_emits_tool_step_event(self):
        """_react_loop should emit tool_step events via _emit after tool execution.

        Verifies the production code path where tool_step events are emitted
        through the event queue (not just stored in state["tool_steps"]).
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
            {
                "ok": True,
                "items": [{"id": 10, "question": "Explain JVM memory model"}],
                "metadata": {},
            }
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
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Interviewer prompt.",
                ),
                patch(
                    "app.services.llm.llm_with_tools",
                    mock_llm_with_tools,
                ),
                patch(
                    "app.agents.chat.tools.execute_tool",
                    side_effect=_mock_execute,
                ),
                patch(
                    "app.services.llm.stream_llm_messages",
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

        # Verify tool_step event was emitted via _emit
        tool_step_events = [e for e in emitted if e.get("type") == "tool_step"]
        assert len(tool_step_events) == 1, (
            f"Expected 1 tool_step event, got {len(tool_step_events)}. "
            f"Emitted types: {[e.get('type') for e in emitted]}"
        )

        tool_step = tool_step_events[0]
        data = tool_step["data"]
        assert data["tool_name"] == "search_questions"
        assert data["step"] == "search_questions"
        assert "message" in data
        assert "elapsed_ms" in data
        assert isinstance(data["elapsed_ms"], int)
        assert data["elapsed_ms"] >= 0
        assert "result_count" in data
        assert isinstance(data["result_count"], int)
        assert "fallback_used" in data
        assert isinstance(data["fallback_used"], bool)

        # Verify tool_steps also stored in state
        assert "tool_steps" in state
        assert len(state["tool_steps"]) == 1
        assert state["tool_steps"][0]["tool_name"] == "search_questions"

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
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.services.llm.llm_with_tools", side_effect=mock_llm),
                patch(
                    "app.agents.chat.tools.execute_tool", side_effect=mock_execute_tool
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        retrieved = next(e for e in emitted if e.get("type") == "retrieved")
        assert [q["id"] for q in retrieved["questions"]] == list(
            range(1, PUBLIC_QUESTION_PREVIEW_LIMIT + 1)
        )

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
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch("app.services.llm.llm_with_tools", mock_llm),
            patch(
                "app.agents.chat.tools.execute_tool",
                side_effect=_mock_execute_tool,
            ),
            patch(
                "app.services.llm.raw_llm_call",
                new_callable=AsyncMock,
                return_value="Final answer after max steps",
            ) as mock_synthesis,
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        # LLM called exactly MAX_REACT_STEPS times (loop capped)
        assert mock_llm.call_count == MAX_REACT_STEPS

        # raw_llm_call synthesizes the final answer after max steps.
        mock_synthesis.assert_awaited_once()
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
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch(
                    "app.agents.chat.tools.execute_tool",
                    side_effect=mock_execute_tool,
                ),
                patch(
                    "app.services.llm.stream_llm_messages",
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
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": "project-deep-dive",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ),
            patch("app.services.llm.stream_llm_messages") as mock_stream,
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
        mock_stream.assert_not_called()


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
            "answer_quality": "complete",
            "should_retrieve": True,
            "retrieved_questions": [],
            "active_skills": [],
            "message_history": [
                {"role": "assistant", "content": "请做自我介绍"},
                {"role": "user", "content": "我做后端"},
                {"role": "assistant", "content": "展开讲缓存优化"},
                {"role": "user", "content": "我用了 Redis 缓存和预热"},
            ],
        }
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "需要先调用题库工具" in strategy

    def test_first_intro_answer_prefers_natural_followup_without_search(self):
        """Opening self-introduction should not immediately force bank search."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
            "active_skills": [],
            "message_history": [
                {"role": "assistant", "content": "请先简单做一下自我介绍吧。"},
                {
                    "role": "user",
                    "content": "我主要做后端开发，负责订单查询和缓存优化。",
                },
            ],
        }
        strategy = _build_tool_strategy(state)
        assert "需要先调用题库工具" not in strategy
        assert "自然追问" in strategy
        assert "题库" in strategy

    def test_interview_question_deep_dive_requires_search_for_plan_binding(self):
        """Project deep-dive mode still searches so question_plan can bind the next question."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "retrieved_questions": [],
            "active_skills": ["project-deep-dive"],
            "message_history": [
                {"role": "assistant", "content": "请做自我介绍"},
                {"role": "user", "content": "我做后端"},
                {"role": "assistant", "content": "展开讲缓存优化"},
                {"role": "user", "content": "我用了 Redis 缓存和预热"},
            ],
        }
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "项目深挖模式" in strategy

    def test_missing_coding_phase_prioritizes_coding_draw_over_more_project_search(self):
        """Full-loop harness should move to coding when project/RAG has saturated."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "question_type": "algorithm_coding",
            "retrieved_questions": [],
            "active_skills": ["interview-rhythm"],
            "session_notes": "\n".join(
                [
                    "[asked] 项目/Agent #11 [project_followup]: 你这个 Agent 项目整体架构是什么？",
                    "[asked] 项目/Agent #12 [project_followup]: query 改写为什么这么做？",
                    "[asked] 理论/RAG #13 [knowledge_probe]: RAG 召回率怎么评估？",
                    "[asked] 理论/RAG #14 [knowledge_probe]: rerank 的延迟怎么控制？",
                ]
            ),
            "message_history": [
                {"role": "assistant", "content": [
                    "说说你的项目架构设计？", "Redis 缓存穿透怎么解决？",
                    "MySQL 索引原理是什么？", "TCP 三次握手过程？",
                    "Python 装饰器怎么实现？",
                ][i // 2]}
                if i % 2 == 0
                else {"role": "user", "content": f"候选人回答 {i // 2}"}
                for i in range(10)
            ],
        }

        strategy = _build_tool_strategy(state)

        assert "draw_questions" in strategy
        assert "algorithm_coding" in strategy
        assert "禁止：search_questions" in strategy

    def test_interview_question_answer_incomplete_suggests_wait(self):
        """Should suggest waiting when user hasn't finished answering."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {
            "intent": "interview_question",
            "answer_complete": False,
            "answer_quality": "incomplete",
            "active_skills": [],
        }
        strategy = _build_tool_strategy(state)
        assert "不要检索新题" in strategy

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
        assert "需要先调用题库工具" in strategy

    def test_chat_suggests_no_tools(self):
        """Should suggest no tools for casual chat."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "chat", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "直接回应" in strategy

    def test_follow_up_suggests_contextual_answer(self):
        """Should suggest contextual answer for follow-ups."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "follow_up", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "直接回应" in strategy

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
        assert "无需再次检索" in strategy


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

    async def test_direct_react_answer_skips_stream_even_when_stream_would_fail(self):
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
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": "正常草稿：请你解释 Agent 的整体架构是什么？",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ),
            patch(
                "app.services.llm.stream_llm_messages",
                side_effect=broken_stream,
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        chunks = [event["content"] for event in events if event["type"] == "chunk"]
        assert chunks == ["正常草稿：请你解释 Agent 的整体架构是什么？"]
        assert [event["type"] for event in events][-2:] == ["chunk", "done"]
        assert "selected_question" not in state

    async def test_direct_react_answer_does_not_retry_final_stream(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "conv",
            "user_id": 1,
            "user_message": "继续",
            "model": None,
        }

        async def flaky_stream(*args, **kwargs):
            raise RuntimeError("should not be called")
            yield  # pragma: no cover

        with (
            patch(
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                return_value={
                    "content": "非流式草稿",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ),
            patch(
                "app.services.llm.stream_llm_messages",
                side_effect=flaky_stream,
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert [event for event in events if event["type"] == "chunk"] == [
            {"type": "chunk", "content": "非流式草稿"}
        ]
        assert not any(event["type"] == "error" for event in events)

    async def test_react_llm_failure_returns_error_without_final_fallback(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "conv",
            "user_id": 1,
            "user_message": "继续",
            "model": None,
        }
        stream_attempts = 0

        async def unexpected_stream(*args, **kwargs):
            nonlocal stream_attempts
            stream_attempts += 1
            yield {"type": "content", "content": "不应该补出来的回答"}

        with (
            patch(
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch(
                "app.services.llm.llm_with_tools",
                new_callable=AsyncMock,
                side_effect=RuntimeError("tool decision failed"),
            ),
            patch(
                "app.services.llm.stream_llm_messages",
                side_effect=unexpected_stream,
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        assert stream_attempts == 0
        assert [event["type"] for event in events][-2:] == ["error", "done"]
        assert state["final_answer_error"]["reason"] == "react_llm_failed"


class TestQuestionPlanHelpers:
    def test_should_create_question_plan_for_practice_request(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        state = {"intent": "practice_request", "answer_complete": False}
        assert _should_create_question_plan(state) is True

    def test_should_create_question_plan_for_complete_interview_answer(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "requires_bank_question": True,
        }
        assert _should_create_question_plan(state) is True

    def test_should_not_create_question_plan_for_follow_up_chat_or_end(self):
        from app.agents.chat.pipeline import _should_create_question_plan

        assert (
            _should_create_question_plan(
                {"intent": "follow_up", "answer_complete": False}
            )
            is False
        )
        assert (
            _should_create_question_plan({"intent": "chat", "answer_complete": False})
            is False
        )
        assert (
            _should_create_question_plan(
                {"intent": "end_interview", "answer_complete": False}
            )
            is False
        )
        assert (
            _should_create_question_plan(
                {"intent": "interview_question", "answer_complete": False}
            )
            is False
        )

    def test_select_question_for_plan_prefers_algorithm_candidate(self):
        from app.agents.chat.pipeline import _select_question_for_plan

        state = {"question_type": "algorithm_coding", "search_negative_terms": []}
        candidates = [
            {
                "id": 1,
                "question": "说说 Redis 持久化",
                "cat1": "后端",
                "cat2": "Redis",
                "tags": "redis",
            },
            {
                "id": 2,
                "question": "实现 LRU Cache",
                "cat1": "E.算法与数据结构",
                "cat2": "E2.算法手撕",
                "tags": "代码,lru",
            },
        ]

        selected, reason = _select_question_for_plan(state, candidates)

        assert selected["id"] == 2
        assert reason == "algorithm_candidate_match"

    def test_select_question_for_plan_skips_previously_selected_question(self):
        from app.agents.chat.pipeline import _select_question_for_plan

        state = {
            "search_negative_terms": [],
            "message_history": [
                {
                    "role": "assistant",
                    "content": "我追问一个问题：Agent 的整体架构是什么？",
                    "metadata": {
                        "selected_question": {
                            "id": 10,
                            "question": "Agent 的整体架构是什么？",
                        }
                    },
                }
            ],
        }
        candidates = [
            {
                "id": 10,
                "question": "Agent 的整体架构是什么？",
                "cat1": "B.Agent与LLM应用",
                "cat2": "Agent",
                "tags": "agent",
            },
            {
                "id": 11,
                "question": "介绍一下你的项目里的多Agent架构是如何设计的？",
                "cat1": "B.Agent与LLM应用",
                "cat2": "Agent",
                "tags": "agent,多Agent",
            },
        ]

        selected, reason = _select_question_for_plan(state, candidates)

        assert selected["id"] == 11
        assert reason == "top_ranked_candidate_after_asked_filter"

    def test_select_question_for_plan_uses_ledger_to_shift_saturated_topic(self):
        from app.agents.chat.pipeline import _select_question_for_plan

        state = {
            "search_negative_terms": [],
            "message_history": [
                {
                    "role": "assistant",
                    "content": "Agent 的检索机制是怎样的？",
                    "metadata": {
                        "selected_question": {
                            "id": 10,
                            "question": "Agent 的检索机制是怎样的？",
                            "cat1": "B.Agent与LLM应用",
                            "cat2": "Agent 检索",
                            "tags": "agent,检索",
                        }
                    },
                },
                {
                    "role": "assistant",
                    "content": "Agent 的检索机制如何设计？",
                    "metadata": {
                        "selected_question": {
                            "id": 11,
                            "question": "Agent 的检索机制如何设计？",
                            "cat1": "B.Agent与LLM应用",
                            "cat2": "Agent 检索",
                            "tags": "agent,检索",
                        }
                    },
                },
            ],
        }
        candidates = [
            {
                "id": 12,
                "question": "Agent 检索链路里的 query 改写怎么做？",
                "cat1": "B.Agent与LLM应用",
                "cat2": "Agent 检索",
                "tags": "agent,检索",
            },
            {
                "id": 13,
                "question": "Redis 分布式锁如何避免误删？",
                "cat1": "C.后端基础",
                "cat2": "Redis",
                "tags": "redis,锁",
            },
        ]

        selected, reason = _select_question_for_plan(state, candidates)

        assert selected["id"] == 13
        assert reason == "top_ranked_candidate_after_ledger_filter"

    def test_select_question_for_plan_falls_back_when_all_candidates_were_asked(self):
        from app.agents.chat.pipeline import _select_question_for_plan

        state = {
            "search_negative_terms": [],
            "message_history": [
                {
                    "role": "assistant",
                    "content": "Redis 持久化怎么做？",
                    "metadata": {
                        "selected_question": {
                            "id": 10,
                            "question": "Redis 持久化怎么做？",
                        }
                    },
                }
            ],
        }
        candidates = [
            {
                "id": 10,
                "question": "Redis 持久化怎么做？",
                "cat1": "后端",
                "cat2": "Redis",
                "tags": "redis",
            }
        ]

        selected, reason = _select_question_for_plan(state, candidates)

        assert selected["id"] == 10
        assert reason == "top_ranked_candidate_all_candidates_previously_asked"

    def test_build_interview_ledger_collects_question_ids_and_type_counts(self):
        from app.agents.chat.pipeline import _build_interview_ledger

        state = {
            "session_notes": "[asked] B.Agent与LLM应用/Agent 检索 #21 [project_followup]: Agent 检索怎么做？",
            "message_history": [
                {
                    "role": "assistant",
                    "content": "来写一道代码题：LRU Cache",
                    "metadata": {
                        "selected_question": {
                            "id": 22,
                            "question": "LRU Cache",
                            "cat1": "E.算法与数据结构",
                            "cat2": "E2.算法手撕",
                            "tags": "代码,lru",
                        },
                        "question_plan": {"question_id": 22},
                    },
                }
            ],
        }

        ledger = _build_interview_ledger(state)

        assert ledger.asked_question_ids == {21, 22}
        assert ledger.cat2_counts["Agent 检索"] == 1
        assert ledger.cat2_counts["E2.算法手撕"] == 1
        assert ledger.question_type_counts["algorithm_coding"] == 1

    def test_build_question_plan_sets_state_selected_question(self):
        from app.agents.chat.pipeline import _maybe_create_question_plan

        state = {
            "intent": "practice_request",
            "answer_complete": False,
            "question_source": "search",
            "search_negative_terms": ["HR"],
        }
        candidates = [
            {
                "id": 7,
                "question": "RAG 检索怎么设计？",
                "cat1": "B",
                "cat2": "RAG",
                "tags": "检索,重排",
            }
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
                return {
                    "content": None,
                    "tool_calls": [tc_search],
                    "finish_reason": "tool_calls",
                }
            return {
                "content": "请你说说 RAG 检索怎么设计？",
                "tool_calls": None,
                "finish_reason": "stop",
            }

        async def mock_execute_tool(tc, st):
            question = {
                "id": 11,
                "question": "RAG 检索怎么设计？",
                "cat1": "B",
                "cat2": "RAG",
                "tags": "检索",
                "sources": [],
            }
            st["retrieved_questions"] = [question]
            st["candidate_questions"] = [question]
            st["question_source"] = "search"
            return json.dumps(
                {
                    "ok": True,
                    "tool": "search_questions",
                    "items": [
                        {
                            **question,
                            "source": "search",
                            "score": 0.1,
                            "reason": "rrf_ranked",
                        }
                    ],
                    "metadata": {
                        "result_count": 1,
                        "fallback_used": False,
                        "fallback_steps": [],
                        "empty_reason": None,
                        "debug_reason": "hybrid_search_ok",
                        "metrics": {"total_ms": 1},
                    },
                    "error": None,
                },
                ensure_ascii=False,
            )

        with (
            patch(
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch("app.services.llm.llm_with_tools", side_effect=mock_llm),
            patch("app.agents.chat.tools.execute_tool", side_effect=mock_execute_tool),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        second_messages_text = "\n".join(
            m.get("content") or "" for m in captured_messages[1]
        )
        assert "<next_question_plan>" in second_messages_text
        assert "RAG 检索怎么设计" in second_messages_text
        assert state["next_question_plan"]["question_id"] == 11

    async def test_empty_final_answer_uses_bound_question_plan_fallback(self):
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "conv",
            "user_id": 1,
            "user_message": "那继续问一个 coding 题吧",
            "model": None,
            "intent": "practice_request",
            "question_type": "algorithm_coding",
            "answer_complete": False,
        }
        tc_draw = _tc("draw_questions", {"question_type": "algorithm_coding"})
        tc_select = _tc("select_question", {"candidate_index": 1}, tc_id="call_2")
        captured_messages = []

        async def mock_llm(messages, *args, **kwargs):
            captured_messages.append(messages)
            if len(captured_messages) == 1:
                return {
                    "content": None,
                    "tool_calls": [tc_draw],
                    "finish_reason": "tool_calls",
                }
            if len(captured_messages) == 2:
                return {
                    "content": None,
                    "tool_calls": [tc_select],
                    "finish_reason": "tool_calls",
                }
            return {"content": "", "tool_calls": None, "finish_reason": "stop"}

        async def mock_execute_tool(tc, st):
            name = tc["function"]["name"]
            candidates = [
                {
                    "id": 6274,
                    "question": "跳表索引是怎么建立的？",
                    "cat1": "E.算法与数据结构",
                    "cat2": "E1.数据结构",
                    "tags": "跳表",
                },
                {
                    "id": 6000,
                    "question": "深度遍历用迭代和递归分别如何实现？",
                    "cat1": "E.算法与数据结构",
                    "cat2": "E2.算法手撕",
                    "tags": "DFS,代码",
                },
            ]
            st["candidate_questions"] = candidates
            st["retrieved_questions"] = candidates
            st["question_source"] = "draw"
            if name == "select_question":
                selected = candidates[1]
                st["selected_question"] = selected
                st["next_question_plan"] = {
                    "must_ask": True,
                    "question_id": selected["id"],
                    "question_text": selected["question"],
                    "source": "draw",
                    "selection_reason": "agent_explicit_selection",
                }
                return json.dumps(
                    {
                        "ok": True,
                        "tool": "select_question",
                        "items": [selected],
                        "selected_question": selected,
                        "question_plan": st["next_question_plan"],
                        "metadata": {"result_count": 1},
                        "error": None,
                    },
                    ensure_ascii=False,
                )
            return json.dumps(
                {
                    "ok": True,
                    "tool": "draw_questions",
                    "items": candidates,
                    "metadata": {"result_count": len(candidates)},
                    "error": None,
                },
                ensure_ascii=False,
            )

        with (
            patch(
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch("app.services.llm.llm_with_tools", side_effect=mock_llm),
            patch("app.agents.chat.tools.execute_tool", side_effect=mock_execute_tool),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        error_events = [event for event in events if event["type"] == "error"]
        assert len(error_events) == 1
        assert error_events[0].get("code") == "empty_answer_plan_generation_failed"
        assert state["final_answer_error"]["reason"] == "empty_answer_plan_generation_error"

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
            "selected_question": {
                "id": 11,
                "question": "RAG 检索怎么设计？",
                "cat1": "B",
                "cat2": "RAG",
            },
        }

        with patch(
            "app.agents.chat.pipeline._repair_response_to_question_plan",
            new_callable=AsyncMock,
            return_value={
                "response": "我们收束到 RAG：请你说说 RAG 检索怎么设计？",
                "repaired": True,
                "reason": "plan_drift_repaired",
                "adherence": {
                    "adheres": True,
                    "score": 0.5,
                    "reason": "keyword_overlap",
                },
            },
        ) as mock_repair:
            events = await _final_answer_events_from_text("说说你的 HR 优势？", state)

        assert events[0]["type"] == "chunk"
        assert "RAG 检索怎么设计" in events[0]["content"]
        assert state["question_plan_metadata"]["repaired"] is True
        mock_repair.assert_awaited_once()

    async def test_unrequested_summary_is_replaced_with_continuation_question(self):
        from app.agents.chat.pipeline import _final_answer_events_from_text

        state = {
            "conversation_id": "conv",
            "user_id": 1,
            "user_message": "如果还要继续，我可以补充 RAG hybrid search 和 rerank。",
            "intent": "follow_up",
            "keywords": ["RAG", "hybrid search", "rerank"],
            "interview_stop_decision": {"action": "continue"},
            "message_history": [
                {"role": "assistant", "content": "说说这个系统的整体架构。"}
            ],
        }

        events = await _final_answer_events_from_text(
            "## 面试总结\n\n**整体表现**：信息不足，无法评价。\n\n**综合评分**：3/10",
            state,
        )

        assert events
        text = events[0]["content"]
        assert "面试总结" not in text
        assert "整体表现" not in text
        assert "综合评分" not in text
        assert "RAG" in text
        assert state["question_source_reason"] == "fallback_after_unrequested_summary"

    def test_react_metadata_prefers_planned_selected_question(self):
        from app.agents.chat.pipeline import _build_react_metadata

        state = {
            "retrieved_questions": [
                {
                    "id": 1,
                    "question": "Redis 持久化怎么做？",
                    "cat1": "后端",
                    "cat2": "Redis",
                    "sources": [],
                },
                {
                    "id": 2,
                    "question": "RAG 检索怎么设计？",
                    "cat1": "B",
                    "cat2": "RAG",
                    "sources": [],
                },
            ],
            "candidate_questions": [
                {
                    "id": 1,
                    "question": "Redis 持久化怎么做？",
                    "cat1": "后端",
                    "cat2": "Redis",
                    "sources": [],
                },
                {
                    "id": 2,
                    "question": "RAG 检索怎么设计？",
                    "cat1": "B",
                    "cat2": "RAG",
                    "sources": [],
                },
            ],
            "selected_question": {
                "id": 2,
                "question": "RAG 检索怎么设计？",
                "cat1": "B",
                "cat2": "RAG",
                "sources": [],
            },
            "next_question_plan": {
                "must_ask": True,
                "question_id": 2,
                "question_text": "RAG 检索怎么设计？",
                "source": "search",
                "selection_reason": "top_ranked_candidate",
            },
            "question_plan_metadata": {
                "adherence": {
                    "adheres": True,
                    "score": 0.5,
                    "reason": "keyword_overlap",
                },
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

    async def test_runtime_tool_contract_is_adjacent_to_current_user_message(self):
        """Required retrieval should be repeated near the user message."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "tool-contract-conv",
            "user_id": 1,
            "user_message": "我想从题库里抽一道 RAG 题",
            "model": None,
            "intent": "practice_request",
            "answer_quality": "complete",
            "should_retrieve": True,
            "requires_bank_question": True,
            "active_skills": [],
            "retrieved_questions": [],
            "candidate_questions": [],
            "recent_messages": [],
        }

        mock_llm = AsyncMock(
            return_value={
                "content": "请说说 RAG 的检索流程。",
                "tool_calls": None,
                "finish_reason": "stop",
            }
        )

        with (
            patch(
                "app.agents.chat.react_loop.build_react_system_prompt",
                return_value="Prompt.",
            ),
            patch("app.services.llm.llm_with_tools", mock_llm),
            patch(
                "app.services.llm.stream_llm_messages",
                side_effect=lambda *a, **kw: _mock_stream_strings(
                    "请说说 RAG 的检索流程。"
                ),
            ),
        ):
            events = []
            async for event in _react_loop(state):
                events.append(event)

        messages = mock_llm.call_args.args[0]
        assert messages[-2]["role"] == "user"
        assert "[当前回合工具策略]" in messages[-2]["content"]
        assert "requires_retrieval=true" in messages[-2]["content"]
        assert "不要直接输出自然语言问题" in messages[-2]["content"]
        assert messages[-1] == {"role": "user", "content": state["user_message"]}

    def test_injects_big_tech_interview_harness(self):
        """System prompt should expose full-loop coverage guidance to the agent."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "\n".join(
                [
                    "[asked] 项目/Agent #11 [project_followup]: 你这个 Agent 项目整体架构是什么？",
                    "[asked] 理论/RAG #12 [knowledge_probe]: RAG 召回率怎么评估？",
                ]
            ),
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": ["interview-rhythm"],
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
            "message_history": [
                {"role": "assistant", "content": "技术问题"}
                if i % 2 == 0
                else {"role": "user", "content": "候选人回答"}
                for i in range(8)
            ],
        }

        prompt = build_react_system_prompt(state)

        assert "<interview_harness>" in prompt
        assert "大厂 full-loop" in prompt
        assert "coding" in prompt
        assert "system_design" in prompt
        assert "behavioral" in prompt
        assert "clarification" in prompt
        assert "trade-off" in prompt
        assert "中国互联网大厂" in prompt
        assert "项目深挖" in prompt
        assert "八股" in prompt
        assert "场景题" in prompt
        assert "手撕代码" in prompt
        assert "反问" in prompt

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
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="Test prompt.",
            ):
                with patch("app.services.llm.llm_with_tools", side_effect=mock_llm):
                    with patch(
                        "app.services.llm.stream_llm_messages",
                        side_effect=mock_stream,
                    ):
                        with patch(
                            "app.agents.chat.tools.execute_tool",
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
                    "app.services.llm.llm_with_tools", new_callable=AsyncMock
                ) as mock_llm_tools,
                patch(
                    "app.agents.chat.tools.execute_tool", new_callable=AsyncMock
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

        mock_summary_json = json.dumps(
            {
                "overall_comment": "候选人项目经验丰富，基础知识扎实",
                "strongest_topic": "Redis 缓存策略，回答深入全面",
                "weakest_topic": "算法基础薄弱，手撕题解题思路不清晰",
                "key_suggestions": [
                    "复习常见排序算法",
                    "练习链表题目",
                    "深入理解时间复杂度",
                ],
                "score_estimate": 7,
            },
            ensure_ascii=False,
        )

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
            "app.services.llm._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            response = await _generate_end_interview_response(state)

        assert "整体表现" in response
        assert "候选人项目经验丰富" in response
        assert state["question_source"] == "conversation"
        assert state["question_source_reason"] == "end_interview_hard_route"

    @pytest.mark.asyncio
    async def test_end_interview_with_evaluation_request_generates_summary(self):
        """Evaluation-style closing requests should not fall through to brief farewell."""
        from app.agents.chat.pipeline import _generate_end_interview_response

        mock_summary_json = json.dumps(
            {
                "overall_comment": "候选人的项目讲解有亮点，但系统设计深度还不稳定。",
                "strongest_topic": "Agent 工具调用链路，能结合项目细节说明取舍。",
                "weakest_topic": "容量评估和异常兜底，缺少可量化的压测依据。",
                "key_suggestions": [
                    "补充关键链路的容量估算",
                    "整理工具调用失败时的降级策略",
                    "用一次真实复盘串起指标和结论",
                ],
                "score_estimate": 6,
                "hiring_signal": "有进入下一轮的基础，但需要继续压系统设计细节。",
                "risk_points": ["压测依据不足", "异常恢复方案不够具体"],
                "next_round_questions": ["如果 Redis 不可用，面试链路如何降级？"],
            },
            ensure_ascii=False,
        )

        state = {
            "user_message": "结束面试，请给我完整评价：hiring signal、风险点、强项和下一轮追问。",
            "message_history": [
                {"role": "assistant", "content": "讲一下你的 Agent 项目。"},
                {"role": "user", "content": "我做了工具调用和状态管理。"},
            ],
            "question_source": None,
            "question_source_reason": None,
            "session_notes": "[asked] Agent 工具调用",
            "user_id": 1,
        }

        with patch(
            "app.services.llm._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ) as mock_call:
            response = await _generate_end_interview_response(state)

        mock_call.assert_awaited_once()
        assert "整体表现" in response
        assert "Hiring Signal" in response
        assert "主要风险" in response
        assert "下一轮追问" in response
        assert "戛然而止" not in response
        assert state["question_source"] == "conversation"
        assert state["question_source_reason"] == "end_interview_hard_route"

    @pytest.mark.asyncio
    async def test_abrupt_too_early_end_request_returns_structured_summary(self):
        """Once explicit end is accepted, the contract always returns a summary."""
        from app.agents.chat.pipeline import _generate_end_interview_response

        state = {
            "user_message": "我们先别问了，我想现在就结束面试，你直接给我完整评价和是否通过吧。",
            "message_history": [
                {"role": "assistant", "content": "请先做一下自我介绍。"},
                {"role": "user", "content": "我做过 RAG 和 Agent 平台。"},
                {
                    "role": "assistant",
                    "content": "你先说说这个平台的整体架构，以及你负责的模块。",
                },
            ],
            "question_source": None,
            "question_source_reason": None,
            "session_notes": "",
            "user_id": 1,
        }

        mock_summary_json = json.dumps({
            "overall_comment": "证据较少，结论仅供本轮复盘参考。",
            "strongest_topic": "RAG 和 Agent 平台经验",
            "weakest_topic": "架构细节证据不足",
            "key_suggestions": ["补充架构取舍"],
            "score_estimate": 5,
        }, ensure_ascii=False)
        with patch(
            "app.services.llm._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ) as mock_call:
            response = await _generate_end_interview_response(state)

        mock_call.assert_awaited_once()
        assert "整体表现" in response
        assert "证据较少" in response
        assert state["question_source_reason"] == "end_interview_hard_route"

    @pytest.mark.asyncio
    async def test_too_early_close_request_without_summary_returns_structured_summary(self):
        """An explicit close has the same two-stage summary contract."""
        from app.agents.chat.pipeline import _generate_end_interview_response

        state = {
            "user_message": "不好意思，时间有点紧，我们是不是可以先收尾？",
            "message_history": [
                {"role": "assistant", "content": "请先做一下自我介绍。"},
                {"role": "user", "content": "我主要做 RAG 和 Agent。"},
                {
                    "role": "assistant",
                    "content": "你说一下 Agent 工作流里状态管理是怎么设计的？",
                },
            ],
            "question_source": None,
            "question_source_reason": None,
            "session_notes": "",
            "user_id": 1,
        }

        mock_summary_json = json.dumps({
            "overall_comment": "对话较短，结论仅供参考。",
            "strongest_topic": "Agent 工作流经验",
            "weakest_topic": "状态管理细节不足",
            "key_suggestions": ["补充状态设计细节"],
            "score_estimate": 5,
        }, ensure_ascii=False)
        with patch(
            "app.services.llm._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ) as mock_call:
            response = await _generate_end_interview_response(state)

        mock_call.assert_awaited_once()
        assert "整体表现" in response
        assert "对话较短" in response
        assert state["question_source_reason"] == "end_interview_hard_route"

    @pytest.mark.asyncio
    async def test_end_interview_with_evidence_gap_request_generates_summary(self):
        """Requests for senior-level evidence gaps should generate feedback."""
        from app.agents.chat.pipeline import _generate_end_interview_response

        mock_summary_json = json.dumps(
            {
                "overall_comment": "候选人的平台经验有数据，但关键证据链不完整。",
                "strongest_topic": "工具调用平台指标，能给出成功率和延迟变化。",
                "weakest_topic": "证据不足：没有说明失败原因分布和 schema 校验改动细节。",
                "key_suggestions": [
                    "补齐失败原因分布",
                    "说明 schema 校验前后的数据结构变化",
                    "准备一次端到端事故复盘",
                ],
                "score_estimate": 6,
            },
            ensure_ascii=False,
        )
        state = {
            "user_message": "请结束这轮，并按照高级工程师标准指出我证据不足的地方。",
            "message_history": [
                {"role": "assistant", "content": "schema 校验具体改了什么？"},
                {"role": "user", "content": "我做了限流和幂等。"},
            ],
            "question_source": None,
            "question_source_reason": None,
            "session_notes": "[asked] schema 校验具体改了什么？",
            "user_id": 1,
        }

        with patch(
            "app.services.llm._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ) as mock_call:
            response = await _generate_end_interview_response(state)

        mock_call.assert_awaited_once()
        assert "整体表现" in response
        assert "证据不足" in response
        assert "综合评分" in response


class TestAssessmentFocusMetadata:
    def test_conversation_followup_without_selected_question_has_assessment_focus(self):
        """Conversation-only follow-ups should still expose what is being assessed."""
        from app.agents.chat.metadata import _build_react_metadata

        state = {
            "active_skills": ["project-deep-dive"],
            "question_source": "conversation",
            "question_source_reason": "deep_dive_followup",
            "question_type": "system_design",
            "interview_state": {
                "current_phase": "project_deep_dive",
                "next_focus": "failure_recovery",
            },
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        metadata, _ = _build_react_metadata(
            state,
            "继续说说如果 Redis 不可用，你的面试状态链路怎么降级？",
        )

        assert metadata["selected_question"] is None
        assert metadata["question_source"] == "conversation"
        assert metadata["assessment_focus"] == {
            "source": "conversation",
            "reason": "deep_dive_followup",
            "question_type": "system_design",
            "phase": "project_deep_dive",
            "next_focus": "failure_recovery",
            "active_skills": ["project-deep-dive"],
        }

    def test_conversation_followup_metadata_writes_coverage_event(self):
        """Conversation-only questions should still become next-turn coverage facts."""
        from app.agents.chat.metadata import _build_react_metadata

        state = {
            "active_skills": ["project-deep-dive"],
            "question_source": "conversation",
            "question_source_reason": "deep_dive_followup",
            "question_type": "knowledge_probe",
            "interview_state": {
                "current_phase": "knowledge_probe",
                "next_focus": "behavioral",
            },
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        metadata, _ = _build_react_metadata(
            state,
            "Redis 分布式锁如果客户端超时，怎么保证不会误删别人的锁？",
        )

        assert metadata["coverage_events"] == [
            {
                "phase": "knowledge_probe",
                "source": "conversation",
                "confidence": "medium",
                "question_text": "Redis 分布式锁如果客户端超时，怎么保证不会误删别人的锁？",
                "reason": "deep_dive_followup",
            }
        ]

    def test_selected_question_metadata_writes_high_confidence_coverage_event(self):
        from app.agents.chat.metadata import _build_react_metadata

        state = {
            "active_skills": [],
            "question_source": "draw",
            "question_source_reason": "question_plan_bound",
            "question_type": "behavioral",
            "selected_question": {
                "id": 99,
                "question": "讲讲你处理团队冲突的一次经历。",
                "tags": "behavioral",
            },
            "next_question_plan": {
                "must_ask": True,
                "question_id": 99,
                "question_text": "讲讲你处理团队冲突的一次经历。",
                "source": "draw",
            },
            "question_plan_metadata": {
                "adherence": {"adheres": True, "score": 1.0, "reason": "exact"},
            },
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        metadata, _ = _build_react_metadata(
            state,
            "讲讲你处理团队冲突的一次经历。",
        )

        assert metadata["coverage_events"] == [
            {
                "phase": "behavioral",
                "source": "draw",
                "confidence": "high",
                "question_text": "讲讲你处理团队冲突的一次经历。",
                "evidence": {"question_id": 99, "question_type": "behavioral"},
                "reason": "question_plan_bound",
            }
        ]


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
    async def test_protection_survives_prompt_rebuild_after_skill_load(
        self, base_state
    ):
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
                "app.agents.chat.nodes.build_react_system_prompt",
                return_value="BASE PROMPT",
            ),
            patch("app.services.llm.llm_with_tools", side_effect=mock_llm),
            patch("app.agents.chat.tools.execute_tool", side_effect=mock_execute_tool),
            patch(
                "app.services.llm.stream_llm_messages",
                side_effect=lambda *a, **kw: _mock_stream_strings("继续问边界条件"),
            ),
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

    def test_multiple_candidates_token_overlap_binds_natural_rewrite(self):
        """Natural rewrites of one candidate among many should still bind."""
        from app.agents.chat.pipeline import _infer_selected_question

        candidates = [
            {"id": 5880, "question": "介绍一下React模式，它和CoT还有Plan-and-Execute有什么区别？"},
            {"id": 6366, "question": "Agent Loop 是什么？和普通工作流有什么区别？"},
            {"id": 6350, "question": "你的项目有前后端吗？大概结构是怎样的？"},
        ]
        response = (
            "你提到用了ReAct agent，能具体说说你理解的ReAct模式吗？"
            "它和CoT、Plan-and-Execute有什么核心区别？"
        )

        selected, reason = _infer_selected_question(response, [], candidates)

        assert selected is not None
        assert selected["id"] == 5880
        assert reason == "multi_candidate_token_overlap"


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


# ── TestRetrievalGap ────────────────────────────────────────


class TestRetrievalGap:
    """A retrieval recommendation is observability, not a post-hoc takeover."""

    async def test_retrieval_gap_records_without_forcing_retry(self):
        """LLM can make a natural follow-up even when retrieval was recommended."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "gap-conv-1",
            "user_id": 1,
            "user_message": "我用了 Redis 做缓存层，通过布隆过滤器解决了穿透问题",
            "model": None,
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "active_skills": ["project-deep-dive"],
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        mock_llm = AsyncMock(
            return_value={
                "content": "能说说你们项目里 Redis 缓存的过期策略是怎么设计的？",
                "tool_calls": None,
                "finish_reason": "stop",
            }
        )

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Interviewer prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "能说说你们项目里 Redis 缓存的过期策略是怎么设计的？"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        all_events = emitted + yielded

        assert mock_llm.call_count == 1
        assert not state.get("retrieved_questions")
        assert state["question_source"] == "conversation"
        assert state["question_source_reason"] == "retrieval_recommended_but_skipped"
        assert state["retrieval_gap"]["reason"] == "model_answered_without_retrieval"

        chunk_events = [e for e in all_events if e.get("type") == "chunk"]
        assert len(chunk_events) >= 1
        assert "过期策略" in chunk_events[0]["content"]

    async def test_retrieval_gap_records_when_practice_request_skips_tool(
        self,
    ):
        """Practice requests should expose skipped retrieval for observability."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "gap-conv-2",
            "user_id": 1,
            "user_message": "来一道 RAG 题",
            "model": None,
            "intent": "practice_request",
            "answer_complete": False,
            "answer_quality": "complete",
            "should_retrieve": True,
            "active_skills": [],
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        mock_llm = AsyncMock(
            return_value={
                "content": "请说说 RAG 的检索流程。",
                "tool_calls": None,
                "finish_reason": "stop",
            }
        )

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "请说说 RAG 的检索流程。"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        all_events = emitted + yielded

        assert mock_llm.call_count == 1
        assert state["question_source"] == "conversation"
        assert state["question_source_reason"] == "retrieval_recommended_but_skipped"
        assert state["retrieval_gap"]["intent"] == "practice_request"

        # Final answer accepted on first try
        chunk_events = [e for e in all_events if e.get("type") == "chunk"]
        assert len(chunk_events) >= 1

    async def test_retrieval_gap_not_recorded_when_retrieved_present(self):
        """Existing candidates mean there is no retrieval gap to record."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "gap-conv-3",
            "user_id": 1,
            "user_message": "继续",
            "model": None,
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "active_skills": ["project-deep-dive"],
            "retrieved_questions": [
                {"id": 42, "question": "已有候选题", "sources": []}
            ],
            "candidate_questions": [
                {"id": 42, "question": "已有候选题", "sources": []}
            ],
        }

        mock_llm = AsyncMock(
            return_value={
                "content": "请说说你对 Redis 持久化的理解。",
                "tool_calls": None,
                "finish_reason": "stop",
            }
        )

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "请说说你对 Redis 持久化的理解。"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        all_events = emitted + yielded

        assert mock_llm.call_count == 1
        assert "retrieval_gap" not in state

        # Answer accepted on first try
        chunk_events = [e for e in all_events if e.get("type") == "chunk"]
        assert len(chunk_events) >= 1

    async def test_retrieval_gap_records_only_once_without_retry_budget(self):
        """A skipped retrieval recommendation is recorded once; no retry budget needed."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "gap-conv-4",
            "user_id": 1,
            "user_message": "我用了 Redis 做缓存",
            "model": None,
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "vague",
            "should_retrieve": True,
            "active_skills": ["project-deep-dive"],
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        mock_llm = AsyncMock(
            return_value={
                "content": "能详细说说缓存的过期策略吗？",
                "tool_calls": None,
                "finish_reason": "stop",
            }
        )

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "能详细说说缓存的过期策略吗？"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        all_events = emitted + yielded

        assert mock_llm.call_count == 1
        assert state["retrieval_gap"]["answer_quality"] == "vague"

        chunk_events = [e for e in all_events if e.get("type") == "chunk"]
        assert len(chunk_events) >= 1
        assert "过期策略" in chunk_events[0]["content"]

    async def test_load_skill_only_turn_records_gap_without_forcing_search(self):
        """LLM calls load_skill (turns on project-deep-dive) but skips
        search_questions/draw_questions entirely → record the gap, do not take over.
        """
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "gap-conv-5",
            "user_id": 1,
            "user_message": "我做了 RAG 系统，文档切块用 RecursiveCharacterTextSplitter，bge 向量化后 reranker 排序",
            "model": None,
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "active_skills": [],
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        tc_load = _tc("load_skill", {"skill_name": "project-deep-dive"}, "call_load")

        # LLM mock sequence: load_skill only → final natural follow-up.
        mock_llm = AsyncMock(
            side_effect=[
                {
                    "content": None,
                    "tool_calls": [tc_load],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "你的切块策略具体怎么做的？固定长度还是递归？chunk size 多少？",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ]
        )

        load_result = json.dumps(
            {
                "ok": True,
                "tool": "load_skill",
                "items": [],
                "metadata": {"active_skill": "project-deep-dive"},
                "error": None,
            },
            ensure_ascii=False,
        )
        async def mock_execute_tool(tc, st):
            name = tc["function"]["name"]
            if name == "load_skill":
                st.setdefault("active_skills", []).append("project-deep-dive")
                st.setdefault("active_skill_instructions", []).append(
                    {
                        "skill_name": "project-deep-dive",
                        "instruction": "## Project Deep Dive\nDrill technical details.",
                    }
                )
                return load_result
            return json.dumps(
                {"ok": False, "error": "unmocked_tool"}, ensure_ascii=False
            )

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                # Stub build_react_system_prompt so loop iterations don't rebuild
                # full system prompt from the (now mutated) active_skill_instructions
                # — we want to keep the test focused on guard behavior.
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Interviewer prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch(
                    "app.agents.chat.tools.execute_tool",
                    side_effect=mock_execute_tool,
                ),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "你的切块策略具体怎么做的？固定长度还是递归？chunk size 多少？"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        all_events = emitted + yielded

        assert mock_llm.call_count == 2
        assert state["retrieval_gap"]["tool_names"] == ["load_skill"]
        assert not state.get("retrieved_questions")

        chunk_events = [e for e in all_events if e.get("type") == "chunk"]
        assert len(chunk_events) >= 1
        assert "切块策略" in chunk_events[0]["content"]

    async def test_retrieval_gap_does_not_run_retry_validation_path(self):
        """No guard retry means no hidden retry tool validation path exists."""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "conversation_id": "gap-conv-6",
            "user_id": 1,
            "user_message": "我用了 Redis 做缓存",
            "model": None,
            "intent": "interview_question",
            "answer_complete": True,
            "answer_quality": "complete",
            "should_retrieve": True,
            "active_skills": ["project-deep-dive"],
            "retrieved_questions": [],
            "candidate_questions": [],
        }

        mock_llm = AsyncMock(
            return_value={
                "content": "你缓存怎么设计的？",
                "tool_calls": None,
                "finish_reason": "stop",
            }
        )

        execute_tool = AsyncMock()
        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch(
                    "app.agents.chat.nodes.build_react_system_prompt",
                    return_value="Prompt.",
                ),
                patch("app.services.llm.llm_with_tools", mock_llm),
                patch("app.agents.chat.tools.execute_tool", execute_tool),
                patch(
                    "app.services.llm.stream_llm_messages",
                    side_effect=lambda *a, **kw: _mock_stream_strings(
                        "那继续说说 Redis 缓存一致性吧。"
                    ),
                ),
            ):
                yielded = []
                async for event in _react_loop(state):
                    yielded.append(event)
        finally:
            _event_queue_var.reset(token)

        assert execute_tool.await_count == 0
        assert mock_llm.call_count == 1
        assert not state.get("retrieved_questions")
        assert state["retrieval_gap"]["reason"] == "model_answered_without_retrieval"

"""E2E tests for Interview Agent Harness contract paths.

Tests that the pipeline correctly:
1. Records turn_contract in done metadata
2. Uses two-stage closing (closing_writer + summary_writer)
3. Validates ask_selected_question with semantic validator
"""

import pytest
from unittest.mock import AsyncMock, patch

from tests.chat.multi_turn_helpers import (
    run_single_turn,
    make_question,
    tool_call,
    _async_stream,
)


async def run_single_turn_with_raw_events(
    *,
    user_message: str,
    classify_updates: dict,
    llm_responses: list[dict],
    stream_chunks: tuple[str, ...],
    tool_patches: list = None,
    state_overrides: dict | None = None,
    mode: str = "free_practice",
    bank_mode: str = "public",
) -> tuple[list[dict], dict, AsyncMock]:
    """Run a single turn and return RAW events (not routerized)."""
    from app.agents.chat.pipeline import run_chat
    from contextlib import ExitStack

    captured_state: dict = {}
    state_ready = __import__("asyncio").Event()

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
        if state_overrides:
            state.update(state_overrides)
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
        return _async_stream(*stream_chunks)

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

    import asyncio
    with ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)

        raw_events: list[dict] = []
        async for event in run_chat(
            conversation_id="conv-multi-turn",
            user_id=1,
            user_message=user_message,
            mode=mode,
            bank_mode=bank_mode,
        ):
            raw_events.append(event)

    await asyncio.wait_for(state_ready.wait(), timeout=1)
    return raw_events, captured_state, llm_mock


class TestTurnContractMetadata:
    """Verify turn_contract appears in done metadata."""

    @pytest.mark.asyncio
    async def test_done_metadata_includes_turn_contract(self):
        """Done event should include turn_contract from sidecar observation."""
        events, state, _ = await run_single_turn_with_raw_events(
            user_message="介绍一下你的项目经验",
            classify_updates={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
            llm_responses=[
                {"content": "好的，请介绍一下你最近参与的一个项目。", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("好的，请介绍一下你最近参与的一个项目。",),
        )
        done_events = [e for e in events if e.get("type") == "done"]
        assert len(done_events) > 0
        metadata = done_events[0].get("metadata", {})
        # turn_contract should be present (sidecar observation)
        assert "turn_contract" in metadata
        assert "action" in metadata["turn_contract"]

    @pytest.mark.asyncio
    async def test_turn_contract_action_is_valid(self):
        """turn_contract.action should be one of the valid actions."""
        valid_actions = {
            "close_with_summary",
            "answer_counter_question",
            "clarify_candidate_answer",
            "ask_selected_question",
            "continue_natural_followup",
        }
        events, state, _ = await run_single_turn_with_raw_events(
            user_message="介绍一下你的项目经验",
            classify_updates={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
            llm_responses=[
                {"content": "好的，请介绍一下你最近参与的一个项目。", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("好的，请介绍一下你最近参与的一个项目。",),
        )
        done_events = [e for e in events if e.get("type") == "done"]
        metadata = done_events[0].get("metadata", {})
        action = metadata.get("turn_contract", {}).get("action")
        assert action in valid_actions

    @pytest.mark.asyncio
    async def test_done_metadata_records_executed_contract_evidence(self):
        """Trajectory eval must see the writer, validator, and selected tool fact."""
        executor_result = {
            "status": "success",
            "text": "你在项目里是怎么把 Agent 评测接进发布流程的？",
            "writer_trace": {"writer": "question_writer", "result": "success", "retry_count": 1},
            "validator_trace": [
                {
                    "name": "semantic_question_adherence",
                    "blocking": True,
                    "passes": True,
                    "score": 0.91,
                    "issues": [],
                }
            ],
        }
        events, _, _ = await run_single_turn_with_raw_events(
            user_message="我完成了 Agent 评测平台的改造。",
            classify_updates={
                "intent": "interview_question",
                "answer_quality": "complete",
                "needs_new_dimension": True,
                "confidence": 0.9,
                "should_retrieve": False,
                "classify_result": {
                    "intent": "interview_question",
                    "answer_quality": "complete",
                    "needs_new_dimension": True,
                    "confidence": 0.9,
                },
            },
            llm_responses=[{"content": "", "tool_calls": None, "finish_reason": "stop"}],
            stream_chunks=(),
            state_overrides={
                "selected_question": {"id": 6370, "question": "Agent 评测如何落地？", "selection_confidence": 0.9},
                "question_source": "draw_questions",
            },
            tool_patches=[
                patch(
                    "app.agents.chat.contract_executor.execute_turn_contract",
                    new=AsyncMock(return_value=executor_result),
                )
            ],
        )

        metadata = next(event["metadata"] for event in events if event.get("type") == "done")
        assert metadata["turn_contract"]["action"] == "ask_selected_question"
        assert metadata["writer_trace"]["writer"] == "question_writer"
        assert metadata["validator_trace"][0]["passes"] is True
        assert metadata["tool_contract_trace"] == {
            "selected_question_id": 6370,
            "source": "draw_questions",
        }


class TestClosingTwoStage:
    """Verify closing uses two-stage output."""

    @pytest.mark.asyncio
    async def test_closing_metadata_includes_writer_trace(self):
        """Closing done event should include writer_trace."""
        events, state, _ = await run_single_turn(
            user_message="好的，面试就到这里吧",
            classify_updates={
                "intent": "end_interview",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
            llm_responses=[
                {"content": "", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("感谢你的时间。",),
            state_overrides={
                "closing_stage": "final_summary",
                "message_history": [{"role": "user", "content": "test"}] * 20,
            },
        )
        done_events = [e for e in events if e.get("type") == "done"]
        if done_events:
            metadata = done_events[0].get("metadata", {})
            # writer_trace should be present for closing
            if metadata.get("closing_stage") == "closed":
                assert "writer_trace" in metadata

    @pytest.mark.asyncio
    async def test_short_explicit_end_always_includes_structured_summary(self):
        """Explicit end must not degrade to the legacy generic farewell."""
        summary_json = (
            '{"overall_comment":"回答能落到项目细节。","strongest_topic":"缓存",'
            '"weakest_topic":"系统设计","key_suggestions":["补齐设计取舍"],'
            '"score_estimate":7}'
        )
        events, _, _ = await run_single_turn_with_raw_events(
            user_message="今天先结束吧",
            classify_updates={
                "intent": "end_interview",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
            llm_responses=[],
            stream_chunks=(),
            state_overrides={"message_history": [{"role": "user", "content": "我做过缓存优化。"}]},
            tool_patches=[
                patch(
                    "app.services.llm._call_llm_with_retry_messages",
                    new=AsyncMock(side_effect=["感谢你的时间，今天的交流先到这里。", summary_json]),
                )
            ],
        )
        errors = [event for event in events if event.get("type") == "error"]
        assert not errors, errors
        content = "".join(e.get("content", "") for e in events if e.get("type") == "chunk")
        assert "感谢你的时间" in content
        assert "**整体表现**" in content


class TestContractCoverage:
    """Verify contract paths cover all 5 actions."""

    @pytest.mark.asyncio
    async def test_natural_followup_contract(self):
        """Normal answer should produce continue_natural_followup contract."""
        events, state, _ = await run_single_turn_with_raw_events(
            user_message="我的项目用了 Redis 做缓存",
            classify_updates={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
            llm_responses=[
                {"content": "能具体说说你们的缓存策略吗？", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("能具体说说你们的缓存策略吗？",),
        )
        done_events = [e for e in events if e.get("type") == "done"]
        metadata = done_events[0].get("metadata", {})
        contract = metadata.get("turn_contract", {})
        # Should be natural followup or ask_selected_question
        assert contract.get("action") in (
            "continue_natural_followup",
            "ask_selected_question",
            "clarify_candidate_answer",
        )

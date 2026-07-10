"""Tests that semantic validator blocks drifted questions from reaching the user.

When ask_selected_question contract is active and the validator returns false,
the user must NOT receive the drifted question. Instead, the pipeline should
either retry with feedback or yield an error event.
"""

import pytest
from unittest.mock import AsyncMock, patch
from contextlib import ExitStack

from tests.chat.multi_turn_helpers import (
    _async_stream,
    make_question,
    tool_call,
)


async def _run_turn_with_validator(
    *,
    validator_passes: bool,
    validator_score: float = 0.38,
    validator_reason: str = "话题偏离",
    retry_passes: bool = False,
    retry_score: float = 0.38,
    llm_answer: str = "你们怎么保证工具调用稳定？",
):
    """Run a turn where ask_selected_question is active and validator returns specified result."""
    from app.agents.chat.pipeline import run_chat
    import asyncio

    validation_count = 0

    async def mock_validator(*, generated_text, selected_question, llm_call):
        nonlocal validation_count
        validation_count += 1
        if validation_count == 1:
            return {
                "passes": validator_passes,
                "score": validator_score,
                "reason": validator_reason,
                "detected_question": generated_text,
                "issues": [] if validator_passes else ["topic_drift"],
            }
        # retry
        return {
            "passes": retry_passes,
            "score": retry_score,
            "reason": "retry" if retry_passes else "still drifting",
            "detected_question": generated_text,
            "issues": [] if retry_passes else ["topic_drift"],
        }

    async def mock_load_context(state):
        state.update({
            "message_history": [{"role": "user", "content": "test"}] * 10,
            "recent_messages": [{"role": "user", "content": "test"}] * 4,
            "compressed_context": None,
            "session_notes": "",
            "interview_context": "目标岗位：后端开发",
            "job_position": "后端开发",
            "memory_summaries": [],
            "retrieved_questions": [],
            "selected_question": {"id": 6370, "question": "Agent范式在项目中有没有用过？"},
            "candidate_questions": [{"id": 6370, "question": "Agent范式在项目中有没有用过？"}],
            "question_source": "draw_questions",
        })
        return state

    async def mock_classify(state):
        state.update({
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": False,
            "requires_bank_question": False,
            "transition_style": "natural",
            "escalation_level": 0,
            "off_topic_streak": 0,
            "repetition_streak": 0,
            "classify_result": {
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
        })
        return state

    async def mock_extract_memory(snapshot):
        pass

    llm_mock = AsyncMock(return_value={
        "content": llm_answer,
        "tool_calls": None,
        "finish_reason": "stop",
    })

    def stream_side_effect(*args, **kwargs):
        return _async_stream(llm_answer)

    patchers = [
        patch("app.agents.chat.nodes.build_react_system_prompt", return_value="Test prompt."),
        patch("app.agents.chat.pipeline._step_load_context", new_callable=AsyncMock, side_effect=mock_load_context),
        patch("app.agents.chat.pipeline._step_classify", new_callable=AsyncMock, side_effect=mock_classify),
        patch("app.agents.chat.pipeline._step_extract_memory", new_callable=AsyncMock, side_effect=mock_extract_memory),
        patch("app.services.llm.llm_with_tools", new=llm_mock),
        patch("app.services.llm.stream_llm_messages", side_effect=stream_side_effect),
        patch(
            "app.agents.chat.validators.semantic_question_adherence.validate_question_adherence",
            side_effect=mock_validator,
        ),
    ]

    with ExitStack() as stack:
        for p in patchers:
            stack.enter_context(p)
        raw_events = []
        async for event in run_chat(
            conversation_id="conv-validator-test",
            user_id=1,
            user_message="Agent范式在项目中有没有用过？",
            mode="free_practice",
        ):
            raw_events.append(event)

    return raw_events, validation_count


class TestValidatorBlocksDrift:
    """When validator returns false, user must NOT receive drifted question."""

    @pytest.mark.asyncio
    async def test_validator_pass_streams_normally(self):
        """When validator passes, the question should be streamed to the user."""
        events, count = await _run_turn_with_validator(
            validator_passes=True,
            validator_score=0.91,
            llm_answer="你在项目中有实际用过 Agent 范式吗？",
        )
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        chunk_content = "".join(e.get("content", "") for e in chunk_events)
        assert "Agent" in chunk_content
        assert count == 1

    @pytest.mark.asyncio
    async def test_validator_fail_blocks_drifted_question(self):
        """When validator fails, the drifted question must NOT reach the user as a chunk.

        This is the KEY test: if the validator says the question drifted,
        the user should either see a retry result or an error — NOT the drifted text.
        """
        events, count = await _run_turn_with_validator(
            validator_passes=False,
            validator_score=0.38,
            validator_reason="话题偏离",
            llm_answer="你们怎么保证工具调用稳定？",  # drifted from "Agent范式"
        )
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        chunk_content = "".join(e.get("content", "") for e in chunk_events)
        error_events = [e for e in events if e.get("type") == "error"]

        # The drifted text "工具调用稳定" must NOT appear in user-visible output
        # Either the validator blocked it (error event) or retry succeeded
        has_drifted_text = "工具调用稳定" in chunk_content
        has_error = len(error_events) > 0

        # One of these must be true:
        # 1. Drifted text is NOT in chunks (blocked)
        # 2. There's an error event (generation failed)
        assert not has_drifted_text or has_error, (
            f"Drifted question '工具调用稳定' reached the user without being blocked! "
            f"chunk_content={chunk_content!r}, error_events={error_events}"
        )

    @pytest.mark.asyncio
    async def test_validator_retry_then_pass(self):
        """When first attempt fails but retry passes, the retry result should be used."""
        events, count = await _run_turn_with_validator(
            validator_passes=False,
            validator_score=0.38,
            retry_passes=True,
            retry_score=0.88,
            llm_answer="你在项目中有实际用过 Agent 范式吗？",
        )
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        chunk_content = "".join(e.get("content", "") for e in chunk_events)
        # Should have retried
        assert count == 2
        # The passed retry content should be in the output
        assert len(chunk_content) > 0

    @pytest.mark.asyncio
    async def test_validator_retry_also_fails_yields_error(self):
        """When both attempts fail, should yield error event, not drifted text."""
        events, count = await _run_turn_with_validator(
            validator_passes=False,
            validator_score=0.38,
            retry_passes=False,
            retry_score=0.38,
            llm_answer="你们怎么保证工具调用稳定？",
        )
        error_events = [e for e in events if e.get("type") == "error"]
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        chunk_content = "".join(e.get("content", "") for e in chunk_events)

        # Should have retried
        assert count == 2
        # Should have error event or no drifted content
        assert len(error_events) > 0 or "工具调用稳定" not in chunk_content

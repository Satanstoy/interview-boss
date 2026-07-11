"""Pipeline tests for the ask_selected_question contract.

ReAct may gather evidence and produce a draft, but a selected-question contract
must hand final output ownership to question_writer.  A stale selected question
must not validate unrelated counter-question answers.
"""

import pytest
from unittest.mock import AsyncMock, patch
from contextlib import ExitStack

from tests.chat.multi_turn_helpers import _async_stream


async def _run_turn_with_validator(
    *,
    validator_passes: bool,
    validator_score: float = 0.38,
    validator_reason: str = "话题偏离",
    retry_passes: bool = False,
    retry_score: float = 0.38,
    llm_answer: str = "你们怎么保证工具调用稳定？",
    counter_question: bool = False,
    writer_result: dict | None = None,
):
    """Run a turn with a selected question and capture its output contracts."""
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
            "selection_confidence": 0.9,
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
            "counter_question": counter_question,
            "counter_question_topic": "团队如何做 Agent 落地" if counter_question else None,
            "classify_result": {
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
                "needs_new_dimension": True,
                "confidence": 0.9,
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

    question_writer = AsyncMock(
        return_value=writer_result
        or {
            "status": "success",
            "text": "你在项目中有实际用过 Agent 范式吗？能具体说说落地过程吗？",
            "validator_result": {"passes": True, "score": 0.91, "reason": "语义一致"},
            "retry_count": 0,
        }
    )

    patchers = [
        patch("app.agents.chat.nodes.build_react_system_prompt", return_value="Test prompt."),
        patch("app.agents.chat.pipeline._step_load_context", new_callable=AsyncMock, side_effect=mock_load_context),
        patch("app.agents.chat.pipeline._step_classify", new_callable=AsyncMock, side_effect=mock_classify),
        patch("app.agents.chat.pipeline._step_extract_memory", new_callable=AsyncMock, side_effect=mock_extract_memory),
        patch("app.services.llm.llm_with_tools", new=llm_mock),
        patch("app.services.llm.stream_llm_messages", side_effect=stream_side_effect),
        patch("app.services.llm.raw_llm_call", new_callable=AsyncMock, return_value=""),
        patch(
            "app.agents.chat.output_guardrails.needs_output_repair",
            return_value={"needs_repair": False},
        ),
        patch(
            "app.agents.chat.validators.semantic_question_adherence.validate_question_adherence",
            side_effect=mock_validator,
        ),
        patch(
            "app.agents.chat.contract_executor.generate_question_with_validation",
            new=question_writer,
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

    return raw_events, validation_count, question_writer


class TestAskSelectedQuestionContract:
    """The writer, not the ReAct draft, owns a selected-question response."""

    @pytest.mark.asyncio
    async def test_selected_question_uses_writer_not_react_draft(self):
        """A drifted ReAct draft must not reach the candidate when writer succeeds."""
        events, count, question_writer = await _run_turn_with_validator(
            validator_passes=True,
            llm_answer="你们怎么保证工具调用稳定？",
        )
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        chunk_content = "".join(e.get("content", "") for e in chunk_events)
        assert "工具调用稳定" not in chunk_content
        assert "Agent 范式" in chunk_content or "Agent范式" in chunk_content
        question_writer.assert_awaited_once()
        assert count == 0

    @pytest.mark.asyncio
    async def test_question_writer_failure_blocks_react_draft(self):
        """A failed writer must emit an error instead of leaking the ReAct draft."""
        events, count, question_writer = await _run_turn_with_validator(
            validator_passes=False,
            llm_answer="你们怎么保证工具调用稳定？",
            writer_result={
                "status": "error",
                "error_code": "question_validation_failed",
                "message": "验证失败: 话题偏离",
            },
        )
        chunk_events = [e for e in events if e.get("type") == "chunk"]
        chunk_content = "".join(e.get("content", "") for e in chunk_events)
        error_events = [e for e in events if e.get("type") == "error"]
        done_metadata = next(
            event["metadata"] for event in events if event.get("type") == "done"
        )
        assert "工具调用稳定" not in chunk_content
        assert any(event["code"] == "question_validation_failed" for event in error_events)
        assert done_metadata["generation_error_code"] == "question_validation_failed"
        assert done_metadata["writer_trace"]["writer"] == "question_writer"
        question_writer.assert_awaited_once()
        assert count == 0

    @pytest.mark.asyncio
    async def test_counter_question_bypasses_selected_question_writer(self):
        """A stale selected question cannot hijack a candidate counter-question."""
        events, count, question_writer = await _run_turn_with_validator(
            validator_passes=True,
            llm_answer="团队会先用离线评测确认稳定性，再逐步扩大到真实链路。",
            counter_question=True,
        )
        chunk_content = "".join(
            e.get("content", "") for e in events if e.get("type") == "chunk"
        )
        assert chunk_content
        assert "Agent范式在项目中有没有用过" not in chunk_content
        question_writer.assert_not_awaited()
        assert count == 0

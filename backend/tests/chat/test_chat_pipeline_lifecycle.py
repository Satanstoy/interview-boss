"""Regression tests for the chat pipeline's async-generator lifecycle."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.chat import pipeline


@pytest.mark.asyncio
async def test_run_chat_can_close_from_a_different_async_context(monkeypatch):
    """Closing the SSE generator from another task must not reset a foreign token."""

    release_pipeline = asyncio.Event()

    async def fake_load_interview_config(_state):
        return None

    async def fake_load_context(_state):
        return None

    async def fake_classify(state):
        state["intent"] = "interview_question"
        state["classify_result"] = {}
        return state

    class FakeTurnIntent:
        def to_metadata_dict(self):
            return {}

    async def fake_react_loop(_state):
        yield {"type": "chunk", "content": "partial response"}
        await release_pipeline.wait()

    async def fake_noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(pipeline, "_load_interview_config", fake_load_interview_config)
    monkeypatch.setattr(pipeline, "_step_load_context", fake_load_context)
    monkeypatch.setattr(pipeline, "_step_classify", fake_classify)
    monkeypatch.setattr(pipeline, "_refresh_interview_state_snapshot", lambda _state: None)
    monkeypatch.setattr(pipeline, "_react_loop", fake_react_loop)
    monkeypatch.setattr(pipeline, "_persist_active_skills", fake_noop)
    monkeypatch.setattr(pipeline, "_persist_mcp_session", fake_noop)
    monkeypatch.setattr(pipeline, "_step_extract_memory", fake_noop)
    monkeypatch.setattr(pipeline, "_build_react_metadata", lambda _state, response: ({}, response))
    monkeypatch.setattr(pipeline, "_attach_executed_contract_metadata", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_record_asked_question_if_any", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_basis_event_payload", lambda _metadata: {})
    monkeypatch.setattr(
        "app.agents.chat.distribution_runtime.apply_distribution_control",
        lambda _state: None,
    )
    monkeypatch.setattr(
        "app.agents.chat.turn_intent.build_turn_intent",
        lambda _state: FakeTurnIntent(),
    )

    stream = pipeline.run_chat(
        conversation_id="context-close-regression",
        user_id=1,
        user_message="继续",
    )

    first_event = await stream.__anext__()
    assert first_event == {"type": "chunk", "content": "partial response"}

    close_error = None
    try:
        # Starlette/asyncio may close a suspended async generator in a
        # different task from the one that first advanced it.
        await asyncio.create_task(stream.aclose())
    except Exception as exc:  # assertion below turns the regression into a test failure
        close_error = exc
    finally:
        release_pipeline.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert close_error is None, f"stream cleanup raised unexpectedly: {close_error!r}"

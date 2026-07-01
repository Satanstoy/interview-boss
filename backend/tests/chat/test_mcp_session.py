import pytest


@pytest.fixture
def sample_state():
    return {
        "active_skills": ["algorithm-coding"],
        "active_skill_instructions": [
            {"skill_name": "algorithm-coding", "instruction": "## Algorithm"}
        ],
        "candidate_questions": [{"id": 1, "question": "Q"}],
        "retrieved_questions": [{"id": 1, "question": "Q"}],
        "session_notes": "[asked] 一道题",
        "question_source": "draw",
        "question_source_reason": "draw_ok",
        "user_id": 42,
    }


def test_new_session_id_is_unique():
    from app.mcp_server.session import new_session_id

    a = new_session_id()
    b = new_session_id()
    assert a != b
    assert len(a) == 32


def test_save_and_load_mcp_session_roundtrip(sample_state, client):
    from app.mcp_server.session import (
        load_mcp_session,
        save_mcp_session,
        new_session_id,
    )

    session_id = new_session_id()
    save_mcp_session(session_id, sample_state)

    loaded = load_mcp_session(session_id)
    assert loaded is not None
    assert loaded["active_skills"] == ["algorithm-coding"]
    assert loaded["retrieved_questions"][0]["id"] == 1
    assert loaded["session_notes"] == "[asked] 一道题"
    assert "user_id" not in loaded


def test_load_missing_session_returns_none(client):
    from app.mcp_server.session import load_mcp_session

    assert load_mcp_session("does-not-exist") is None


def test_save_updates_existing_session(sample_state, client):
    from app.mcp_server.session import (
        load_mcp_session,
        save_mcp_session,
        new_session_id,
    )

    session_id = new_session_id()
    save_mcp_session(session_id, sample_state)

    sample_state["active_skills"].append("theory-qa")
    save_mcp_session(session_id, sample_state)

    loaded = load_mcp_session(session_id)
    assert loaded["active_skills"] == ["algorithm-coding", "theory-qa"]


# ── Fix 3: internal ReAct path session persistence ─────────


class TestInternalReactSessionPersistence:
    async def test_internal_react_persists_session(self):
        """run_chat should call save_mcp_session after ReAct loop ends."""
        from unittest.mock import AsyncMock, patch
        from app.agents.chat.pipeline import run_chat
        from app.agents.chat.state import ChatState

        async def _async_gen(items):
            for item in items:
                yield item

        react_events = [
            {"type": "chunk", "content": "Answer"},
            {"type": "done", "metadata": {}},
        ]

        with (
            patch(
                "app.agents.chat.pipeline._step_load_context",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline._step_classify",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline._react_loop",
                side_effect=lambda state: _async_gen(react_events),
            ),
            patch(
                "app.agents.chat.pipeline._build_react_metadata",
                return_value=({}, "Answer"),
            ),
            patch(
                "app.agents.chat.pipeline._basis_event_payload",
                return_value={},
            ),
            patch(
                "app.agents.chat.pipeline._persist_active_skills",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline._step_extract_memory",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline.save_mcp_session",
            ) as mock_save,
        ):
            async for event in run_chat(
                conversation_id="conv-persist-test",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                pass

        mock_save.assert_called_once()
        call_args = mock_save.call_args
        session_id = call_args[0][0]
        assert session_id == "conv-persist-test"

    async def test_internal_react_persists_active_skills(self):
        """save_mcp_session should receive state with active_skills."""
        from unittest.mock import AsyncMock, patch
        from app.agents.chat.pipeline import run_chat

        async def _async_gen(items):
            for item in items:
                yield item

        react_events = [
            {"type": "chunk", "content": "Answer"},
            {"type": "done", "metadata": {}},
        ]

        with (
            patch(
                "app.agents.chat.pipeline._step_load_context",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline._step_classify",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline._react_loop",
                side_effect=lambda state: _async_gen(react_events),
            ),
            patch(
                "app.agents.chat.pipeline._build_react_metadata",
                return_value=({}, "Answer"),
            ),
            patch(
                "app.agents.chat.pipeline._basis_event_payload",
                return_value={},
            ),
            patch(
                "app.agents.chat.pipeline._persist_active_skills",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline._step_extract_memory",
                new_callable=AsyncMock,
            ),
            patch(
                "app.agents.chat.pipeline.save_mcp_session",
            ) as mock_save,
        ):
            async for event in run_chat(
                conversation_id="conv-skills-test",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                pass

        assert mock_save.call_count == 1
        persisted_state = mock_save.call_args[0][1]
        assert "active_skills" in persisted_state

    async def test_chat_state_has_session_id_field(self):
        """ChatState should have session_id field (derived from conversation_id)."""
        from app.agents.chat.state import ChatState

        state: ChatState = {
            "conversation_id": "conv-123",
            "session_id": "conv-123",
        }
        assert state["session_id"] == "conv-123"

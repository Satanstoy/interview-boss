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

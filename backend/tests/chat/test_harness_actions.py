"""Append-only Action/Attempt/Artifact lifecycle tests."""

import asyncio

from app.db.connection import get_db_connection
from app.services import chat_service


def test_action_is_idempotent_and_attempt_retry_preserves_previous_attempt(test_db):
    conversation = chat_service.create_conversation(
        user_id=1, mode="free_practice", job_position="agent_llm"
    )
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-action-1", "请追问项目中的故障处理"
    )

    action = chat_service.create_harness_action(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_key="observe:0",
        action_type="observe",
        phase="observe_propose",
        input_payload={"message": "请追问项目中的故障处理"},
    )
    replayed_action = chat_service.create_harness_action(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_key="observe:0",
        action_type="observe",
        phase="observe_propose",
        input_payload={"message": "请追问项目中的故障处理"},
    )
    first = chat_service.start_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        call_mode="observe_propose",
        provider="test-provider",
        model="test-model",
        context_pack_hash="ctx-a",
    )
    second = chat_service.start_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        call_mode="observe_propose",
        provider="test-provider",
        model="test-model",
        context_pack_hash="ctx-b",
    )

    assert replayed_action["id"] == action["id"]
    assert first["attempt_no"] == 1
    assert second["attempt_no"] == 2
    with get_db_connection() as conn:
        attempts = conn.execute(
            "SELECT attempt_no, status, context_pack_hash FROM interview_attempts "
            "WHERE action_id = ? ORDER BY attempt_no",
            (action["id"],),
        ).fetchall()
        action_row = conn.execute(
            "SELECT status, current_attempt_no FROM interview_actions WHERE id = ?",
            (action["id"],),
        ).fetchone()
        turn_row = conn.execute(
            "SELECT current_action_id, current_attempt_no FROM chat_turns WHERE id = ?",
            (turn.id,),
        ).fetchone()

    assert [(row["attempt_no"], row["status"]) for row in attempts] == [
        (1, "superseded"),
        (2, "active"),
    ]
    assert attempts[0]["context_pack_hash"] == "ctx-a"
    assert action_row["status"] == "started"
    assert action_row["current_attempt_no"] == 2
    assert turn_row["current_action_id"] == action["id"]
    assert turn_row["current_attempt_no"] == 2

    finished = chat_service.finish_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        attempt_id=second["id"],
        status="succeeded",
        output={"status": "completed"},
    )
    assert finished["status"] == "succeeded"
    with get_db_connection() as conn:
        action_row = conn.execute(
            "SELECT status, output_json FROM interview_actions WHERE id = ?",
            (action["id"],),
        ).fetchone()
    assert action_row["status"] == "completed"
    assert "completed" in action_row["output_json"]


def test_artifacts_are_immutable_and_replayable(test_db):
    conversation = chat_service.create_conversation(user_id=1, mode="free_practice")
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-artifact-1", "回答缓存击穿"
    )
    action = chat_service.create_harness_action(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_key="write:0",
        action_type="write",
        phase="write_response",
    )
    attempt = chat_service.start_harness_attempt(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        call_mode="write_response",
        provider="test-provider",
        model="test-model",
        context_pack_hash="ctx-write",
    )
    artifact = chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        action_id=action["id"],
        attempt_id=attempt["id"],
        artifact_type="reasoning",
        content={"text": "先检查证据"},
        visibility="audit",
    )

    assert artifact["content_hash"]
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT artifact_type, content_json, visibility FROM interview_artifacts WHERE id = ?",
            (artifact["id"],),
        ).fetchone()

    assert row["artifact_type"] == "reasoning"
    assert row["visibility"] == "audit"
    assert "先检查证据" in row["content_json"]


def test_harness_agent_adapter_persists_provider_request_and_response(test_db):
    from app.agents.chat.harness_agent import run_harness_agent_call

    conversation = chat_service.create_conversation(user_id=1, mode="free_practice")
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-agent-adapter", "请追问缓存设计"
    )
    state = {
        "user_id": 1,
        "conversation_id": conversation["id"],
        "turn_id": turn.id,
        "model": "test-model",
        "context_pack_hash": "ctx-agent",
    }

    result = asyncio.run(
        run_harness_agent_call(
            state=state,
            call_mode="observe_propose",
            action_key="react:1",
            request_payload={"messages": [{"role": "user", "content": "缓存"}]},
            call=lambda: _return_provider_result(),
        )
    )
    assert result["payload"]["action"] == "ask_followup"
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT artifact_type FROM interview_artifacts WHERE turn_id = ?",
            (turn.id,),
        ).fetchall()
        attempt = conn.execute(
            "SELECT call_mode, status, context_pack_hash FROM interview_attempts WHERE turn_id = ?",
            (turn.id,),
        ).fetchone()
    assert sorted(row["artifact_type"] for row in rows) == sorted([
        "provider_request",
        "provider_response",
    ])
    assert attempt["call_mode"] == "observe_propose"
    assert attempt["status"] == "succeeded"
    assert attempt["context_pack_hash"] == "ctx-agent"


def test_harness_agent_adapter_replays_succeeded_attempt_after_recovery(test_db):
    from app.agents.chat.harness_agent import run_harness_agent_call

    conversation = chat_service.create_conversation(user_id=1, mode="free_practice")
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-agent-recovery", "继续追问缓存设计"
    )
    state = {
        "user_id": 1,
        "conversation_id": conversation["id"],
        "turn_id": turn.id,
        "model": "test-model",
        "context_pack_hash": "ctx-recovery",
    }
    calls = {"count": 0}

    async def provider():
        calls["count"] += 1
        return {"payload": {"action": "ask_followup"}, "status": "completed"}

    first = asyncio.run(
        run_harness_agent_call(
            state=state,
            call_mode="observe_propose",
            action_key="react:recovery",
            request_payload={"messages": []},
            call=provider,
        )
    )

    async def should_not_call():
        raise AssertionError("recovered attempts must not call the provider again")

    second = asyncio.run(
        run_harness_agent_call(
            state=state,
            call_mode="observe_propose",
            action_key="react:recovery",
            request_payload={"messages": []},
            call=should_not_call,
        )
    )
    assert first == second
    assert calls["count"] == 1
    with get_db_connection() as conn:
        attempt_count = conn.execute(
            "SELECT COUNT(*) FROM interview_attempts WHERE turn_id = ?", (turn.id,)
        ).fetchone()[0]
    assert attempt_count == 1


async def _return_provider_result():
    return {"payload": {"action": "ask_followup"}, "status": "completed"}

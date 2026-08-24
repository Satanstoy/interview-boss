"""Outbox publisher contract: DB is truth, broker is only a projection."""

import pytest

from app.services import chat_service


def test_outbox_publisher_emits_canonical_event_and_acknowledges(test_db):
    from app.services.harness_event_publisher import publish_pending_harness_events

    conversation = chat_service.create_conversation(1, "free_practice", job_position="agent_llm")
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "publisher-request", "继续追问"
    )
    event = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="publisher-event",
        event_type="action.started",
        action_id="action-1",
        phase="observe_propose",
        channel="system",
        payload={"call_mode": "observe_propose"},
    )
    delivered = []

    async def publish(value):
        delivered.append(value)

    result = __import__("asyncio").run(
        publish_pending_harness_events(publish=publish, limit=10)
    )

    assert result == {"claimed": 1, "published": 1, "failed": 0}
    assert delivered[0]["event_id"] == event["event_id"]
    assert delivered[0]["sequence"] == 1
    assert delivered[0]["type"] == "action.started"
    assert delivered[0]["payload"] == {"call_mode": "observe_propose"}
    assert test_db.execute(
        "SELECT status FROM interview_event_outbox WHERE event_id = ?",
        (event["event_id"],),
    ).fetchone()["status"] == "published"


@pytest.mark.asyncio
async def test_outbox_publisher_retries_after_broker_failure(test_db):
    from app.services.harness_event_publisher import publish_pending_harness_events

    conversation = chat_service.create_conversation(1, "free_practice", job_position="agent_llm")
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "publisher-failure", "继续追问"
    )
    event = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="publisher-failure-event",
        event_type="turn.completed",
        action_id=None,
        phase="commit",
        channel="system",
        payload={"status": "completed"},
    )

    async def publish(_value):
        raise RuntimeError("broker down")

    result = await publish_pending_harness_events(publish=publish, limit=10)
    assert result == {"claimed": 1, "published": 0, "failed": 1}
    row = test_db.execute(
        "SELECT status, last_error FROM interview_event_outbox WHERE event_id = ?",
        (event["event_id"],),
    ).fetchone()
    assert row["status"] == "failed"
    assert row["last_error"] == "broker down"

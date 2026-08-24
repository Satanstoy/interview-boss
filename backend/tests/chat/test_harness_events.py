"""Harness 2.0 append-only event and outbox contract."""

from app.services import chat_service


def _conversation():
    return chat_service.create_conversation(1, "free_practice", job_position="agent_llm")


def _turn(conversation_id: str):
    return chat_service.reserve_chat_turn(
        conversation_id,
        1,
        "harness-events-request",
        "我负责过一个高并发缓存系统。",
    )


def test_append_turn_event_assigns_sequence_and_outbox(test_db):
    conversation = _conversation()
    turn = _turn(conversation["id"])

    started = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="evt-started",
        event_type="action.started",
        action_id="action-observe",
        phase="observe_propose",
        channel="system",
        payload={"call_mode": "observe_propose"},
    )
    delta = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="evt-delta",
        event_type="reasoning.delta",
        action_id="action-observe",
        phase="observe_propose",
        channel="reasoning",
        payload={"content": "先分析回答"},
    )

    assert started["sequence"] == 1
    assert delta["sequence"] == 2
    assert started["event_id"] == "evt-started"
    assert delta["channel"] == "reasoning"
    assert started["session_id"] == conversation["id"]
    assert started["turn_run_id"] == turn.id
    assert started["type"] == "action.started"
    assert started["schema_version"] == "turn-event-v1"
    assert started["occurred_at"]

    outbox = test_db.execute(
        "SELECT event_id, sequence, published_at FROM interview_event_outbox "
        "WHERE turn_id = ? ORDER BY sequence",
        (turn.id,),
    ).fetchall()
    assert [(row["event_id"], row["sequence"], row["published_at"]) for row in outbox] == [
        ("evt-started", 1, None),
        ("evt-delta", 2, None),
    ]


def test_append_turn_event_is_idempotent_and_replays_after_sequence(test_db):
    conversation = _conversation()
    turn = _turn(conversation["id"])
    payload = {"content": "同一事件重放"}

    first = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="evt-idempotent",
        event_type="assistant.delta",
        action_id="action-write",
        phase="write_response",
        channel="assistant",
        payload=payload,
    )
    replay = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="evt-idempotent",
        event_type="assistant.delta",
        action_id="action-write",
        phase="write_response",
        channel="assistant",
        payload=payload,
    )

    assert replay == first
    assert test_db.execute(
        "SELECT COUNT(*) FROM interview_events WHERE turn_id = ?", (turn.id,)
    ).fetchone()[0] == 1

    events = chat_service.get_turn_events(
        turn.id,
        user_id=1,
        conversation_id=conversation["id"],
        after_sequence=0,
    )
    assert len(events) == 1
    assert events[0]["event_id"] == "evt-idempotent"
    assert events[0]["payload"] == payload


def test_event_outbox_claim_and_ack_are_retryable_without_mutating_event(test_db):
    conversation = _conversation()
    turn = _turn(conversation["id"])
    event = chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="evt-outbox",
        event_type="turn.completed",
        action_id=None,
        phase="commit",
        channel="system",
        payload={"status": "completed"},
    )

    claimed = chat_service.claim_turn_event_outbox(limit=10, lease_seconds=10)
    assert [item["event_id"] for item in claimed] == [event["event_id"]]
    assert claimed[0]["attempts"] == 1
    assert chat_service.mark_turn_event_outbox_published(
        event["event_id"],
        success=False,
        error="temporary broker outage",
        retry_delay_seconds=1,
    )
    assert chat_service.mark_turn_event_outbox_published(event["event_id"], success=True)

    replay = chat_service.get_turn_events(
        turn.id, user_id=1, conversation_id=conversation["id"]
    )
    assert replay[0]["type"] == "turn.completed"
    row = test_db.execute(
        "SELECT status, attempts, published_at FROM interview_event_outbox WHERE event_id = ?",
        (event["event_id"],),
    ).fetchone()
    assert row["status"] == "published"
    assert row["attempts"] == 1
    assert row["published_at"] is not None

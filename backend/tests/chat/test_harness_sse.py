"""Canonical Harness 2.0 SSE replay endpoint."""

import json
from unittest.mock import AsyncMock
from unittest.mock import patch

from app.core.auth import get_current_user
from app.services import chat_service


def test_turn_events_endpoint_replays_ordered_envelopes(client, test_db):
    from app.asgi import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "sse-replay-1", "说明一下缓存击穿"
    )
    chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="sse-1",
        event_type="turn.started",
        action_id=None,
        phase="observe_propose",
        channel="system",
        payload={"status": "running"},
    )
    chat_service.append_turn_event(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        event_id="sse-2",
        event_type="assistant.delta",
        action_id="action-write",
        phase="write_response",
        channel="assistant",
        payload={"content": "先区分缓存击穿和雪崩"},
    )
    chat_service.cancel_chat_turn(turn.id, conversation["id"], 1)

    response = client.get(
        f"/api/chat/conversations/{conversation['id']}/turns/{turn.id}/events"
        "?after_sequence=1&follow=false"
    )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [payload["sequence"] for payload in payloads] == [2]
    assert payloads[0]["session_id"] == conversation["id"]
    assert payloads[0]["turn_run_id"] == turn.id
    assert response.text.splitlines()[0] == "id: sse-2"
    assert payloads[0]["type"] == "assistant.delta"
    assert payloads[0]["payload"]["content"] == "先区分缓存击穿和雪崩"

    app.dependency_overrides.clear()


def test_turn_events_accepts_standard_last_event_id(client, test_db):
    from app.asgi import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "sse-replay-last-id", "继续上一题"
    )
    for event_id, event_type in (("sse-last-1", "turn.started"), ("sse-last-2", "assistant.delta")):
        chat_service.append_turn_event(
            user_id=1,
            conversation_id=conversation["id"],
            turn_id=turn.id,
            event_id=event_id,
            event_type=event_type,
            action_id=None,
            phase="observe_propose",
            channel="system",
            payload={"event_id": event_id},
        )

    response = client.get(
        f"/api/chat/conversations/{conversation['id']}/turns/{turn.id}/events",
        headers={"Last-Event-ID": "sse-last-1"},
    )

    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [payload["event_id"] for payload in payloads] == ["sse-last-2"]
    app.dependency_overrides.clear()


def test_message_stream_persists_canonical_lifecycle_events(client, test_db):
    from app.asgi import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]

    async def fake_run_chat(**_kwargs):
        yield {"type": "thinking_start"}
        yield {"type": "thinking", "content": "先确认证据"}
        yield {"type": "thinking_done", "duration": 0.2, "content": "先确认证据"}
        yield {"type": "chunk", "content": "可以从缓存击穿说起。"}
        yield {"type": "done", "metadata": {"turn_intent": {"action": "ask"}}}

    with patch("app.agents.chat.graph.run_chat", fake_run_chat):
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={"content": "回答缓存击穿", "client_request_id": "sse-stream-1"},
        )

    assert response.status_code == 200
    turn_started = next(
        item for item in chat_service.get_messages(conversation["id"])
        if item["role"] == "user"
    )
    turn_id = turn_started["metadata"]["turn_id"]
    events = chat_service.get_turn_events(
        turn_id,
        user_id=1,
        conversation_id=conversation["id"],
    )
    event_types = [event["type"] for event in events]
    assert event_types[0] == "turn.started"
    assert "reasoning.delta" in event_types
    assert "assistant.delta" in event_types
    assert "assistant.completed" in event_types
    assert "turn.completed" in event_types
    assert all(event["turn_run_id"] == turn_id for event in events)

    app.dependency_overrides.clear()


def test_harness_2_turn_is_queued_and_returns_202(client, test_db):
    """Harness 2.0 HTTP only reserves durable state and enqueues ARQ."""
    from app.asgi import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]
    queued = AsyncMock()
    queued.return_value = type("Job", (), {"job_id": "arq-harness-1"})()

    with patch("app.routers.chat.enqueue_interview_turn_job", queued):
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={
                "content": "请开始模拟面试",
                "client_request_id": "harness-2-queue-1",
                "harness_version": "2.0",
            },
        )

    assert response.status_code == 202
    payload = response.json()["data"]
    assert payload["status"] == "queued"
    assert payload["harness_version"] == "2.0"
    turn_id = payload["turn_run_id"]
    queued.assert_awaited_once_with(turn_id)

    turn = chat_service.get_chat_turn(
        turn_id, conversation_id=conversation["id"], user_id=1
    )
    assert turn["status"] == "running"
    events = chat_service.get_turn_events(
        turn_id, user_id=1, conversation_id=conversation["id"]
    )
    assert [event["type"] for event in events] == ["turn.started", "turn.queued"]
    assert events[0]["sequence"] == 1
    assert events[1]["payload"]["dispatch_state"] == "pending_dispatch"

    app.dependency_overrides.clear()


def test_harness_2_cancel_is_cooperative_until_worker_finalizes(client, test_db):
    from app.asgi import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "harness-cancel-1", "停止本轮", harness_version="2.0"
    )

    response = client.post(
        f"/api/chat/conversations/{conversation['id']}/turns/{turn.id}/cancel",
        json={"reason": "用户点击停止"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "cancel_requested"
    snapshot = chat_service.get_chat_turn(
        turn.id, conversation_id=conversation["id"], user_id=1
    )
    assert snapshot["status"] == "running"
    events = chat_service.get_turn_events(
        turn.id, user_id=1, conversation_id=conversation["id"]
    )
    assert [event["type"] for event in events] == [
        "turn.started",
        "turn.queued",
        "turn.cancel_requested",
    ]

    app.dependency_overrides.clear()


def test_user_artifact_projection_never_returns_audit_prompt_or_cot(client, test_db):
    from app.asgi import app

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]
    turn = chat_service.reserve_chat_turn(
        conversation["id"], 1, "sse-artifacts", "查看运行轨迹", harness_version="2.0"
    )
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        artifact_type="provider_request",
        content={"prompt": "secret"},
        visibility="audit",
    )
    chat_service.append_harness_artifact(
        user_id=1,
        conversation_id=conversation["id"],
        turn_id=turn.id,
        artifact_type="user_note",
        content={"label": "可见步骤"},
        visibility="user",
    )

    response = client.get(
        f"/api/chat/conversations/{conversation['id']}/turns/{turn.id}/artifacts"
    )

    assert response.status_code == 200
    artifacts = response.json()["data"]
    assert [item["artifact_type"] for item in artifacts] == ["user_note"]
    assert artifacts[0]["content"] == {"label": "可见步骤"}
    assert "secret" not in response.text
    app.dependency_overrides.clear()

from unittest.mock import patch

import pytest

from app.core.auth import get_current_user
from app.services import chat_service


@pytest.mark.asyncio
async def test_harness_worker_projects_events_and_commits_turn(client, test_db):
    from app.asgi import app
    from app.services.harness_turn_worker import run_harness_turn

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "user1",
        "is_admin": 0,
    }
    conversation = client.post(
        "/api/chat/conversations", json={"mode": "free_practice"}
    ).json()["data"]
    turn = chat_service.reserve_chat_turn(
        conversation["id"],
        1,
        "worker-test-1",
        "解释一下缓存击穿",
        harness_version="2.0",
    )

    async def fake_run_chat(**_kwargs):
        yield {"type": "thinking_start"}
        yield {"type": "thinking", "content": "先定位证据缺口"}
        yield {"type": "thinking_done", "duration": 0.2, "content": "先定位证据缺口"}
        yield {"type": "chunk", "content": "可以从缓存击穿与缓存雪崩的区别开始。"}
        yield {"type": "done", "metadata": {"depth": 1}}

    with patch("app.agents.chat.graph.run_chat", fake_run_chat):
        result = await run_harness_turn(turn.id, worker_id="worker-test")

    assert result["status"] == "completed"
    snapshot = chat_service.get_chat_turn(
        turn.id, conversation_id=conversation["id"], user_id=1
    )
    assert snapshot["status"] == "completed"
    assert snapshot["assistant_content"].startswith("可以从缓存击穿")
    events = chat_service.get_turn_events(
        turn.id, user_id=1, conversation_id=conversation["id"]
    )
    assert [event["type"] for event in events] == [
        "turn.started",
        "turn.queued",
        "reasoning.started",
        "reasoning.delta",
        "reasoning.completed",
        "assistant.started",
        "assistant.delta",
        "commit.started",
        "assistant.completed",
        "commit.completed",
        "turn.completed",
    ]
    assert [event["sequence"] for event in events] == list(range(1, 12))
    ledger = chat_service.get_interview_ledger(conversation["id"], user_id=1)
    assert ledger["ledger_version"] == 2
    app.dependency_overrides.clear()

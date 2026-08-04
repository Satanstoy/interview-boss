"""Turn lifecycle tests for concurrent and cancellable chat requests."""

import pytest


def _conversation():
    from app.services import chat_service

    return chat_service.create_conversation(user_id=1, mode="free_practice")


class TestChatTurnLifecycle:
    def test_same_request_id_with_different_payload_is_idempotency_conflict(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "第一条消息"
        )

        with pytest.raises(chat_service.TurnIdempotencyConflict):
            chat_service.reserve_chat_turn(
                conversation["id"], 1, "req-1", "另一条消息"
            )

        messages = chat_service.get_messages(conversation["id"])
        assert [message["content"] for message in messages] == ["第一条消息"]

    def test_legacy_empty_fingerprint_is_reconciled_from_original_user_message(self, test_db):
        from app.db.connection import get_db_connection
        from app.services import chat_service

        conversation = _conversation()
        first = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-legacy", "原始消息"
        )
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE chat_turns SET request_fingerprint = '' WHERE id = ?",
                (first.id,),
            )
            conn.commit()

        replay = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-legacy", "原始消息"
        )
        assert replay.created is False
        assert replay.request_fingerprint

        with pytest.raises(chat_service.TurnIdempotencyConflict):
            chat_service.reserve_chat_turn(
                conversation["id"], 1, "req-legacy", "篡改消息"
            )

    def test_turn_request_fingerprint_changes_with_model_and_revision(self):
        from app.services.chat_service import build_turn_request_fingerprint

        base = build_turn_request_fingerprint("回答 Redis", model="model-a")
        same = build_turn_request_fingerprint("回答 Redis", model="model-a")
        different_model = build_turn_request_fingerprint("回答 Redis", model="model-b")
        different_revision = build_turn_request_fingerprint(
            "回答 Redis", model="model-a", revision_of_message_id=7
        )

        assert base == same
        assert base != different_model
        assert base != different_revision

    def test_reserve_turn_is_idempotent_without_duplicate_user_message(self, test_db):
        from app.services import chat_service

        conversation = _conversation()

        first = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "你好"
        )
        second = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "你好"
        )

        assert second.id == first.id
        assert second.fence == first.fence
        messages = chat_service.get_messages(conversation["id"])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "你好"

    def test_second_running_turn_is_rejected(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        chat_service.reserve_chat_turn(conversation["id"], 1, "req-1", "第一条")

        with pytest.raises(chat_service.TurnInProgress):
            chat_service.reserve_chat_turn(
                conversation["id"], 1, "req-2", "第二条"
            )

    def test_cancelled_turn_cannot_finalize_assistant_message(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        turn = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "你好"
        )

        cancelled = chat_service.cancel_chat_turn(
            turn.id, conversation["id"], 1, "client_stop"
        )

        assert cancelled.status == "cancelled"
        with pytest.raises(chat_service.TurnCancelled):
            chat_service.finalize_chat_turn(
                turn.id,
                turn.fence,
                conversation["id"],
                1,
                "不应落库",
                {},
            )

        messages = chat_service.get_messages(conversation["id"])
        assert [message["role"] for message in messages] == ["user"]

    def test_finalize_turn_is_atomic_and_cannot_run_twice(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        turn = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "你好"
        )

        assistant_id = chat_service.finalize_chat_turn(
            turn.id,
            turn.fence,
            conversation["id"],
            1,
            "你好，我是面试官。",
            {"turn_id": turn.id},
        )

        assert assistant_id is not None
        assert chat_service.get_chat_turn(turn.id)["status"] == "completed"
        with pytest.raises(chat_service.TurnCancelled):
            chat_service.finalize_chat_turn(
                turn.id,
                turn.fence,
                conversation["id"],
                1,
                "重复回复",
                {},
            )

        messages = chat_service.get_messages(conversation["id"])
        assert [message["role"] for message in messages] == ["user", "assistant"]

    def test_revision_reuses_original_user_message_and_links_new_assistant(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        original_turn = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-original", "请解释 Redis 一致性"
        )
        original_assistant_id = chat_service.finalize_chat_turn(
            original_turn.id,
            original_turn.fence,
            conversation["id"],
            1,
            "原始追问",
            {"turn_id": original_turn.id},
        )

        revision, original_user_content = chat_service.reserve_chat_revision(
            conversation["id"],
            1,
            original_assistant_id,
            "req-revision",
            model="model-a",
        )

        assert original_user_content == "请解释 Redis 一致性"
        assert revision.revision_of_message_id == original_assistant_id
        assert revision.user_message_id == original_turn.user_message_id
        messages = chat_service.get_messages(conversation["id"])
        assert [message["role"] for message in messages] == ["user", "assistant"]

        chat_service.finalize_chat_turn(
            revision.id,
            revision.fence,
            conversation["id"],
            1,
            "新的追问",
            {"turn_id": revision.id},
        )

        messages = chat_service.get_messages(conversation["id"])
        assert [message["role"] for message in messages] == [
            "user",
            "assistant",
            "assistant",
        ]
        assert messages[-1]["metadata"]["revision_of_message_id"] == original_assistant_id
        assert messages[-1]["metadata"]["revision_number"] == 1

    def test_revision_rejects_original_user_message_as_target(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        original_turn = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-original", "原始候选人回答"
        )

        with pytest.raises(chat_service.TurnNotFound):
            chat_service.reserve_chat_revision(
                conversation["id"],
                1,
                original_turn.user_message_id,
                "req-revision",
            )

    def test_turn_identity_is_required_for_active_guard(self, test_db):
        from app.services import chat_service

        conversation = _conversation()
        turn = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "你好"
        )

        with pytest.raises(chat_service.TurnNotFound):
            chat_service.assert_chat_turn_active(
                turn.id,
                turn.fence,
                conversation["id"],
                2,
            )


class TestChatPipelineGuards:
    @staticmethod
    def _state(turn):
        return {
            "conversation_id": turn.conversation_id,
            "user_id": turn.user_id,
            "turn_id": turn.id,
            "turn_fence": turn.fence,
            "active_skills": ["interview-rhythm"],
            "session_id": turn.conversation_id,
        }

    async def test_cancelled_turn_blocks_pipeline_side_effect_boundaries(self, test_db):
        from app.agents.chat import pipeline
        from app.services import chat_service
        from unittest.mock import AsyncMock, patch

        conversation = _conversation()
        turn = chat_service.reserve_chat_turn(
            conversation["id"], 1, "req-1", "请深入解释 Redis 缓存一致性"
        )
        chat_service.cancel_chat_turn(turn.id, conversation["id"], 1)
        state = self._state(turn)

        with patch.object(
            chat_service, "update_conversation_metadata"
        ) as update_metadata, patch(
            "app.db.operations.record_asked_question"
        ) as record_question, patch.object(
            pipeline, "save_mcp_session_async", new_callable=AsyncMock
        ) as save_session:
            with pytest.raises(chat_service.TurnCancelled):
                pipeline._record_asked_question_if_any(
                    state, {"selected_question": {"id": 7}}
                )
            with pytest.raises(chat_service.TurnCancelled):
                await pipeline._persist_active_skills(state)
            with pytest.raises(chat_service.TurnCancelled):
                await pipeline._persist_mcp_session(state)

        update_metadata.assert_not_called()
        record_question.assert_not_called()
        save_session.assert_not_awaited()


class TestChatTurnRouter:
    @staticmethod
    def _use_test_database(monkeypatch, test_db):
        from app.services import chat_service

        monkeypatch.setattr(chat_service, "get_db_connection", lambda: test_db)
        monkeypatch.setattr(
            "app.routers.chat._current_position_name",
            lambda _user_id: "",
        )

    @staticmethod
    def _auth(user_id=1):
        from app.asgi import app
        from app.core.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": user_id,
            "username": f"user{user_id}",
            "is_admin": 0,
        }
        return app

    @staticmethod
    def _create_router_conversation(client):
        response = client.post(
            "/api/chat/conversations",
            json={"mode": "free_practice"},
        )
        assert response.status_code == 200
        return response.json()["data"]["id"]

    def test_send_rejects_a_different_request_while_turn_is_running(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service
        from unittest.mock import patch

        async def empty_run_chat(**_kwargs):
            yield {"type": "done", "metadata": {}}

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            chat_service.reserve_chat_turn(conversation_id, 1, "req-1", "第一条")
            with patch("app.agents.chat.graph.run_chat", empty_run_chat):
                response = client.post(
                    f"/api/chat/conversations/{conversation_id}/messages",
                    json={"content": "第二条", "client_request_id": "req-2"},
                )
            assert response.status_code == 409
            assert response.json()["detail"] == "TURN_IN_PROGRESS"
        finally:
            app.dependency_overrides.clear()

    def test_status_endpoint_returns_owned_turn_for_reconciliation(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            turn = chat_service.reserve_chat_turn(
                conversation_id, 1, "req-status", "第一条"
            )
            chat_service.finalize_chat_turn(
                turn.id,
                turn.fence,
                conversation_id,
                1,
                "已完成回答",
                {"trace": "status-test"},
            )

            response = client.get(
                f"/api/chat/conversations/{conversation_id}/turns/{turn.id}"
            )

            assert response.status_code == 200
            data = response.json()["data"]
            assert data["status"] == "completed"
            assert data["request_fingerprint"]
            assert data["assistant_content"] == "已完成回答"
            assert data["assistant_metadata"]["trace"] == "status-test"
            assert data["assistant_metadata"]["turn_id"] == turn.id
        finally:
            app.dependency_overrides.clear()

    def test_same_completed_request_replays_sse_without_new_user_message(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service
        from unittest.mock import patch

        async def fake_run_chat(**_kwargs):
            yield {"type": "chunk", "content": "可重放回答"}
            yield {"type": "done", "metadata": {"trace": "replay"}}

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            with patch("app.agents.chat.graph.run_chat", fake_run_chat):
                first = client.post(
                    f"/api/chat/conversations/{conversation_id}/messages",
                    json={"content": "原始请求", "client_request_id": "req-replay"},
                )
                replay = client.post(
                    f"/api/chat/conversations/{conversation_id}/messages",
                    json={"content": "原始请求", "client_request_id": "req-replay"},
                )

            assert first.status_code == 200
            assert replay.status_code == 200
            assert "text/event-stream" in replay.headers["content-type"]
            assert "可重放回答" in replay.text
            messages = chat_service.get_messages(conversation_id)
            assert sum(message["role"] == "user" for message in messages) == 1
            assert sum(message["content"] == "可重放回答" for message in messages) == 1
        finally:
            app.dependency_overrides.clear()

    def test_regenerate_request_rejects_extra_fields(self):
        from pydantic import ValidationError
        from app.routers.chat import RegenerateMessageRequest

        with pytest.raises(ValidationError):
            RegenerateMessageRequest.model_validate(
                {"client_request_id": "req-1", "unexpected": "value"}
            )

    def test_status_endpoint_rejects_other_users_turn(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service

        self._use_test_database(monkeypatch, test_db)
        app = self._auth(user_id=1)
        try:
            conversation_id = self._create_router_conversation(client)
            turn = chat_service.reserve_chat_turn(
                conversation_id, 1, "req-private", "私有回答"
            )
            app.dependency_overrides.clear()
            app = self._auth(user_id=2)

            response = client.get(
                f"/api/chat/conversations/{conversation_id}/turns/{turn.id}"
            )

            assert response.status_code == 404
            assert response.json()["detail"] == "TURN_NOT_FOUND"
        finally:
            app.dependency_overrides.clear()

    def test_send_returns_idempotency_conflict_for_reused_request_id(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            chat_service.reserve_chat_turn(
                conversation_id, 1, "req-conflict", "原始请求"
            )

            response = client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={"content": "被篡改的请求", "client_request_id": "req-conflict"},
            )

            assert response.status_code == 409
            assert response.json()["detail"]["code"] == "TURN_IDEMPOTENCY_CONFLICT"
        finally:
            app.dependency_overrides.clear()

    def test_regenerate_creates_assistant_revision_without_new_user_message(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service
        from unittest.mock import patch

        async def fake_run_chat(**kwargs):
            assert kwargs["user_message"] == "原始候选人回答"
            yield {"type": "chunk", "content": "新的面试官追问"}
            yield {"type": "done", "metadata": {"trace": "revision"}}

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            original_turn = chat_service.reserve_chat_turn(
                conversation_id, 1, "req-original", "原始候选人回答"
            )
            original_assistant_id = chat_service.finalize_chat_turn(
                original_turn.id,
                original_turn.fence,
                conversation_id,
                1,
                "原始面试官追问",
                {},
            )

            with patch("app.agents.chat.graph.run_chat", fake_run_chat):
                response = client.post(
                    f"/api/chat/conversations/{conversation_id}/messages/"
                    f"{original_assistant_id}/regenerate",
                    json={"client_request_id": "req-revision"},
                )

            assert response.status_code == 200
            messages = chat_service.get_messages(conversation_id)
            assert sum(message["role"] == "user" for message in messages) == 1
            assert messages[-1]["content"] == "新的面试官追问"
            assert messages[-1]["metadata"]["revision_of_message_id"] == original_assistant_id
        finally:
            app.dependency_overrides.clear()

    def test_cancel_endpoint_is_idempotent_for_owned_turn(
        self, client, test_db, monkeypatch
    ):
        from app.services import chat_service

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            turn = chat_service.reserve_chat_turn(
                conversation_id, 1, "req-1", "第一条"
            )
            first = client.post(
                f"/api/chat/conversations/{conversation_id}/turns/{turn.id}/cancel",
                json={"reason": "点击停止"},
            )
            second = client.post(
                f"/api/chat/conversations/{conversation_id}/turns/{turn.id}/cancel",
                json={"reason": "重复点击"},
            )
            assert first.status_code == 200
            assert first.json()["data"]["status"] == "cancelled"
            assert second.status_code == 200
            assert second.json()["data"]["status"] == "cancelled"
        finally:
            app.dependency_overrides.clear()

    def test_send_stream_finalizes_the_reserved_turn(self, client, test_db, monkeypatch):
        from app.services import chat_service
        from unittest.mock import patch

        async def fake_run_chat(**kwargs):
            assert kwargs["turn_id"]
            assert kwargs["turn_fence"] == 1
            yield {"type": "chunk", "content": "回答"}
            yield {"type": "done", "metadata": {"trace": "test"}}

        async def fake_generate_title(*_args, **_kwargs):
            return "测试对话"

        self._use_test_database(monkeypatch, test_db)
        app = self._auth()
        try:
            conversation_id = self._create_router_conversation(client)
            with patch("app.agents.chat.graph.run_chat", fake_run_chat), patch(
                "app.services.title_service.generate_title",
                fake_generate_title,
            ):
                response = client.post(
                    f"/api/chat/conversations/{conversation_id}/messages",
                    json={"content": "第一条", "client_request_id": "req-1"},
                )

            assert response.status_code == 200
            assert '"type": "turn_started"' in response.text
            assert '"type": "done"' in response.text
            turns = test_db.execute(
                "SELECT status FROM chat_turns WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
            assert [row["status"] for row in turns] == ["completed"]
            messages = chat_service.get_messages(conversation_id)
            assert [(message["role"], message["content"]) for message in messages] == [
                ("assistant", messages[0]["content"]),
                ("user", "第一条"),
                ("assistant", "回答"),
            ]
        finally:
            app.dependency_overrides.clear()

    def test_other_user_cannot_cancel_turn(self, client, test_db, monkeypatch):
        from app.services import chat_service

        self._use_test_database(monkeypatch, test_db)
        test_db.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (2, 'user2', 'hash')"
        )
        test_db.commit()
        app = self._auth(user_id=2)
        try:
            # The conversation belongs to user 1, while the caller is user 2.
            app.dependency_overrides.clear()
            self._auth(user_id=1)
            conversation_id = self._create_router_conversation(client)
            turn = chat_service.reserve_chat_turn(
                conversation_id, 1, "req-1", "第一条"
            )
            app.dependency_overrides.clear()
            self._auth(user_id=2)
            response = client.post(
                f"/api/chat/conversations/{conversation_id}/turns/{turn.id}/cancel",
                json={"reason": "越权取消"},
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

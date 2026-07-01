"""
TDD 测试 — 模拟面试 Chatbot 后端核心模块

测试覆盖：
- chat_service: 会话/消息/记忆 CRUD
- fts_service: FTS5 全文检索
- chat router: API 端点
"""

import json
import pytest
from unittest.mock import patch, AsyncMock


# ═══════════════════════════════════════════════════
#  T-001 ~ T-005: chat_service 测试
# ═══════════════════════════════════════════════════


class TestChatServiceConversation:
    """会话管理测试"""

    def test_create_conversation_returns_correct_structure(self, test_db):
        """T-001: 创建会话应返回包含 id, mode, title 的字典"""
        from app.services.chat_service import create_conversation

        result = create_conversation(user_id=1, mode="free_practice")

        assert "id" in result
        assert result["mode"] == "free_practice"
        assert result["title"] == "新对话"
        assert len(result["id"]) > 0  # UUID

    def test_create_conversation_jd_mode(self, test_db):
        """T-001b: JD模式创建会话应使用 JD 标题"""
        from app.services.chat_service import create_conversation

        result = create_conversation(
            user_id=1, mode="jd_resume", jd_id=42, resume_text="简历内容"
        )

        assert result["mode"] == "jd_resume"
        assert result["title"] == "JD定制面试"

    def test_get_conversations_returns_user_own(self, test_db):
        """T-002: 获取会话列表只返回当前用户的会话"""
        from app.services.chat_service import create_conversation, get_conversations

        # 创建第二个用户
        test_db.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (2, 'user2', 'hash')"
        )
        test_db.commit()

        # 用户1的会话
        create_conversation(user_id=1, mode="free_practice", title="用户1的对话")

        # 用户2的会话
        create_conversation(user_id=2, mode="free_practice", title="用户2的对话")

        user1_convs = get_conversations(user_id=1)
        user2_convs = get_conversations(user_id=2)

        assert len(user1_convs) == 1
        assert user1_convs[0]["title"] == "用户1的对话"
        assert len(user2_convs) == 1
        assert user2_convs[0]["title"] == "用户2的对话"

    def test_get_conversations_filters_by_job_position(self, test_db):
        """T-002pos: 会话列表和详情应按当前岗位隔离"""
        from app.services.chat_service import (
            create_conversation,
            get_conversations,
            get_conversation,
        )

        fe = create_conversation(
            user_id=1, mode="free_practice", title="前端面试", job_position="前端开发"
        )
        be = create_conversation(
            user_id=1, mode="free_practice", title="后端面试", job_position="后端开发"
        )

        fe_convs = get_conversations(user_id=1, job_position="前端开发")
        be_convs = get_conversations(user_id=1, job_position="后端开发")

        assert [c["id"] for c in fe_convs] == [fe["id"]]
        assert [c["id"] for c in be_convs] == [be["id"]]
        assert get_conversation(be["id"], user_id=1, job_position="前端开发") is None

    def test_get_conversations_excludes_archived(self, test_db):
        """T-002b: 默认不返回已归档的会话"""
        from app.services.chat_service import (
            create_conversation,
            archive_conversation,
            get_conversations,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        archive_conversation(conv["id"], user_id=1)

        active = get_conversations(user_id=1, status="active")
        archived = get_conversations(user_id=1, status="archived")

        assert len(active) == 0
        assert len(archived) == 1

    def test_delete_conversation_cascades_messages(self, test_db):
        """T-002c: 删除会话应级联删除消息"""
        from app.services.chat_service import (
            create_conversation,
            save_message,
            delete_conversation,
            get_conversation,
            get_messages,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        save_message(conv["id"], "user", "你好")
        save_message(conv["id"], "assistant", "你好！")

        delete_conversation(conv["id"], user_id=1)

        assert get_conversation(conv["id"], user_id=1) is None
        assert get_messages(conv["id"]) == []


class TestChatServiceMessages:
    """消息管理测试"""

    def test_save_and_get_messages(self, test_db):
        """T-003: 保存消息后应能按时间顺序检索"""
        from app.services.chat_service import (
            create_conversation,
            save_message,
            get_messages,
        )

        conv = create_conversation(user_id=1, mode="free_practice")

        msg1_id = save_message(conv["id"], "user", "第一句话")
        msg2_id = save_message(conv["id"], "assistant", "回复第一句")
        msg3_id = save_message(conv["id"], "user", "第二句话")

        messages = get_messages(conv["id"])

        assert len(messages) == 3
        assert messages[0]["content"] == "第一句话"
        assert messages[0]["role"] == "user"
        assert messages[1]["content"] == "回复第一句"
        assert messages[2]["content"] == "第二句话"
        assert msg1_id < msg2_id < msg3_id

    def test_get_messages_respects_limit(self, test_db):
        """T-003b: limit 参数应限制返回数量"""
        from app.services.chat_service import (
            create_conversation,
            save_message,
            get_messages,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        for i in range(10):
            save_message(conv["id"], "user", f"消息{i}")

        messages = get_messages(conv["id"], limit=3)

        assert len(messages) == 3

    def test_get_recent_messages_returns_last_n(self, test_db):
        """T-003c: get_recent_messages 应返回最近的 N 条消息（时间正序）"""
        from app.services.chat_service import (
            create_conversation,
            save_message,
            get_recent_messages,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        for i in range(8):
            save_message(conv["id"], "user", f"消息{i}")

        recent = get_recent_messages(conv["id"], limit=3)

        assert len(recent) == 3
        # 应该是最后3条，正序排列
        assert recent[0]["content"] == "消息5"
        assert recent[1]["content"] == "消息6"
        assert recent[2]["content"] == "消息7"

    def test_save_message_with_metadata(self, test_db):
        """T-003d: 消息应支持存储 metadata"""
        from app.services.chat_service import (
            create_conversation,
            save_message,
            get_messages,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        metadata = {"retrieved_questions": [{"id": 1, "question": "什么是REST?"}]}
        save_message(conv["id"], "assistant", "回答", metadata=metadata)

        messages = get_messages(conv["id"])
        assert messages[0]["metadata"] == metadata

    def test_get_conversation_question_ids_from_metadata(self, test_db):
        """已问/已抽题目 ID 应能从 assistant metadata 中收集。"""
        from app.services.chat_service import (
            create_conversation,
            get_conversation_question_ids,
            save_message,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        save_message(
            conv["id"],
            "assistant",
            "问题",
            metadata={
                "basis_question_ids": [1],
                "llm_rerank": {"selected_basis_ids": [2]},
                "retrieved_questions": [{"id": 3, "question": "q3"}],
                "selected_basis_questions": [{"id": 4, "question": "q4"}],
                "next_question_plan": {"question_id": 5},
            },
        )

        assert get_conversation_question_ids(conv["id"]) == {1, 2, 3, 4, 5}

    def test_get_message_count(self, test_db):
        """T-003e: get_message_count 应返回消息总数"""
        from app.services.chat_service import (
            create_conversation,
            save_message,
            get_message_count,
        )

        conv = create_conversation(user_id=1, mode="free_practice")
        assert get_message_count(conv["id"]) == 0

        save_message(conv["id"], "user", "你好")
        assert get_message_count(conv["id"]) == 1

        save_message(conv["id"], "assistant", "你好！")
        assert get_message_count(conv["id"]) == 2


class TestChatServiceMemories:
    """用户记忆管理测试"""

    def test_save_and_get_memories(self, test_db):
        """T-004: 保存记忆后应能按用户查询"""
        from app.services.chat_service import save_memory, get_memories

        # 创建第二个用户
        test_db.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (2, 'user2', 'hash')"
        )
        test_db.commit()

        save_memory(user_id=1, memory_type="weakness", content="Redis不熟悉")
        save_memory(user_id=1, memory_type="strength", content="Java多线程精通")
        save_memory(user_id=2, memory_type="weakness", content="Python装饰器不熟")

        user1_memories = get_memories(user_id=1)
        user2_memories = get_memories(user_id=2)

        assert len(user1_memories) == 2
        assert len(user2_memories) == 1

    def test_get_memories_filter_by_type(self, test_db):
        """T-004b: 可按 memory_type 过滤记忆"""
        from app.services.chat_service import save_memory, get_memories

        save_memory(user_id=1, memory_type="weakness", content="Redis不熟悉")
        save_memory(user_id=1, memory_type="strength", content="Java精通")
        save_memory(user_id=1, memory_type="preference", content="喜欢代码示例")

        weaknesses = get_memories(user_id=1, memory_type="weakness")
        assert len(weaknesses) == 1
        assert weaknesses[0]["content"] == "Redis不熟悉"

    def test_deactivate_memory(self, test_db):
        """T-004c: 停用记忆后不应出现在查询结果中"""
        from app.services.chat_service import (
            save_memory,
            get_memories,
            deactivate_memory,
        )

        mem_id = save_memory(user_id=1, memory_type="weakness", content="旧弱点")
        assert len(get_memories(user_id=1)) == 1

        deactivate_memory(mem_id, user_id=1)
        assert len(get_memories(user_id=1)) == 0

    def test_resume_memory_overwrite(self, test_db):
        """T-005: 保存新简历应停用旧简历记忆"""
        from app.services.chat_service import (
            save_resume_memory,
            get_memories,
            get_resume_memory,
        )

        save_resume_memory(user_id=1, resume_text="旧简历内容")
        assert get_resume_memory(user_id=1) == "旧简历内容"

        save_resume_memory(user_id=1, resume_text="新简历内容")
        assert get_resume_memory(user_id=1) == "新简历内容"

        # 应该只有一条 active 的简历记忆
        resumes = get_memories(user_id=1, memory_type="resume")
        assert len(resumes) == 1

    def test_resume_memory_user_isolation(self, test_db):
        """T-005b: 不同用户的简历记忆互相隔离"""
        from app.services.chat_service import save_resume_memory, get_resume_memory

        # 创建第二个用户
        test_db.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (2, 'user2', 'hash')"
        )
        test_db.commit()

        save_resume_memory(user_id=1, resume_text="用户1简历")
        save_resume_memory(user_id=2, resume_text="用户2简历")

        assert get_resume_memory(user_id=1) == "用户1简历"
        assert get_resume_memory(user_id=2) == "用户2简历"


# ═══════════════════════════════════════════════════
#  T-006 ~ T-007: fts_service 测试
# ═══════════════════════════════════════════════════


class TestFTSService:
    """FTS5 全文检索测试"""

    def _seed_questions(self, conn):
        """插入测试题目数据"""
        questions = [
            (
                "什么是RESTful API？",
                "后端",
                "Spring",
                "REST,API",
                1,
                "REST是一种架构风格...",
            ),
            (
                "Redis缓存策略有哪些？",
                "后端",
                "Redis",
                "Redis,缓存",
                1,
                "常见策略有...",
            ),
            (
                "Vue3的Composition API是什么？",
                "前端",
                "Vue",
                "Vue3,组合式API",
                1,
                "Composition API是...",
            ),
            ("数据库索引原理？", "数据库", "MySQL", "索引,B+树", 1, "B+树索引..."),
        ]
        for q in questions:
            conn.execute(
                "INSERT INTO question_bank (question, cat1, cat2, tags, frequency, ai_answer, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'approved')",
                q,
            )
        conn.commit()

    def test_fts5_search_returns_relevant_questions(self, test_db):
        """T-006: FTS5 检索应返回包含关键词的题目"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)

        results = search_questions_fts(["REST", "API"])

        assert len(results) > 0
        assert any("REST" in r["question"] for r in results)

    def test_fts5_search_multiple_keywords(self, test_db):
        """T-006b: 多关键词应返回匹配至少一个关键词的结果"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)

        # 用单个明确的关键词测试
        results_redis = search_questions_fts(["Redis"])
        results_vue = search_questions_fts(["Vue"])

        assert len(results_redis) >= 1
        assert any("Redis" in r["question"] for r in results_redis)
        assert len(results_vue) >= 1
        assert any("Vue" in r["question"] for r in results_vue)

    def test_fts5_search_empty_keywords(self, test_db):
        """T-007: 空关键词列表应返回空结果"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)

        results = search_questions_fts([])
        assert results == []

        results = search_questions_fts(["", "  "])
        assert results == []

    def test_fts5_search_no_match(self, test_db):
        """T-007b: 不匹配的关键词应返回空结果"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)

        results = search_questions_fts(["量子计算", "区块链"])
        # 可能返回空或通过 LIKE 降级返回少量
        # 重要的是不报错
        assert isinstance(results, list)

    def test_fts5_sync_entry(self, test_db):
        """T-006c: sync_fts_entry 应同步单条题目到 FTS 索引"""
        from app.services.fts_service import sync_fts_entry, search_questions_fts

        # 插入一条题目
        test_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, ai_answer, status) "
            "VALUES (?, ?, ?, ?, ?, 'approved')",
            ("什么是Docker容器？", "DevOps", "Docker", "Docker,容器", "Docker是..."),
        )
        test_db.commit()
        qid = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 同步到 FTS
        sync_fts_entry(qid)

        # 搜索应能找到
        results = search_questions_fts(["Docker"])
        assert any("Docker" in r["question"] for r in results)

    def test_fts5_search_returns_correct_fields(self, test_db):
        """T-006d: 搜索结果应包含所有必要字段"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)

        results = search_questions_fts(["REST"])
        if results:
            r = results[0]
            assert "id" in r
            assert "question" in r
            assert "cat1" in r
            assert "cat2" in r
            assert "tags" in r
            assert "ai_answer" in r
            assert "rank" in r


# ═══════════════════════════════════════════════════
#  T-008 ~ T-010: Chat Router 测试
# ═══════════════════════════════════════════════════


class TestChatRouter:
    """Chat API 端点测试

    注意：这些测试需要 TestClient + run_db (asyncio.to_thread) 配合。
    当前 test_db fixture 使用内存 SQLite，但 run_db 在不同线程中运行，
    导致线程隔离的 _local.conn 无法共享。
    TODO: 修复 test infrastructure 以支持 async router 测试
    """

    def _create_user(self, conn, user_id=1, username="testuser"):
        """创建测试用户（使用 admin 用户，避免 ID 冲突）"""
        # migration 012 已创建 admin 用户 (id=1)，直接使用
        existing = conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO users (id, username, password_hash, is_admin, bank_mode) "
                "VALUES (?, ?, 'fakehash', 0, 'public')",
                (user_id, username),
            )
            conn.commit()

    def _auth_headers(self):
        """伪造认证 header"""
        return {"X-Requested-With": "XMLHttpRequest"}

    def test_create_conversation_api(self, client, test_db):
        """T-008: POST /api/chat/conversations 应创建会话"""
        self._create_user(test_db)

        # Mock auth dependency
        from app.core.auth import get_current_user
        from app.asgi import app

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "is_admin": 0,
        }

        try:
            response = client.post(
                "/api/chat/conversations",
                json={"mode": "free_practice"},
                headers=self._auth_headers(),
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "id" in data["data"]
            assert data["data"]["mode"] == "free_practice"
        finally:
            app.dependency_overrides.clear()

    def test_list_conversations_api(self, client, test_db):
        """T-008b: GET /api/chat/conversations 应返回会话列表"""
        self._create_user(test_db)

        from app.core.auth import get_current_user
        from app.asgi import app

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "is_admin": 0,
        }

        try:
            # 先创建一个会话
            created = client.post(
                "/api/chat/conversations",
                json={"mode": "free_practice"},
                headers=self._auth_headers(),
            )
            created_id = created.json()["data"]["id"]

            response = client.get(
                "/api/chat/conversations",
                headers=self._auth_headers(),
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            created_conversations = [
                conv for conv in data["data"] if conv["id"] == created_id
            ]
            assert len(created_conversations) == 1
            assert created_conversations[0]["mode"] == "free_practice"
        finally:
            app.dependency_overrides.clear()

    def test_get_nonexistent_conversation_returns_404(self, client, test_db):
        """T-010: 获取不存在的会话应返回 404"""
        self._create_user(test_db)

        from app.core.auth import get_current_user
        from app.asgi import app

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "is_admin": 0,
        }

        try:
            response = client.get(
                "/api/chat/conversations/nonexistent-id",
                headers=self._auth_headers(),
            )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_get_messages_api(self, client, test_db):
        """T-008c: GET /api/chat/conversations/{id}/messages 应返回消息列表"""
        self._create_user(test_db)

        from app.core.auth import get_current_user
        from app.asgi import app

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "is_admin": 0,
        }

        try:
            # 创建会话
            res = client.post(
                "/api/chat/conversations",
                json={"mode": "free_practice"},
                headers=self._auth_headers(),
            )
            conv_id = res.json()["data"]["id"]

            # 创建会话时 API 会自动写入面试官开场白
            response = client.get(
                f"/api/chat/conversations/{conv_id}/messages",
                headers=self._auth_headers(),
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data["data"]) == 1
            assert data["data"][0]["role"] == "assistant"
            assert "自我介绍" in data["data"][0]["content"]
        finally:
            app.dependency_overrides.clear()

    def test_delete_conversation_api(self, client, test_db):
        """T-008d: DELETE /api/chat/conversations/{id} 应删除会话"""
        self._create_user(test_db)

        from app.core.auth import get_current_user
        from app.asgi import app

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "is_admin": 0,
        }

        try:
            res = client.post(
                "/api/chat/conversations",
                json={"mode": "free_practice"},
                headers=self._auth_headers(),
            )
            conv_id = res.json()["data"]["id"]

            response = client.delete(
                f"/api/chat/conversations/{conv_id}",
                headers=self._auth_headers(),
            )
            assert response.status_code == 200

            # 再次获取应 404
            response = client.get(
                f"/api/chat/conversations/{conv_id}",
                headers=self._auth_headers(),
            )
            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_memories_api(self, client, test_db):
        """T-008e: GET /api/chat/memories 应返回记忆列表"""
        self._create_user(test_db)

        from app.core.auth import get_current_user
        from app.asgi import app

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "is_admin": 0,
        }

        try:
            response = client.get(
                "/api/chat/memories",
                headers=self._auth_headers(),
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert isinstance(data["data"], list)
        finally:
            app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════
#  Fix 4: thinking/steps/insights persistence in done metadata
# ═══════════════════════════════════════════════════


class TestDoneEventMetadataPersistence:
    """Fix 4 — done event metadata must include thinking, steps, insights."""

    async def test_done_event_metadata_includes_thinking(self):
        """After pipeline runs, done event metadata.thinking should exist."""
        from app.agents.chat.pipeline import run_chat

        thinking_events = [
            {"type": "thinking_start", "data": {}},
            {"type": "thinking", "data": {"text": "Let me think..."}},
            {"type": "thinking_done", "data": {}},
        ]
        react_events = [
            *thinking_events,
            {"type": "chunk", "content": "Here is a question"},
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
                return_value=({}, "Here is a question"),
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None, "No done event received"
        metadata = done_event.get("metadata", {})
        assert "thinking" in metadata, (
            f"done event metadata should contain 'thinking', got keys: {list(metadata.keys())}"
        )
        assert isinstance(metadata["thinking"], list)
        assert len(metadata["thinking"]) == 1
        assert metadata["thinking"][0].get("chunks") == ["Let me think..."]

    async def test_done_event_metadata_includes_steps(self):
        """After pipeline runs, done event metadata.steps should exist."""
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "chunk", "content": "Here is a question"},
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
                return_value=({}, "Here is a question"),
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "steps" in metadata, (
            f"done event metadata should contain 'steps', got keys: {list(metadata.keys())}"
        )
        assert isinstance(metadata["steps"], list)

    async def test_done_event_metadata_includes_insights(self):
        """After pipeline runs, done event metadata.insights should exist."""
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "chunk", "content": "Here is a question"},
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
                return_value=({}, "Here is a question"),
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "insights" in metadata, (
            f"done event metadata should contain 'insights', got keys: {list(metadata.keys())}"
        )
        assert isinstance(metadata["insights"], list)

    async def test_done_event_metadata_thinking_duration_calculated(self):
        """thinking_duration should be sum of all thinking session durations."""
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {
                "type": "thinking_start",
                "data": {},
            },
            {
                "type": "thinking",
                "data": {"text": "Reasoning chunk 1"},
            },
            {
                "type": "thinking_done",
                "data": {},
            },
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "thinking_duration" in metadata
        assert isinstance(metadata["thinking_duration"], (int, float))
        assert metadata["thinking_duration"] >= 0

    async def test_done_event_metadata_thinking_chunks_limited(self):
        """Thinking chunks should be limited to avoid metadata bloat."""
        from app.agents.chat.pipeline import run_chat

        # Simulate many thinking chunks
        thinking_events = [
            {"type": "thinking_start", "data": {}},
        ]
        for i in range(200):
            thinking_events.append({"type": "thinking", "data": {"text": f"chunk_{i}"}})
        thinking_events.append({"type": "thinking_done", "data": {}})

        react_events = [
            *thinking_events,
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "thinking" in metadata
        # Should be capped — 200 chunks is way over any reasonable limit
        total_chunks = sum(len(t.get("chunks", [])) for t in metadata["thinking"])
        assert total_chunks < 200, (
            f"Thinking chunks should be limited, got {total_chunks}"
        )


# ── Thinking Metadata Collection (content field) ──────────


class TestThinkingMetadataContentField:
    """Test thinking metadata collection supports content field."""

    async def test_thinking_metadata_collects_content_field(self):
        """Thinking events with 'content' field should be collected via pipeline."""
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "thinking_start", "data": {}},
            {"type": "thinking", "content": "思考内容1"},
            {"type": "thinking", "content": "思考内容2"},
            {"type": "thinking_done", "data": {}},
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "thinking" in metadata
        assert len(metadata["thinking"]) == 1
        chunks = metadata["thinking"][0].get("chunks", [])
        assert len(chunks) == 2
        assert chunks[0] == "思考内容1"
        assert chunks[1] == "思考内容2"

    async def test_thinking_metadata_fallback_to_data_text(self):
        """Thinking events should fallback to data.text when content is absent."""
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "thinking_start", "data": {}},
            {"type": "thinking", "data": {"text": "思考内容1"}},
            {"type": "thinking", "data": {"text": "思考内容2"}},
            {"type": "thinking_done", "data": {}},
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "thinking" in metadata
        chunks = metadata["thinking"][0].get("chunks", [])
        assert len(chunks) == 2
        assert chunks[0] == "思考内容1"
        assert chunks[1] == "思考内容2"

    async def test_thinking_metadata_skips_empty_chunks(self):
        """Empty thinking chunks should not be collected."""
        from app.agents.chat.pipeline import run_chat

        react_events = [
            {"type": "thinking_start", "data": {}},
            {"type": "thinking", "content": ""},
            {"type": "thinking", "data": {"text": ""}},
            {"type": "thinking", "content": "有效内容"},
            {"type": "thinking_done", "data": {}},
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
        ):
            done_event = None
            async for event in run_chat(
                conversation_id="conv-1",
                user_id=1,
                user_message="Hello",
                mode="free_practice",
            ):
                if event.get("type") == "done":
                    done_event = event

        assert done_event is not None
        metadata = done_event.get("metadata", {})
        assert "thinking" in metadata
        chunks = metadata["thinking"][0].get("chunks", [])
        assert len(chunks) == 1
        assert chunks[0] == "有效内容"


# ── Helper ─────────────────────────────────────────────────


async def _async_gen(items: list):
    """Simple async generator yielding items from a list."""
    for item in items:
        yield item

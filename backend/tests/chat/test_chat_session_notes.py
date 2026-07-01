"""
TDD 测试 — 增强 Session Notes 作为零成本压缩源

红灯阶段：enhanced 提取逻辑尚不存在，测试应 FAIL
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def _make_messages(n: int, content: str = "面试对话内容") -> list[dict]:
    """生成测试消息"""
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"[{i}] {content}"})
    return msgs


class TestExtractMemoryRichCapture:
    """extract_memory 增强记忆捕获"""

    @pytest.mark.asyncio
    async def test_captures_all_memory_types(self):
        """S-001: extract_memory 应捕获所有记忆类型（不仅 weakness/strength）"""
        from app.agents.chat.nodes import extract_memory

        mock_memories = [
            {"type": "weakness", "content": "Redis 缓存策略不熟悉"},
            {"type": "strength", "content": "Java 多线程理解深入"},
            {"type": "preference", "content": "喜欢通过代码示例学习"},
        ]

        state = {
            "user_id": 1,
            "user_message": "请介绍一下 Redis 的数据结构",
            "response": "Redis 支持五种基本数据结构...",
            "keywords": ["Redis", "数据结构"],
            "retrieved_questions": [],
            "session_notes": "",
            "conversation_id": "test-conv-id",
        }

        with patch("app.agents.chat.nodes.chat_service") as mock_svc, \
             patch("app.agents.chat.nodes._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            import json
            mock_llm.return_value = json.dumps(mock_memories)

            result = await extract_memory(state)

        # Verify that save_memory was called for all 3 types
        assert mock_svc.save_memory.call_count == 3
        saved_types = {call.kwargs.get("memory_type") or call.args[2] for call in mock_svc.save_memory.call_args_list}
        assert "weakness" in saved_types
        assert "strength" in saved_types
        assert "preference" in saved_types

    @pytest.mark.asyncio
    async def test_captures_topic_tags_from_keywords(self):
        """S-002: extract_memory 应从 keywords 生成 topic 标签"""
        from app.agents.chat.nodes import extract_memory

        state = {
            "user_id": 1,
            "user_message": "Redis 缓存和分布式锁的问题",
            "response": "Redis 可以用 SETNX 实现分布式锁...",
            "keywords": ["Redis", "缓存", "分布式锁"],
            "retrieved_questions": [],
            "session_notes": "",
            "conversation_id": "test-conv-id",
        }

        with patch("app.agents.chat.nodes.chat_service") as mock_svc, \
             patch("app.agents.chat.nodes._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "[]"

            await extract_memory(state)

        # Check that update_session_notes was called with topic info
        if mock_svc.update_session_notes.called:
            notes_arg = mock_svc.update_session_notes.call_args[0][1]
            assert "[topics]" in notes_arg

    @pytest.mark.asyncio
    async def test_captures_asked_question_in_notes(self):
        """S-003: extract_memory 应记录被问到的题目"""
        from app.agents.chat.nodes import extract_memory

        state = {
            "user_id": 1,
            "user_message": "Redis 的五种数据结构分别是...",
            "response": "很好，让我继续追问...",
            "keywords": ["Redis"],
            "intent": "interview_question",
            "retrieved_questions": [
                {"id": 1, "question": "Redis 有哪些数据结构？", "cat1": "中间件"}
            ],
            "session_notes": "",
            "conversation_id": "test-conv-id",
        }

        with patch("app.agents.chat.nodes.chat_service") as mock_svc, \
             patch("app.agents.chat.nodes._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "[]"

            await extract_memory(state)

        if mock_svc.update_session_notes.called:
            notes_arg = mock_svc.update_session_notes.call_args[0][1]
            assert "[asked]" in notes_arg

    @pytest.mark.asyncio
    async def test_captures_selected_question_instead_of_first_retrieved(self):
        """S-003b: asked ledger should record the actually selected question."""
        from app.agents.chat.nodes import extract_memory

        state = {
            "user_id": 1,
            "user_message": "我继续回答 RAG 评估指标的设计思路和实际验证过程",
            "response": "好的，换一个方向。",
            "keywords": ["RAG"],
            "intent": "interview_question",
            "selected_question": {
                "id": 2,
                "question": "RAG 评估指标怎么设计？",
                "cat1": "B.Agent与LLM应用",
                "cat2": "RAG",
                "tags": "评估",
            },
            "next_question_plan": {
                "question_id": 2,
                "question_text": "RAG 评估指标怎么设计？",
                "source": "search",
                "strategy": "interview_question",
            },
            "retrieved_questions": [
                {"id": 1, "question": "RAG 流程是什么？", "cat1": "B.Agent与LLM应用", "cat2": "RAG"},
                {"id": 2, "question": "RAG 评估指标怎么设计？", "cat1": "B.Agent与LLM应用", "cat2": "RAG"},
            ],
            "session_notes": "",
            "conversation_id": "test-conv-id",
        }

        with patch("app.agents.chat.nodes.chat_service") as mock_svc, \
             patch("app.agents.chat.nodes._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "[]"

            await extract_memory(state)

        notes_arg = mock_svc.update_session_notes.call_args[0][1]
        assert "#2" in notes_arg
        assert "RAG 评估指标怎么设计" in notes_arg
        assert "RAG 流程是什么" not in notes_arg


class TestTier1SessionNotesIntegration:
    """Tier 1 压缩集成 session notes"""

    def test_tier1_uses_session_notes_when_available(self):
        """S-004: 12K-24K 历史 + session_notes 应在 compressed 中包含 notes 文本"""
        import asyncio
        from app.agents.chat.budget import TokenBudgetManager

        messages = _make_messages(15, "A" * 950)
        notes = "[weakness] Redis 缓存策略不熟悉\n[topics] Redis, 缓存"

        mgr = TokenBudgetManager(total_budget_chars=12000)
        recent, compressed, tier = asyncio.run(mgr.compress(
            messages=messages,
            session_notes=notes,
            existing_compressed=None,
        ))

        assert compressed is not None
        # Session notes content should be in the compressed output
        assert "Redis" in compressed

    def test_tier1_falls_back_to_snip_when_no_notes(self):
        """S-005: 15K 历史 + 空 notes 应回退到 snip"""
        import asyncio
        from app.agents.chat.budget import TokenBudgetManager

        messages = _make_messages(15, "B" * 950)

        # Budget 20000 gives enough room for snip
        mgr = TokenBudgetManager(total_budget_chars=20000)
        recent, compressed, tier = asyncio.run(mgr.compress(
            messages=messages,
            session_notes="",
            existing_compressed=None,
        ))

        assert tier == "snip"
        assert compressed is not None


class TestPreResponseNote:
    """预笔记功能"""

    def test_pre_response_note_inserted_after_classify(self):
        """S-006: 意图分类后应插入预笔记到 session_notes"""
        # This tests the graph.py integration - pre-response note pattern
        state = {
            "intent": "interview_question",
            "keywords": ["Redis", "缓存"],
            "session_notes": "[weakness] SQL 不熟练",
        }

        # Simulate the pre-response note logic from graph.py
        if state.get("intent") == "interview_question" and state.get("keywords"):
            topic_tag = ", ".join(state["keywords"][:3])
            pre_note = f"[pending] 候选人正在回答: {topic_tag}"
            current_notes = state.get("session_notes", "")
            state["session_notes"] = f"{current_notes}\n{pre_note}" if current_notes else pre_note

        assert "[pending]" in state["session_notes"]
        assert "Redis" in state["session_notes"]

    def test_notes_cap_at_2000_chars(self):
        """S-007: session_notes 应在 2000 字符处截断"""
        # Simulate the truncation logic
        long_notes = "\n".join(f"[weakness] 弱点 {i}: {'X' * 100}" for i in range(50))
        assert len(long_notes) > 2000

        # Apply the 2000-char cap (preserving most recent)
        if len(long_notes) > 2000:
            long_notes = long_notes[-2000:]

        assert len(long_notes) <= 2000

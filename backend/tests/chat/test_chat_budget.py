"""
TDD 测试 — TokenBudgetManager 统一预算管理 + 五级级联压缩

红灯阶段：此模块尚不存在，测试应 FAIL
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


def _make_messages(n: int, content_per_msg: str = "这是一段面试对话内容，关于技术问题的讨论。") -> list[dict]:
    """生成 n 条测试消息（交替 user/assistant）"""
    msgs = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        msgs.append({"role": role, "content": f"[{i}] {content_per_msg}"})
    return msgs


class TestTokenBudgetManager:
    """TokenBudgetManager 预算管理测试"""

    def test_measure_returns_correct_snapshot_for_small_history(self):
        """B-001: 短对话（5 条消息, ~2K chars）应返回 needs_compression=False"""
        from app.agents.chat.budget import TokenBudgetManager

        state = {
            "message_history": _make_messages(5, "短消息"),
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
            "retrieved_questions": [],
            "user_message": "请问 Redis 有哪些数据结构？",
        }

        mgr = TokenBudgetManager()
        snapshot = mgr.measure(state)

        assert snapshot.utilization_pct < 60
        assert mgr.needs_compression(snapshot) is False

    def test_cascade_stops_at_snip_tier_for_medium_history(self):
        """B-002: 15K 历史应级联停在 snip 层，无 LLM 调用"""
        import asyncio
        from app.agents.chat.budget import TokenBudgetManager

        # 15 messages * ~1000 chars = ~15K
        messages = _make_messages(15, "A" * 950)

        # Budget 20000 gives ~11700 available, enough for snip
        mgr = TokenBudgetManager(total_budget_chars=20000)
        recent, compressed, tier = asyncio.run(mgr.compress(
            messages=messages,
            session_notes="",
            existing_compressed=None,
        ))

        assert tier == "snip"
        assert len(recent) > 0
        assert compressed is not None

    def test_cascade_uses_session_notes_when_available(self):
        """B-003: >24K 历史 + session_notes 应停在 session_notes 层"""
        import asyncio
        from app.agents.chat.budget import TokenBudgetManager

        messages = _make_messages(30, "B" * 800)
        notes = "[weakness] Redis 缓存策略不熟悉\n[topics] Redis, 缓存"

        mgr = TokenBudgetManager(total_budget_chars=12000)
        recent, compressed, tier = asyncio.run(mgr.compress(
            messages=messages,
            session_notes=notes,
            existing_compressed=None,
        ))

        # session_notes 或 micro_compact 都是零 LLM 成本
        assert tier in ("session_notes", "micro_compact")
        assert "Redis" in (compressed or "")

    def test_cascade_falls_through_to_llm_when_no_notes(self):
        """B-004: >24K 历史 + 无 session_notes 应降级到 LLM"""
        from app.agents.chat.budget import TokenBudgetManager

        messages = _make_messages(30, "C" * 800)

        mgr = TokenBudgetManager(total_budget_chars=8000)

        with patch("app.agents.chat.budget._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '## 已完成的考察\n- Redis 数据结构: 3分\n\n## 待考察的方向\n- 缓存穿透'

            import asyncio
            recent, compressed, tier = asyncio.run(
                mgr.compress(messages=messages, session_notes="", existing_compressed=None)
            )

        assert tier == "llm"
        assert compressed is not None

    def test_cascade_reduces_recent_window_for_very_long_history(self):
        """B-005: 超长对话应缩减 recent window (5→3→2 轮)"""
        from app.agents.chat.budget import TokenBudgetManager

        messages = _make_messages(50, "D" * 700)

        mgr = TokenBudgetManager(total_budget_chars=8000)

        with patch("app.agents.chat.budget._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = '## 面试目标\n- 自由练习\n\n## 已完成的考察\n（暂无）\n\n## 剩余工作\n- 继续考察八股和算法'

            import asyncio
            recent, compressed, tier = asyncio.run(
                mgr.compress(messages=messages, session_notes="", existing_compressed=None)
            )

        # Recent window should be reduced from default 10 (5 rounds * 2)
        assert len(recent) <= 6  # at most 3 rounds * 2

    def test_empty_message_history_returns_cleanly(self):
        """B-006: 空消息列表应返回空结果，tier="none" """
        import asyncio
        from app.agents.chat.budget import TokenBudgetManager

        mgr = TokenBudgetManager()
        recent, compressed, tier = asyncio.run(mgr.compress(
            messages=[],
            session_notes="",
            existing_compressed=None,
        ))

        assert recent == []
        assert compressed is None
        assert tier == "none"

    def test_budget_snapshot_travels_in_state(self):
        """B-007: 测量后的 snapshot 应可存入 state 供下游使用"""
        from app.agents.chat.budget import TokenBudgetManager, BudgetSnapshot

        state = {
            "message_history": _make_messages(5),
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
            "retrieved_questions": [],
            "user_message": "测试消息",
        }

        mgr = TokenBudgetManager()
        snapshot = mgr.measure(state)

        assert isinstance(snapshot, BudgetSnapshot)
        assert hasattr(snapshot, "compression_tier")
        assert hasattr(snapshot, "total_chars")
        assert snapshot.total_chars > 0


class TestBudgetHelpers:
    """工具函数测试"""

    def test_count_chars_sums_message_content(self):
        """_count_chars 应正确计算消息总字符数"""
        from app.agents.chat.nodes import _count_chars

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "你好世界"},
        ]
        # "Hello" = 5, "你好世界" = 4
        assert _count_chars(messages) == 9

    def test_count_chars_handles_empty_list(self):
        from app.agents.chat.nodes import _count_chars
        assert _count_chars([]) == 0

    def test_snip_messages_truncates_long_content(self):
        """_snip_messages 应将长消息截断为一行摘要"""
        from app.agents.chat.nodes import _snip_messages

        messages = [
            {"role": "user", "content": "A" * 200},
            {"role": "assistant", "content": "B" * 200},
        ]
        result = _snip_messages(messages)
        # Each line should be truncated to ~60 chars
        for line in result.split("\n"):
            assert len(line) < 100

    def test_truncate_to_budget_respects_limit(self):
        """_truncate_to_budget 应在 budget 范围内截断"""
        from app.agents.chat.nodes import _truncate_to_budget

        text = "A" * 1000
        result = _truncate_to_budget(text, 500)
        assert len(result) <= 503  # +3 for "..."

    def test_truncate_to_budget_preserves_short_text(self):
        """_truncate_to_budget 不应截断短文本"""
        from app.agents.chat.nodes import _truncate_to_budget

        text = "短文本"
        result = _truncate_to_budget(text, 500)
        assert result == text

"""TDD tests for OutputDeduplicator — two-level (hash + Jaccard) output dedup."""

import pytest

from app.agents.chat.pipeline import OutputDeduplicator


class TestOutputDeduplicatorHash:
    """Level 1: Hash exact match detection."""

    def test_exact_duplicate_detected(self):
        """Identical normalized text should return 'exact'."""
        dedup = OutputDeduplicator()
        text = "你好，我们先收束到一道具体题：LRU Cache"
        assert dedup.check(text) == "ok"
        dedup.record(text)
        assert dedup.check(text) == "exact"

    def test_exact_match_ignores_whitespace(self):
        """Extra whitespace differences should still be 'exact'."""
        dedup = OutputDeduplicator()
        text1 = "你好  世界"
        text2 = "你好 世界"
        dedup.record(text1)
        assert dedup.check(text2) == "exact"

    def test_exact_match_ignores_case(self):
        """Case differences should still be 'exact'."""
        dedup = OutputDeduplicator()
        text1 = "Hello World"
        text2 = "hello world"
        dedup.record(text1)
        assert dedup.check(text2) == "exact"

    def test_different_text_not_exact(self):
        """Completely different text should not be 'exact'."""
        dedup = OutputDeduplicator()
        dedup.record("我们来聊聊 RAG")
        assert dedup.check("我们来聊聊 Agent") == "ok"

    def test_exact_after_multiple_records(self):
        """Exact match should work across any number of recorded entries."""
        dedup = OutputDeduplicator()
        dedup.record("话题一")
        dedup.record("话题二")
        dedup.record("话题三")
        assert dedup.check("话题二") == "exact"


class TestOutputDeduplicatorJaccard:
    """Level 2: Jaccard fuzzy match detection."""

    def test_similar_text_detected(self):
        """Highly overlapping text should return 'similar'."""
        dedup = OutputDeduplicator(jaccard_threshold=0.7)
        # Realistic LLM output with mixed Chinese/English tokens
        text1 = "Lru Cache 的实现方式是使用 HashMap 和双向链表 时间复杂度 O(1)"
        text2 = "Lru Cache 的实现方式是使用 HashMap 加双向链表 时间复杂度 O(1)"
        dedup.record(text1)
        result = dedup.check(text2)
        assert result in ("similar", "exact")

    def test_different_text_not_similar(self):
        """Completely different text should be 'ok'."""
        dedup = OutputDeduplicator(jaccard_threshold=0.7)
        dedup.record("你了解过 RAG 吗 说说你对 RAG 的理解")
        assert dedup.check("我们来聊聊 Agent 的架构设计和工具调用") == "ok"

    def test_short_text_skips_jaccard(self):
        """Text with fewer than 5 tokens should skip Jaccard check."""
        dedup = OutputDeduplicator()
        dedup.record("你好 你好 你好 你好")
        # "你好" repeated 4 times = 1 unique token (< 5 tokens threshold)
        assert dedup.check("你好 你好 你好 你好") == "exact"  # caught by hash

    def test_short_different_text_ok(self):
        """Short text with <5 unique tokens should not trigger Jaccard."""
        dedup = OutputDeduplicator()
        dedup.record("一句话回答")
        assert dedup.check("另一句回答") == "ok"

    def test_jaccard_respects_threshold(self):
        """Text below threshold should be 'ok'."""
        dedup = OutputDeduplicator(jaccard_threshold=0.9)
        text1 = "这是一个关于 RAG 和 Agent 的面试题 需要候选人回答技术方案"
        text2 = "这是一个关于 LLM 和 Prompt 的面试题 需要候选人设计系统架构"
        dedup.record(text1)
        assert dedup.check(text2) == "ok"


class TestOutputDeduplicatorWindow:
    """Window management and recording behavior."""

    def test_window_size_limits_jaccard_lookback(self):
        """Old entries outside window should not trigger Jaccard."""
        dedup = OutputDeduplicator(window_size=2)
        text1 = "Lru Cache 的实现方式是使用 HashMap 和双向链表 时间复杂度 O(1)"
        dedup.record(text1)
        # Record 2 more entries to push text1 out of Jaccard window
        dedup.record("完全不同的话题 A 关于分布式系统和微服务架构")
        dedup.record("完全不同的话题 B 关于数据库索引和查询优化")
        # Hash still catches exact matches
        assert dedup.check(text1) == "exact"
        # But a similar (not exact) text should pass since text1 is out of window
        similar = "Lru Cache 的实现方式是使用 HashMap 加双向链表 时间复杂度 O(1)"
        assert dedup.check(similar) == "ok"

    def test_hash_buffer_never_shrinks(self):
        """Hash buffer should retain all entries (not affected by window)."""
        dedup = OutputDeduplicator(window_size=2)
        dedup.record("text one")
        dedup.record("text two")
        dedup.record("text three")
        # text_one is outside Jaccard window but hash should still catch it
        assert dedup.check("text one") == "exact"

    def test_record_then_check_consistency(self):
        """After recording, the same text should always be 'exact'."""
        dedup = OutputDeduplicator()
        for i in range(20):
            text = f"这是第 {i} 条面试问题"
            assert dedup.check(text) == "ok"
            dedup.record(text)
            assert dedup.check(text) == "exact"

    def test_empty_text(self):
        """Empty or whitespace-only text should be handled gracefully."""
        dedup = OutputDeduplicator()
        assert dedup.check("") == "ok"
        assert dedup.check("   ") == "ok"
        dedup.record("")
        assert dedup.check("") == "exact"

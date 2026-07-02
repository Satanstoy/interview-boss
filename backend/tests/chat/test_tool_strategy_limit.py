"""Tests for _build_tool_strategy consecutive topic hard limit.

When the interviewer has been asking about the same topic 3+ times consecutively,
tool_strategy should force a topic switch instead of continuing.
"""
from __future__ import annotations

import pytest


def _make_state_with_assistant_history(assistant_contents: list[str]) -> dict:
    """Build a minimal state with assistant message history for repetition detection."""
    history = []
    for content in assistant_contents:
        history.append({"role": "assistant", "content": content})
        history.append({"role": "user", "content": "（候选人回答）"})
    return {
        "message_history": history,
        "intent": "interview_question",
        "answer_complete": True,
        "retrieved_questions": [{"id": 1, "question": "Redis 跳表结构"}],
        "active_skills": [],
        "interview_state": {},
    }


class TestBuildToolStrategyConsecutiveLimit:
    """_build_tool_strategy should force topic switch after 3+ consecutive same-topic."""

    def test_normal_no_limit(self):
        from app.agents.chat.nodes import _build_tool_strategy

        state = _make_state_with_assistant_history([
            "说说你的项目架构。",
            "Redis 缓存怎么设计的？",
            "MySQL 索引原理是什么？",
        ])
        strategy = _build_tool_strategy(state)
        # Should NOT force switch — topics are diverse
        assert "禁止" not in strategy or "同一话题" not in strategy

    def test_three_consecutive_same_topic_forces_switch(self):
        from app.agents.chat.nodes import _build_tool_strategy

        # Use messages with clear repeated tokens to trigger the overlap detection
        state = _make_state_with_assistant_history([
            "说说 Redis 缓存穿透怎么解决？Redis 缓存击穿怎么处理？",
            "Redis 缓存雪崩是什么？Redis 缓存和 MySQL 一致性怎么保证？",
            "Redis 缓存的过期策略有哪些？Redis 缓存淘汰机制怎么选？",
        ])
        strategy = _build_tool_strategy(state)
        # Should force switch
        assert "切换" in strategy or "不同" in strategy or "禁止" in strategy

    def test_two_consecutive_same_topic_no_limit_yet(self):
        from app.agents.chat.nodes import _build_tool_strategy

        state = _make_state_with_assistant_history([
            "Redis 缓存穿透怎么解决？",
            "Redis 缓存击穿和雪崩的区别？",
        ])
        strategy = _build_tool_strategy(state)
        # 2 consecutive is OK, should not force switch
        # (may have other instructions but not the hard limit)
        assert "已连续多次追问同一话题" not in strategy

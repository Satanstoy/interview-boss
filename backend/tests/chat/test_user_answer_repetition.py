"""Tests for candidate answer repetition detection.

Covers:
- _count_consecutive_similar_user_answers: detect when candidate repeats same answer
- stop_policy integration: force topic switch on repetition
"""
from __future__ import annotations

import pytest


def _make_state(user_messages: list[str], assistant_messages: list[str] | None = None) -> dict:
    """Build a minimal ChatState for testing."""
    history = []
    if assistant_messages is None:
        assistant_messages = ["你好，请自我介绍。"] * len(user_messages)
    for u, a in zip(user_messages, assistant_messages):
        history.append({"role": "assistant", "content": a})
        history.append({"role": "user", "content": u})
    return {"message_history": history}


# ── _count_consecutive_similar_user_answers ─────────────────────


class TestCountConsecutiveSimilarUserAnswers:
    """Detect when candidate repeats the same answer across turns."""

    def test_returns_zero_for_single_message(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        state = _make_state(["我用 Redis 做缓存。"])
        assert _count_consecutive_similar_user_answers(state) == 0

    def test_returns_zero_for_different_messages(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        state = _make_state([
            "我用 Redis 做缓存，TTL 设了 300 秒。",
            "MySQL 索引用 B+ 树，查询走覆盖索引。",
        ])
        assert _count_consecutive_similar_user_answers(state) == 0

    def test_detects_two_consecutive_identical(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        answer = "这个项目里我把链路拆成上下文加载、意图分类、ReAct 循环、metadata 落账和记忆提取几个阶段。"
        state = _make_state([answer, answer])
        assert _count_consecutive_similar_user_answers(state) >= 1

    def test_detects_three_consecutive_identical(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        answer = "这个项目里我把链路拆成上下文加载、意图分类、ReAct 循环、metadata 落账和记忆提取几个阶段。"
        state = _make_state([answer, answer, answer])
        assert _count_consecutive_similar_user_answers(state) >= 2

    def test_resets_on_different_message(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        answer = "这个项目里我把链路拆成上下文加载、意图分类、ReAct 循环。"
        state = _make_state([
            answer,
            answer,
            "MySQL 索引用 B+ 树，查询走覆盖索引。",  # different
        ])
        # The last two messages are different, so count should be 0
        assert _count_consecutive_similar_user_answers(state) == 0

    def test_counts_only_recent_tail(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        answer_a = "我用 Redis 做缓存，TTL 设了 300 秒，避免缓存雪崩。"
        answer_b = "这个项目里我把链路拆成上下文加载、意图分类、ReAct 循环。"
        state = _make_state([
            answer_a,
            answer_b,  # different
            answer_b,
            answer_b,  # 2 consecutive repeats of B
        ])
        assert _count_consecutive_similar_user_answers(state) >= 1

    def test_returns_zero_for_empty_history(self):
        from app.agents.chat.question_plan import _count_consecutive_similar_user_answers

        state = {"message_history": []}
        assert _count_consecutive_similar_user_answers(state) == 0


# ── stop_policy integration ─────────────────────────────────────


class TestStopPolicyRepetition:
    """stop_policy should force topic switch or close on candidate repetition."""

    def test_repeat_3_triggers_ask_candidate_question(self):
        from app.agents.chat.stop_policy import evaluate_interview_stop

        answer = "这个项目里我把链路拆成上下文加载、意图分类、ReAct 循环、metadata 落账和记忆提取几个阶段。关键状态不只放在 prompt 里。"
        state = _make_state([answer] * 4, ["问你检索"] * 4)
        result = evaluate_interview_stop(state)
        assert result["action"] in ("ask_candidate_question", "close")
        assert result.get("reason") in ("candidate_repeated_answers", "candidate_repeated_answers_excessive")
        # No hardcoded message — LLM generates the actual response
        assert "message" not in result or result.get("message") is None

    def test_repeat_5_triggers_close(self):
        from app.agents.chat.stop_policy import evaluate_interview_stop

        answer = "这个项目里我把链路拆成上下文加载、意图分类、ReAct 循环、metadata 落账和记忆提取几个阶段。关键状态不只放在 prompt 里。"
        state = _make_state([answer] * 6, ["问你检索"] * 6)
        result = evaluate_interview_stop(state)
        assert result["action"] == "close"
        assert result.get("reason") == "candidate_repeated_answers_excessive"

    def test_no_repeat_normal_continue(self):
        from app.agents.chat.stop_policy import evaluate_interview_stop

        state = _make_state([
            "我用 Redis 做缓存，TTL 设了 300 秒。",
            "MySQL 索引用 B+ 树，查询走覆盖索引。",
            "TCP 三次握手是 SYN、SYN-ACK、ACK。",
        ], ["问你缓存", "问你索引", "问你网络"])
        result = evaluate_interview_stop(state)
        assert result["action"] == "continue"

"""Tests for TurnController routing decisions."""

from app.agents.chat.turn_controller import decide_turn_action


def test_turn_action_closing_summary_on_closing_signal():
    """候选人发出收尾信号时应路由到 closing_summary。"""
    state = {
        "closing_stage": "technical",
        "user_message": "今天聊得挺深入的，时间差不多了。感谢您的时间！",
        "message_count": 12,
        "answer_quality": "complete",
    }
    result = decide_turn_action(state)
    assert result["turn_action"] == "closing_summary"
    assert "收尾信号" in result["turn_reason"]


def test_turn_action_bank_question_for_algorithm():
    """需要算法题时应路由到 bank_question。"""
    state = {
        "closing_stage": "technical",
        "user_message": "我用双指针法解决的",
        "message_count": 6,
        "answer_quality": "complete",
        "requires_bank_question": True,
        "classify_result": {"question_type": "algorithm_coding"},
    }
    result = decide_turn_action(state)
    assert result["turn_action"] == "bank_question"


def test_turn_action_answer_counter_question():
    """候选人反问时应路由到 answer_counter_question。"""
    state = {
        "closing_stage": "candidate_question_asked",
        "user_message": "我想了解一下，贵团队在分布式锁方面是怎么做的？",
        "message_count": 14,
        "counter_question": True,
        "counter_question_topic": "分布式锁",
    }
    result = decide_turn_action(state)
    assert result["turn_action"] == "answer_counter_question"

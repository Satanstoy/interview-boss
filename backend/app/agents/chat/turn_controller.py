"""TurnController: 决定本轮面试的路由动作。"""

from __future__ import annotations

from typing import Any

from app.agents.chat.stop_policy import detect_closing_signal


def decide_turn_action(state: dict[str, Any]) -> dict[str, Any]:
    """根据当前状态决定 turn_action 和 turn_reason。

    Returns:
        {"turn_action": str, "turn_reason": str, "question_intent": dict | None}
    """
    closing_stage = state.get("closing_stage", "technical")
    user_message = state.get("user_message", "")
    counter_question = state.get("counter_question", False)
    requires_bank_question = state.get("requires_bank_question", False)
    classify_result = state.get("classify_result", {})
    answer_quality = state.get("answer_quality", "complete")
    message_count = state.get("message_count", 0)

    # 1. 已进入收尾阶段的硬路由
    if closing_stage == "final_summary":
        return {"turn_action": "closing_summary", "turn_reason": "closing_stage=final_summary", "question_intent": None}

    if closing_stage == "candidate_question_answered":
        return {"turn_action": "closing_summary", "turn_reason": "candidate question answered, now summarize", "question_intent": None}

    # 2. 候选人反问
    if counter_question or closing_stage == "candidate_question_asked":
        return {
            "turn_action": "answer_counter_question",
            "turn_reason": f"candidate asked: {state.get('counter_question_topic', 'unknown')}",
            "question_intent": None,
        }

    # 3. 收尾信号检测
    if detect_closing_signal(user_message):
        return {"turn_action": "closing_summary", "turn_reason": "收尾信号检测到", "question_intent": None}

    # 4. 需要题库新题
    if requires_bank_question or classify_result.get("question_type") in ("algorithm_coding", "system_design", "new_question"):
        return {
            "turn_action": "bank_question",
            "turn_reason": f"question_type={classify_result.get('question_type', 'unknown')}",
            "question_intent": {
                "question_type": classify_result.get("question_type", "new_question"),
                "transition_style": classify_result.get("transition_style", "natural"),
                "search_query": classify_result.get("search_query", ""),
            },
        }

    # 5. 自然追问（默认）
    return {
        "turn_action": "natural_followup",
        "turn_reason": f"answer_quality={answer_quality}, continuing",
        "question_intent": {
            "question_type": classify_result.get("question_type", "follow_up"),
            "transition_style": classify_result.get("transition_style", "natural"),
        },
    }

"""Pure routing functions for the interview chat state machine.

These functions act as conditional edges: they read typed state fields and
return the next node / action.  They have no side effects and are easy to unit
test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.chat.decision_config import DecisionConfig
    from app.agents.chat.state import ChatState


def route_after_classify(state: "ChatState") -> str:
    """Return the next node name after classify_intent."""
    intent = state.get("intent", "interview_question")
    if intent == "end_interview":
        return "closing"
    if intent == "chat":
        return "direct_response"
    return "react_loop"


def should_record_retrieval_gap(state: "ChatState") -> bool:
    """Whether to record that recommended retrieval was skipped.

    This is an observability signal, not a control-flow takeover. The ReAct
    loop may still accept a natural conversation-only follow-up when the model
    chooses not to call search/draw tools.
    """
    if state.get("intent") not in ("interview_question", "practice_request"):
        return False
    answer_quality = state.get("answer_quality", "complete")
    if answer_quality not in ("complete", "vague"):
        return False
    if not state.get("should_retrieve"):
        return False
    if state.get("retrieved_questions") or state.get("candidate_questions"):
        return False
    return True


def should_topic_shift(state: "ChatState") -> bool:
    """True when the agent should abandon the current topic."""
    return (
        state.get("off_topic_streak", 0) >= 3
        or state.get("repetition_streak", 0) >= 2
        or state.get("escalation_level", 0) >= 3
    )


def should_close_interview(
    state: "ChatState",
    config: "DecisionConfig | None" = None,
) -> dict:
    """Return a stop decision dict based purely on state + thresholds.

    Mirrors the shape returned by stop_policy.evaluate_interview_stop.
    """
    from app.agents.chat.decision_config import DecisionConfig

    cfg = config or state.get("decision_config") or DecisionConfig()
    message_count = len(state.get("message_history", []) or [])

    # Hard stop by message count.
    if message_count >= cfg.hard_stop_message_count:
        return {
            "action": "close",
            "mode": "hard_stop",
            "reason": "hard_stop_by_message_count",
            "message_count": message_count,
        }

    # Candidate repeated answers -> degraded (ask candidate question).
    repetition = state.get("repetition_streak", 0)
    if repetition >= cfg.candidate_repeat_close:
        return {
            "action": "close",
            "mode": "forced_by_repetition",
            "reason": "candidate_repeated_answers_excessive",
            "message_count": message_count,
        }
    if repetition >= cfg.candidate_repeat_degraded:
        return {
            "action": "ask_candidate_question",
            "mode": "degraded",
            "reason": "candidate_repeated_answers",
            "message": "我注意到你连续几次的回答内容比较相似。我们换个方向——你有什么想问我们的吗？",
            "message_count": message_count,
        }

    # Default: continue.
    return {
        "action": "continue",
        "mode": "normal",
        "reason": "state_allows_continue",
        "message_count": message_count,
    }


def is_retrieval_allowed(state: "ChatState") -> bool:
    """True if the current turn is allowed to call search/draw tools."""
    intent = state.get("intent", "interview_question")
    if intent in ("chat", "end_interview"):
        return False
    answer_quality = state.get("answer_quality", "complete")
    if answer_quality in ("incomplete", "off_topic", "repeated"):
        return False
    return True


def needs_candidate_reverse_question(state: "ChatState") -> bool:
    """True when the assistant should ask 'do you have questions for us?'."""
    interview_state = state.get("interview_state") or {}
    if not isinstance(interview_state, dict):
        return False
    return interview_state.get("asked_candidate_question") is False and interview_state.get("phase") == "wrap_up"

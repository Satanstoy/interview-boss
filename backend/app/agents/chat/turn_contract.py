"""TurnContract — 本轮输出契约。

TurnContract 是短生命周期对象，只对本轮有效。下一轮重新计算，历史事实写入 ledger。

TurnPlanner 是确定性 policy，不读原始用户文本，只读结构化输入：
- semantic classifier result
- ledger / coverage facts
- stop policy result
- tool facts (selected_question, candidate_questions)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("interview-boss")


class TurnContractAction(str, Enum):
    """本轮输出的动作类型。"""

    CLOSE_WITH_SUMMARY = "close_with_summary"
    ANSWER_COUNTER_QUESTION = "answer_counter_question"
    CLARIFY_CANDIDATE_ANSWER = "clarify_candidate_answer"
    ASK_SELECTED_QUESTION = "ask_selected_question"
    CONTINUE_NATURAL_FOLLOWUP = "continue_natural_followup"


# Priority order (highest first):
# 1. close_with_summary — 产品级 exit condition
# 2. answer_counter_question — 避免反问被硬切题库题
# 3. clarify_candidate_answer — 避免含糊回答时为覆盖率强切新题
# 4. ask_selected_question — coverage gap 明确 + 高置信选题
# 5. continue_natural_followup — 默认低风险路径
_ACTION_PRIORITY = {
    TurnContractAction.CLOSE_WITH_SUMMARY: 1,
    TurnContractAction.ANSWER_COUNTER_QUESTION: 2,
    TurnContractAction.CLARIFY_CANDIDATE_ANSWER: 3,
    TurnContractAction.ASK_SELECTED_QUESTION: 4,
    TurnContractAction.CONTINUE_NATURAL_FOLLOWUP: 5,
}

# Validation rules per action
_ACTION_VALIDATIONS = {
    TurnContractAction.CLOSE_WITH_SUMMARY: ["non_empty", "no_unrequested_summary"],
    TurnContractAction.ANSWER_COUNTER_QUESTION: ["non_empty", "no_internal_marker"],
    TurnContractAction.CLARIFY_CANDIDATE_ANSWER: ["non_empty", "no_internal_marker"],
    TurnContractAction.ASK_SELECTED_QUESTION: [
        "non_empty",
        "no_internal_marker",
        "semantic_question_adherence",
    ],
    TurnContractAction.CONTINUE_NATURAL_FOLLOWUP: ["non_empty"],
}


class TurnContract(BaseModel):
    """本轮输出契约。

    Planner 读取结构化事实后输出 TurnContract，Writer 根据 contract 生成自然表达，
    Validator 根据 contract.validation 验证输出。
    """

    action: TurnContractAction
    priority: str = Field(description="本次决策的优先级来源，如 coverage_gap, wrap_up 等")
    payload: dict[str, Any] = Field(default_factory=dict, description="Writer 需要的结构化数据")
    validation: list[str] = Field(default_factory=list, description="本输出需要通过的验证规则")
    reason: str = Field(description="人类可读的决策原因")
    source_facts: dict[str, Any] = Field(default_factory=dict, description="参与决策的结构化事实")

    def to_metadata_dict(self) -> dict[str, Any]:
        """输出到 done metadata 的精简格式。"""
        return {
            "action": self.action.value,
            "priority": self.priority,
            "payload": self.payload,
            "validation": self.validation,
            "reason": self.reason,
            "source_facts": self.source_facts,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "TurnContract":
        """Best-effort parse; never raise. 无效数据默认为 continue_natural_followup。"""
        if not isinstance(data, dict):
            return cls._default()
        try:
            return cls.model_validate(data)
        except Exception:
            return cls._default()

    @classmethod
    def _default(cls) -> "TurnContract":
        return cls(
            action=TurnContractAction.CONTINUE_NATURAL_FOLLOWUP,
            priority="default",
            payload={},
            validation=["non_empty"],
            reason="fallback: invalid or missing contract data",
            source_facts={},
        )

    @model_validator(mode="after")
    def _fill_validation(self) -> "TurnContract":
        """如果 validation 为空，自动填充该 action 的默认规则。"""
        if not self.validation:
            self.validation = _ACTION_VALIDATIONS.get(
                self.action, ["non_empty"]
            )
        return self


def plan_turn(state: dict[str, Any]) -> TurnContract:
    """确定性 TurnPlanner：读取结构化事实，输出 TurnContract。

    不读原始用户文本，只消费：
    - classify_result (semantic signals)
    - closing_stage / counter_question (state machine)
    - selected_question / candidate_questions (tool facts)
    - message_count / coverage (ledger facts)
    """
    classify_result = state.get("classify_result") or {}
    closing_stage = state.get("closing_stage", "technical")
    counter_evidence = classify_result.get("counter_question")
    if not isinstance(counter_evidence, dict):
        counter_evidence = state.get("counter_question_evidence")
    asked_counter_question = bool(counter_evidence)
    counter_question = asked_counter_question
    counter_question_topic = (
        (counter_evidence or {}).get("topic")
        or state.get("counter_question_topic")
    )
    selected_question = state.get("selected_question")
    answer_quality = classify_result.get("answer_quality", "complete")
    message_count = state.get("message_count", 0)

    logger.info(
        "TurnPlanner: closing_stage=%s counter=%s answer_quality=%s selected_q=%s msg_count=%s",
        closing_stage,
        counter_question,
        answer_quality,
        bool(selected_question),
        message_count,
    )

    # Priority 1: close_with_summary
    if state.get("intent") == "end_interview" or classify_result.get("requested_end"):
        return TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority="explicit_end_request",
            payload={"closing_reason": "explicit_end_request"},
            reason="candidate explicitly requested to end the interview",
            source_facts={
                "intent": state.get("intent"),
                "requested_end": classify_result.get("requested_end", False),
                "message_count": message_count,
            },
        )

    if closing_stage in ("final_summary", "candidate_question_answered", "closed"):
        return TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority="closing_stage",
            payload={"closing_reason": f"closing_stage={closing_stage}"},
            reason=f"closing_stage={closing_stage}",
            source_facts={
                "closing_stage": closing_stage,
                "message_count": message_count,
            },
        )

    if (
        closing_stage == "candidate_question_asked"
        and not counter_question
        and not state.get("distribution_primary_required")
    ):
        return TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority="wrap_up",
            payload={"closing_reason": "candidate_question_already_asked"},
            reason="candidate question already asked, now close",
            source_facts={
                "closing_stage": closing_stage,
                "message_count": message_count,
            },
        )

    # Check stop policy for close action
    from app.agents.chat.stop_policy import evaluate_interview_stop

    stop_result = evaluate_interview_stop(state)
    if stop_result.get("action") == "ask_candidate_question":
        return TurnContract(
            action=TurnContractAction.CONTINUE_NATURAL_FOLLOWUP,
            priority="candidate_question_prompt",
            payload={"next_focus": "candidate_question"},
            reason=f"stop_policy: {stop_result.get('reason')}",
            source_facts={
                "stop_policy_action": stop_result.get("action"),
                "stop_policy_reason": stop_result.get("reason"),
                "message_count": message_count,
            },
        )
    if stop_result.get("action") == "close":
        return TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority=stop_result.get("mode", "wrap_up"),
            payload={"closing_reason": stop_result.get("reason", "stop_policy")},
            reason=f"stop_policy: {stop_result.get('reason')}",
            source_facts={
                "stop_policy_action": stop_result.get("action"),
                "stop_policy_mode": stop_result.get("mode"),
                "stop_policy_reason": stop_result.get("reason"),
                "message_count": message_count,
            },
        )

    # Priority 2: answer_counter_question
    if counter_question or (
        closing_stage == "candidate_question_asked"
        and not state.get("distribution_primary_required")
    ):
        return TurnContract(
            action=TurnContractAction.ANSWER_COUNTER_QUESTION,
            priority="counter_question",
            payload={"counter_question_topic": counter_question_topic or "unknown"},
            reason=f"candidate asked: {counter_question_topic or 'unknown'}",
            source_facts={
                "counter_question": counter_question,
                "asked_counter_question": asked_counter_question,
                "counter_question_topic": counter_question_topic,
                "closing_stage": closing_stage,
            },
        )

    # Priority 3: clarify_candidate_answer
    if classify_result.get("needs_clarification") or answer_quality in ("vague", "incomplete"):
        return TurnContract(
            action=TurnContractAction.CLARIFY_CANDIDATE_ANSWER,
            priority=f"answer_{answer_quality}",
            payload={"answer_quality": answer_quality},
            reason=f"answer_quality={answer_quality}, need clarification",
            source_facts={
                "answer_quality": answer_quality,
                "intent": classify_result.get("intent"),
                "needs_clarification": bool(
                    classify_result.get("needs_clarification", False)
                ),
            },
        )

    # Priority 4: ask_selected_question
    if selected_question and _should_ask_selected_question(state, classify_result):
        qid = selected_question.get("id")
        return TurnContract(
            action=TurnContractAction.ASK_SELECTED_QUESTION,
            priority="coverage_gap",
            payload={
                "question_id": qid,
                "question_text": selected_question.get("question", ""),
                "source": state.get("question_source", "unknown"),
                "expected_focus": _extract_expected_focus(selected_question),
            },
            reason=f"selected question {qid} available with high confidence",
            source_facts={
                "answer_quality": answer_quality,
                "selected_question_id": qid,
                "should_retrieve": classify_result.get("should_retrieve"),
                "needs_new_dimension": classify_result.get("needs_new_dimension"),
                "semantic_confidence": classify_result.get("confidence", 0.0),
                "selection_confidence": _selection_confidence(state),
            },
        )

    # Priority 5: continue_natural_followup (default)
    return TurnContract(
        action=TurnContractAction.CONTINUE_NATURAL_FOLLOWUP,
        priority="default",
        payload={},
        reason=f"answer_quality={answer_quality}, continuing natural flow",
        source_facts={
            "answer_quality": answer_quality,
            "intent": classify_result.get("intent"),
        },
    )


def _should_ask_selected_question(state: dict, classify_result: dict) -> bool:
    """判断是否应该使用 selected_question。

    条件：
    - selected_question 存在且有 id
    - answer_quality 为 complete（不是 vague/incomplete/off_topic）
    - 不是 practice_request 模式（practice 有自己的流程）
    """
    selected = state.get("selected_question")
    if not selected or not selected.get("id"):
        return False

    answer_quality = classify_result.get("answer_quality", "complete")
    if answer_quality in ("vague", "incomplete", "off_topic"):
        return False

    if not classify_result.get("needs_new_dimension", False):
        return False

    try:
        semantic_confidence = float(classify_result.get("confidence", 0.0))
    except (TypeError, ValueError):
        semantic_confidence = 0.0
    if semantic_confidence < 0.75:
        return False

    if _selection_confidence(state) < 0.75:
        return False

    return True


def _selection_confidence(state: dict) -> float:
    """Read a structured selection confidence without inspecting question text."""
    selected = state.get("selected_question") or {}
    raw = state.get("selection_confidence", selected.get("selection_confidence", 0.0))
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _extract_expected_focus(question: dict) -> list[str]:
    """Return structured assessment facets supplied by the question source.

    This is trace metadata for the writer/evaluator, never a text-derived
    routing heuristic.  The question bank already owns categories and tags,
    so do not re-interpret natural language with regex here.
    """
    values: list[object] = [question.get("cat1"), question.get("cat2")]
    tags = question.get("tags")
    if isinstance(tags, str):
        values.extend(tags.split(","))
    elif isinstance(tags, list):
        values.extend(tags)

    focus: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in focus:
            focus.append(normalized)
    return focus[:5]

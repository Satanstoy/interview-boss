"""Structured classification result for the interview chat agent.

The classifier is the single place where the LLM writes routing state.
Downstream nodes (tool_strategy, react_loop, stop_policy, answer) read these
fields instead of re-deriving intent/quality/retrieval from message text.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


IntentType = Literal[
    "interview_question",
    "practice_request",
    "chat",
    "follow_up",
    "end_interview",
]

AnswerQualityType = Literal[
    "complete",
    "incomplete",
    "off_topic",
    "repeated",
    "vague",
]

QuestionType = Literal[
    "project_followup",
    "knowledge_probe",
    "algorithm_coding",
    "system_design",
    "behavioral",
    "new_question",
]

TransitionStyleType = Literal[
    "natural",
    "from_candidate_keyword",
    "pivot",
    "closing",
]


class ClassifyResult(BaseModel):
    """Structured output of the classify_intent node.

    All fields have safe defaults so that a parse failure can fall back to a
    known state and the interview can continue.

    Semantic signal fields are consumed by TurnPlanner. All fields retain
    safe defaults so an LLM failure can use the explicit fallback path.
    """

    intent: IntentType = "interview_question"
    answer_quality: AnswerQualityType = "complete"
    question_type: Optional[QuestionType] = None
    should_retrieve: bool = Field(
        default=False,
        description="Whether this turn should call search_questions/draw_questions first.",
    )
    transition_style: Optional[TransitionStyleType] = "natural"
    escalation_level: int = Field(default=0)
    off_topic_streak: int = Field(default=0)
    repetition_streak: int = Field(default=0)
    requires_bank_question: bool = False

    # ── Semantic signals consumed by TurnPlanner ──
    candidate_act: Optional[str] = Field(
        default=None,
        description="候选人的语义行为: answered_question, asked_counter_question, asked_for_summary, requested_end, greeting, chitchat 等",
    )
    asked_counter_question: bool = Field(
        default=False,
        description="候选人本轮是否提出了反问",
    )
    counter_question_topic: Optional[str] = Field(
        default=None,
        description="候选人反问的主题，供 counter_writer 回答，不参与文本匹配路由",
    )
    counter_question: Optional[dict[str, str]] = Field(
        default=None,
        description="候选人实际反问的结构化证据，必须包含 text；无反问时为 null。",
    )
    asked_for_summary: bool = Field(
        default=False,
        description="候选人是否要求总结/评价",
    )
    requested_end: bool = Field(
        default=False,
        description="候选人是否要求结束面试",
    )
    needs_clarification: bool = Field(
        default=False,
        description="候选人回答含糊，需要澄清",
    )
    needs_new_dimension: bool = Field(
        default=False,
        description="候选人回答完整，需要切换到新维度",
    )
    suggested_question_type: Optional[str] = Field(
        default=None,
        description="LLM 建议的下一题类型（语义推断，非硬路由）",
    )
    confidence: float = Field(
        default=0.0,
        description="分类置信度 0.0-1.0",
    )
    evidence: Optional[str] = Field(
        default=None,
        description="分类依据的简短说明",
    )

    @field_validator("intent", "answer_quality", "question_type", "transition_style", mode="before")
    @classmethod
    def _normalize_empty_strings(cls, value: object) -> object | None:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @model_validator(mode="after")
    def _clamp_levels(self) -> "ClassifyResult":
        """Clamp numeric levels to sensible ranges after validation."""
        self.escalation_level = max(0, min(3, int(self.escalation_level)))
        self.off_topic_streak = max(0, int(self.off_topic_streak))
        self.repetition_streak = max(0, int(self.repetition_streak))
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        question = self.counter_question or {}
        text = question.get("text") if isinstance(question, dict) else None
        if not isinstance(text, str) or not text.strip():
            self.counter_question = None
            self.asked_counter_question = False
            self.counter_question_topic = None
            if self.candidate_act == "asked_counter_question":
                self.candidate_act = None
        else:
            self.counter_question = {
                "text": text.strip(),
                "topic": str(question.get("topic") or self.counter_question_topic or "").strip(),
            }
            self.asked_counter_question = True
            self.counter_question_topic = self.counter_question["topic"] or None
        return self

    def to_state(self) -> dict:
        """Return a dict that can be spread into ChatState.

        Keep None values for optional enum fields so that downstream code can
        distinguish "unset" from "natural".  Drop None for everything else.
        """
        data = self.model_dump()
        for key in ("question_type", "transition_style"):
            if data.get(key) is None:
                data.pop(key, None)
        return data

    @classmethod
    def default(cls) -> "ClassifyResult":
        """Safe fallback when LLM output cannot be parsed."""
        return cls(
            intent="interview_question",
            answer_quality="complete",
            should_retrieve=False,
            transition_style="natural",
            escalation_level=0,
            off_topic_streak=0,
            repetition_streak=0,
            requires_bank_question=False,
            # Semantic signal defaults for the LLM-failure fallback
            candidate_act=None,
            asked_counter_question=False,
            counter_question_topic=None,
            asked_for_summary=False,
            requested_end=False,
            needs_clarification=False,
            needs_new_dimension=False,
            suggested_question_type=None,
            confidence=0.0,
            evidence=None,
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> "ClassifyResult":
        """Best-effort parse; never raise."""
        if not isinstance(data, dict):
            return cls.default()
        try:
            return cls.model_validate(data)
        except Exception:
            return cls.default()

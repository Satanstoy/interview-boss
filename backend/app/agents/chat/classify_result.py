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

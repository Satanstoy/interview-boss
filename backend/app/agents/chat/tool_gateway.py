"""Typed gateway helpers for chat ReAct tools.

This module keeps LLM-facing tool execution predictable: validate inputs,
normalize question rows, and return one stable envelope shape.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ToolName = Literal[
    "search_questions",
    "draw_questions",
    "select_question",
    "load_skill",
    "list_job_positions",
]
QuestionSource = Literal["search", "draw"]


class ToolMetrics(BaseModel):
    """Best-effort tool timing metrics in milliseconds."""

    total_ms: int = 0
    fts_ms: int | None = None
    cjk_like_ms: int | None = None
    vector_ms: int | None = None
    rerank_ms: int | None = None
    db_ms: int | None = None


class ToolError(BaseModel):
    error_code: str
    message: str


class ToolQuestionItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int = Field(gt=0)
    question: str = Field(min_length=1)
    cat1: str = ""
    cat2: str = ""
    source: QuestionSource
    score: float | None = None
    reason: str
    tags: str = ""
    difficulty: str = ""
    sources: list[dict] = Field(default_factory=list)


class ToolMetadata(BaseModel):
    result_count: int = 0
    fallback_used: bool = False
    fallback_steps: list[str] = Field(default_factory=list)
    empty_reason: str | None = None
    debug_reason: str = ""
    message: str | None = None
    suggestions: list[str] = Field(default_factory=list)
    metrics: ToolMetrics = Field(default_factory=ToolMetrics)


class ToolEnvelope(BaseModel):
    ok: bool
    tool: ToolName
    # Question tools return ToolQuestionItem-shaped rows; position discovery
    # returns position rows.  The envelope deliberately keeps this boundary
    # generic so both remain one stable JSON shape.
    items: list[dict] = Field(default_factory=list)
    metadata: ToolMetadata = Field(default_factory=ToolMetadata)
    error: ToolError | None = None


class SearchQuestionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list, max_length=5)
    question_type: (
        Literal["project_followup", "knowledge_probe", "new_question"] | None
    ) = None
    limit: int = Field(default=5, ge=1, le=10)
    search_query: str | None = Field(default=None, max_length=500)
    job_position: str | None = Field(default=None, max_length=100)
    retrieval_intent: str | None = Field(default=None, max_length=100)
    negative_terms: list[str] = Field(default_factory=list, max_length=10)
    session_id: str | None = None

    @field_validator("keywords", mode="before")
    @classmethod
    def clean_keywords(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("keywords must be a list of strings")
        cleaned = []
        for item in value:
            text = str(item or "").strip()
            if text:
                cleaned.append(text[:80])
        return cleaned[:5]


class DrawQuestionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=3, ge=1, le=5)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    cat1: str | None = Field(default=None, max_length=80)
    cat2: str | None = Field(default=None, max_length=80)
    topic: str | None = Field(default=None, max_length=80)
    question_type: (
        Literal[
            "algorithm_coding",
            "project_followup",
            "knowledge_probe",
            "system_design",
            "behavioral",
            "hr",
        ]
        | None
    ) = None
    job_position: str | None = Field(default=None, max_length=100)
    session_notes: str | None = Field(default=None, max_length=4000)
    session_id: str | None = None

    @field_validator("cat1", "cat2", "topic", mode="before")
    @classmethod
    def clean_optional_text(cls, value: object) -> str | None:
        text = str(value or "").strip()
        return text[:80] if text else None


class LoadSkillInput(BaseModel):
    """Strict input contract for the skill-loading tool."""

    model_config = ConfigDict(extra="forbid")

    skill_name: Literal[
        "interview-tool-use",
        "adaptive-difficulty",
        "algorithm-coding",
        "hr-soft-skills",
        "interview-rhythm",
        "project-deep-dive",
        "theory-qa",
    ]


class SelectQuestionInput(BaseModel):
    """Only an index into the server-owned candidate list is accepted."""

    model_config = ConfigDict(extra="forbid")

    candidate_index: int = Field(default=0, ge=0, le=4)
    question_source: QuestionSource = "draw"
    session_id: str | None = None


class ListJobPositionsInput(BaseModel):
    """Position discovery has no client identity or bank-mode arguments."""

    model_config = ConfigDict(extra="forbid")


TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "search_questions": SearchQuestionsInput,
    "draw_questions": DrawQuestionsInput,
    "load_skill": LoadSkillInput,
    "select_question": SelectQuestionInput,
    "list_job_positions": ListJobPositionsInput,
}


def validate_tool_arguments(tool_name: str, raw_args: object) -> dict:
    """Parse and strictly validate one LLM tool argument object."""

    if isinstance(raw_args, str):
        parsed = json.loads(raw_args)
    elif isinstance(raw_args, dict):
        parsed = raw_args
    else:
        raise ValueError("tool arguments must be a JSON object")

    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")

    model_cls = TOOL_INPUT_MODELS.get(tool_name)
    if model_cls is None:
        raise ValueError(f"unknown tool: {tool_name}")

    model = model_cls.model_validate(parsed)
    return model.model_dump(exclude_none=True, exclude_defaults=True)


def _parse_sources(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _extract_score(raw: dict) -> float | None:
    for key in ("_combined_rank_score", "_rrf_score", "score", "rank"):
        value = raw.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


def normalize_question_item(
    raw: dict,
    *,
    source: QuestionSource,
    reason: str,
) -> dict:
    """Normalize a service row into a stable tool question item dict."""

    item = ToolQuestionItem(
        id=int(raw.get("id")),
        question=str(raw.get("question") or "").strip(),
        cat1=str(raw.get("cat1") or ""),
        cat2=str(raw.get("cat2") or ""),
        source=source,
        score=_extract_score(raw),
        reason=reason,
        tags=str(raw.get("tags") or ""),
        difficulty=str(raw.get("difficulty") or ""),
        sources=_parse_sources(raw.get("sources")),
    )
    normalized = item.model_dump()
    if raw.get("_fallback_used") is not None:
        normalized["_fallback_used"] = bool(raw.get("_fallback_used"))
    if raw.get("_fallback_reason"):
        normalized["_fallback_reason"] = str(raw.get("_fallback_reason"))
    return normalized


def build_success_envelope(
    *,
    tool: ToolName,
    items: list[dict],
    total_ms: int,
    debug_reason: str,
    fallback_used: bool = False,
    fallback_steps: list[str] | None = None,
    empty_reason: str | None = None,
    message: str | None = None,
    suggestions: list[str] | None = None,
) -> dict:
    envelope = ToolEnvelope(
        ok=True,
        tool=tool,
        items=items,
        metadata=ToolMetadata(
            result_count=len(items),
            fallback_used=fallback_used,
            fallback_steps=fallback_steps or [],
            empty_reason=empty_reason,
            debug_reason=debug_reason,
            message=message,
            suggestions=suggestions or [],
            metrics=ToolMetrics(total_ms=max(0, int(total_ms))),
        ),
        error=None,
    )
    return envelope.model_dump()


def build_error_envelope(
    *,
    tool: ToolName,
    error_code: str,
    message: str,
    total_ms: int,
    debug_reason: str,
    empty_reason: str | None = None,
    suggestions: list[str] | None = None,
) -> dict:
    envelope = ToolEnvelope(
        ok=False,
        tool=tool,
        items=[],
        metadata=ToolMetadata(
            result_count=0,
            empty_reason=empty_reason,
            debug_reason=debug_reason,
            suggestions=suggestions or [],
            metrics=ToolMetrics(total_ms=max(0, int(total_ms))),
        ),
        error=ToolError(error_code=error_code, message=message),
    )
    return envelope.model_dump()

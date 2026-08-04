"""P2 structured-turn contracts.

The legacy ReAct/HTTP surface remains compatible, while this module provides
typed facts for persistence, replay, and writer validation.  Natural-language
assistant output is deliberately absent from EvidenceBundle.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=80)
    fact_type: str = Field(min_length=1, max_length=80)
    value: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="tool", min_length=1, max_length=80)
    confidence: Literal["low", "medium", "high"] = "medium"


class QuestionRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: int = Field(gt=0)
    source: str = Field(min_length=1, max_length=80)
    rank: int = Field(default=0, ge=0)


class CoverageFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: str = Field(min_length=1, max_length=80)
    counts_toward_target: bool = False
    question_id: int | None = Field(default=None, gt=0)
    confidence: Literal["none", "low", "medium", "high"] = "none"


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, ge=1)
    tool_facts: list[ToolFact] = Field(default_factory=list)
    selected_question_ref: QuestionRef | None = None
    candidate_set_ref: str | None = None
    coverage_facts: list[CoverageFact] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    confidence: Literal["none", "low", "medium", "high"] = "none"

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def build_evidence_bundle(state: dict[str, Any]) -> EvidenceBundle:
    """Normalize tool traces and authoritative question references."""
    tool_facts: list[ToolFact] = []
    for trace in state.get("tool_calls_trace") or state.get("tool_steps") or []:
        if not isinstance(trace, dict):
            continue
        name = str(trace.get("tool_name") or trace.get("name") or "tool")
        tool_facts.append(
            ToolFact(
                tool_name=name[:80],
                fact_type="tool_result",
                value={
                    "result_count": trace.get("result_count"),
                    "selected_question_id": trace.get("selected_question_id"),
                    "status": trace.get("status"),
                },
                source="react_trace",
                confidence="medium",
            )
        )

    selected = state.get("selected_question") or {}
    selected_ref = None
    if selected.get("id"):
        selected_ref = QuestionRef(
            question_id=int(selected["id"]),
            source=str(state.get("question_source") or "unknown"),
            rank=0,
        )

    coverage_facts: list[CoverageFact] = []
    for event in state.get("coverage_events") or []:
        if not isinstance(event, dict) or not event.get("phase"):
            continue
        evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
        question_id = evidence.get("question_id")
        try:
            question_id = int(question_id) if question_id else None
        except (TypeError, ValueError):
            question_id = None
        coverage_facts.append(
            CoverageFact(
                phase=str(event["phase"]),
                counts_toward_target=bool(event.get("counts_toward_target")),
                question_id=question_id,
                confidence=str(event.get("confidence") or "none")
                if str(event.get("confidence") or "none") in {"none", "low", "medium", "high"}
                else "none",
            )
        )

    refs = [
        SourceRef(source_type="turn", source_id=str(state.get("turn_id")))
    ] if state.get("turn_id") else []
    confidence = "high" if selected_ref and selected_ref.source in {"search", "draw"} else "medium"
    if not selected_ref and not tool_facts and not coverage_facts:
        confidence = "none"
    return EvidenceBundle(
        tool_facts=tool_facts,
        selected_question_ref=selected_ref,
        candidate_set_ref=state.get("candidate_set_id"),
        coverage_facts=coverage_facts,
        source_refs=refs,
        confidence=confidence,
    )


class TurnAction(str, Enum):
    CLOSE_WITH_SUMMARY = "close_with_summary"
    ANSWER_COUNTER_QUESTION = "answer_counter_question"
    CLARIFY_CANDIDATE_ANSWER = "clarify_candidate_answer"
    ASK_SELECTED_QUESTION = "ask_selected_question"
    CONTINUE_NATURAL_FOLLOWUP = "continue_natural_followup"


class StateTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_state: str = Field(alias="from", min_length=1, max_length=80)
    to: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=240)


class WriterBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: str = Field(min_length=1, max_length=120)
    required_question_ref: QuestionRef | None = None
    constraints: list[str] = Field(default_factory=list, max_length=20)


class TurnContractV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=2, ge=2)
    action: TurnAction
    priority: int = Field(ge=1, le=100)
    question_ref: QuestionRef | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    state_transition: StateTransition
    writer_brief: WriterBrief
    contract_hash: str = ""

    @model_validator(mode="after")
    def _set_or_validate_hash(self) -> "TurnContractV2":
        payload = self.model_dump(mode="json", by_alias=True, exclude={"contract_hash"})
        expected = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.contract_hash and self.contract_hash != expected:
            raise ValueError("contract_hash does not match contract payload")
        self.contract_hash = expected
        return self

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def turn_contract_v2_from_legacy(
    legacy: dict[str, Any] | None,
    *,
    state: dict[str, Any],
    evidence: EvidenceBundle | None = None,
) -> TurnContractV2:
    """Adapt the existing TurnContract without allowing free-form routing facts."""
    legacy = legacy if isinstance(legacy, dict) else {}
    action_value = str(legacy.get("action") or TurnAction.CONTINUE_NATURAL_FOLLOWUP.value)
    try:
        action = TurnAction(action_value)
    except ValueError:
        action = TurnAction.CONTINUE_NATURAL_FOLLOWUP
    payload = legacy.get("payload") if isinstance(legacy.get("payload"), dict) else {}
    question_ref = None
    if payload.get("question_id"):
        question_ref = QuestionRef(
            question_id=int(payload["question_id"]),
            source=str(payload.get("source") or state.get("question_source") or "unknown"),
        )
    bundle = evidence or build_evidence_bundle(state)
    refs = [f"turn:{state['turn_id']}"] if state.get("turn_id") else []
    refs.extend(
        f"question:{bundle.selected_question_ref.question_id}"
        for _ in [0]
        if bundle.selected_question_ref
    )
    current_state = str((state.get("interview_state") or {}).get("current_phase") or "technical")
    target_state = "closed" if action == TurnAction.CLOSE_WITH_SUMMARY else current_state
    return TurnContractV2(
        action=action,
        priority={
            TurnAction.CLOSE_WITH_SUMMARY: 1,
            TurnAction.ANSWER_COUNTER_QUESTION: 2,
            TurnAction.CLARIFY_CANDIDATE_ANSWER: 3,
            TurnAction.ASK_SELECTED_QUESTION: 4,
            TurnAction.CONTINUE_NATURAL_FOLLOWUP: 5,
        }[action],
        question_ref=question_ref,
        evidence_refs=refs,
        state_transition={"from": current_state, "to": target_state, "reason": str(legacy.get("reason") or "")},
        writer_brief={
            "purpose": str(legacy.get("reason") or action.value)[:120],
            "required_question_ref": question_ref,
            "constraints": list(legacy.get("validation") or [])[:20],
        },
    )


def validate_writer_output(text: str, contract: TurnContractV2) -> dict[str, Any]:
    """Validate only output invariants; writer output cannot mutate the contract."""
    normalized = str(text or "").strip()
    errors: list[str] = []
    if not normalized:
        errors.append("empty_output")
    if any(marker in normalized.lower() for marker in ("thought:", "action:", "observation:")):
        errors.append("internal_marker")
    if contract.action == TurnAction.ASK_SELECTED_QUESTION and "?" not in normalized and "？" not in normalized:
        errors.append("missing_question_mark")
    return {"valid": not errors, "errors": errors, "contract_hash": contract.contract_hash}

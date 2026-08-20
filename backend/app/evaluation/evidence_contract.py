"""Stable admin-facing Case Evidence View contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


EVIDENCE_CONTRACT_VERSION = "1.0"
PAYLOAD_SCHEMA_VERSION = "1.0"


class RunReference(BaseModel):
    id: int
    status: str = "unknown"
    quality_status: str = "pending"
    target_type: str
    target_release_key: str | None = None
    evaluation_release_key: str | None = None


class ItemReference(BaseModel):
    id: int
    case_id: int | None = None
    case_key: str = ""
    scenario_key: str | None = None
    replication_index: int | None = None
    seed: int | None = None
    status: str = "unknown"
    score: float | None = None
    primary_failure_reason: str | None = None


class CaseReference(BaseModel):
    case_key: str = ""
    scenario_key: str | None = None
    input_digest: str | None = None
    candidate_input: dict[str, Any] = Field(default_factory=dict)
    admin_harness_context: dict[str, Any] = Field(default_factory=dict)
    contract: dict[str, Any] = Field(default_factory=dict)


class ExecutionStatus(BaseModel):
    status: str = "unknown"
    contract_status: str | None = None
    hard_gate_status: str | None = None
    judge_status: str | None = None
    quality_status: str = "pending"


class TargetEvidencePayload(BaseModel):
    target_type: str
    payload_schema_version: str = PAYLOAD_SCHEMA_VERSION
    output: dict[str, Any] = Field(default_factory=dict)
    trace: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)


class ObservationEvidence(BaseModel):
    status: str = "unknown"
    hard_assertions: list[dict[str, Any]] = Field(default_factory=list)
    contract_violations: list[str] = Field(default_factory=list)
    target_payload: TargetEvidencePayload


class ScoringEvidence(BaseModel):
    score: float | None = None
    deterministic_score: float | None = None
    judge_score: float | None = None
    judge_status: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CaseEvidenceView(BaseModel):
    schema_version: str = EVIDENCE_CONTRACT_VERSION
    run: RunReference
    item: ItemReference
    case: CaseReference
    execution: ExecutionStatus
    observation: ObservationEvidence
    scoring: ScoringEvidence
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _target_sections(target_type: str, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    metrics = _as_dict(payload.get("metrics"))
    trace: dict[str, Any] = {}
    output: dict[str, Any] = {}
    if target_type == "interview":
        output = {
            key: payload[key]
            for key in ("conversation_id", "turns", "errors")
            if key in payload
        }
        trace = {
            key: payload[key]
            for key in ("tool_calls", "intent_records")
            if key in payload
        }
        metrics = {
            key: payload[key]
            for key in ("tool_metrics", "intent_metrics")
            if key in payload
        }
    elif target_type in {"experience_extraction", "jd_extraction"}:
        output = {
            key: payload[key]
            for key in ("doc_type", "data", "quality")
            if key in payload
        }
        if isinstance(metrics.get("field_results"), list):
            trace["field_results"] = metrics["field_results"]
    elif target_type == "resume_analysis":
        output = {
            key: payload[key]
            for key in ("points", "optimized_text")
            if key in payload
        }
    elif target_type == "question_tagging":
        output = {
            key: payload[key]
            for key in ("tagged_rows", "quality")
            if key in payload
        }
        if isinstance(metrics.get("label_results"), list):
            trace["label_results"] = metrics["label_results"]
    else:
        output = {
            key: value
            for key, value in payload.items()
            if key not in {"metrics", "trace"}
        }
        trace = _as_dict(payload.get("trace"))
    return output, trace, metrics


def _primary_failure_reason(item: dict[str, Any], observation: dict[str, Any]) -> str | None:
    for assertion in observation.get("hard_assertions") or []:
        if isinstance(assertion, dict) and not assertion.get("passed"):
            evidence = assertion.get("evidence")
            if evidence:
                return str(evidence)
    if item.get("error_message"):
        return str(item["error_message"])
    violations = observation.get("contract_violations") or []
    return str(violations[0]) if violations else None


def _quality_status(item: dict[str, Any], run: dict[str, Any]) -> str:
    if item.get("quality_status"):
        return str(item["quality_status"])
    if item.get("status") in {"pending", "running", "queued", "created"}:
        return "pending"
    if item.get("status") == "failed" or item.get("hard_gate_status") == "failed":
        return "failed"
    if item.get("judge_status") in {"pending", "failed"}:
        return "pending"
    return "passed" if run.get("quality_status") == "passed" or item.get("status") == "completed" else "pending"


def build_case_evidence_view(
    raw: dict[str, Any],
    *,
    run: dict[str, Any],
    target_type: str,
) -> CaseEvidenceView:
    raw = _as_dict(raw)
    item = _as_dict(raw.get("item"))
    case = _as_dict(raw.get("case"))
    result = _as_dict(item.get("result"))
    observation = _as_dict(result.get("observation"))
    payload = _as_dict(observation.get("payload"))
    score = _as_dict(result.get("score"))
    snapshot = _as_dict(case.get("input_snapshot"))
    candidate_input = _as_dict(snapshot.get("candidate_view")) if "candidate_view" in snapshot else snapshot
    harness_context = _as_dict(snapshot.get("harness_context"))
    output, trace, metrics = _target_sections(target_type, payload)
    status = _quality_status(item, run)

    item_ref = ItemReference(
        id=int(item.get("id")),
        case_id=item.get("case_id"),
        case_key=str(item.get("case_key") or ""),
        scenario_key=item.get("scenario_key"),
        replication_index=item.get("replication_index"),
        seed=item.get("seed"),
        status=str(item.get("status") or "unknown"),
        score=item.get("score", score.get("score")),
        primary_failure_reason=_primary_failure_reason(item, observation),
    )
    return CaseEvidenceView(
        run=RunReference(
            id=int(run["id"]),
            status=str(run.get("status") or "unknown"),
            quality_status=str(run.get("quality_status") or status),
            target_type=target_type,
            target_release_key=run.get("target_release_key"),
            evaluation_release_key=run.get("evaluation_release_key"),
        ),
        item=item_ref,
        case=CaseReference(
            case_key=str(case.get("case_key") or item.get("case_key") or ""),
            scenario_key=case.get("scenario_key"),
            input_digest=case.get("input_digest"),
            candidate_input=candidate_input,
            admin_harness_context=harness_context,
            contract=_as_dict(case.get("contract")),
        ),
        execution=ExecutionStatus(
            status=str(item.get("status") or observation.get("status") or "unknown"),
            contract_status=item.get("contract_status"),
            hard_gate_status=item.get("hard_gate_status"),
            judge_status=item.get("judge_status") or score.get("judge_status"),
            quality_status=status,
        ),
        observation=ObservationEvidence(
            status=str(observation.get("status") or "unknown"),
            hard_assertions=[
                value for value in observation.get("hard_assertions") or [] if isinstance(value, dict)
            ],
            contract_violations=[str(value) for value in observation.get("contract_violations") or []],
            target_payload=TargetEvidencePayload(
                target_type=target_type,
                output=output,
                trace=trace,
                metrics=metrics,
            ),
        ),
        scoring=ScoringEvidence(
            score=score.get("score", item.get("score")),
            deterministic_score=score.get("deterministic_score"),
            judge_score=score.get("judge_score"),
            judge_status=score.get("judge_status") or item.get("judge_status"),
            details=score,
        ),
        attempts=[_as_dict(value) for value in raw.get("attempts") or []],
        artifacts=[_as_dict(value) for value in raw.get("artifacts") or []],
    )

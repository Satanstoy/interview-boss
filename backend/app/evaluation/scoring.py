"""Deterministic and hybrid scoring boundary before persistence."""

from __future__ import annotations

from typing import Any


DEFAULT_DETERMINISTIC_WEIGHT = 0.6
DEFAULT_JUDGE_WEIGHT = 0.4


def _bounded(value: Any) -> float | None:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _average(values: list[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return round(sum(usable) / len(usable), 4) if usable else None


def deterministic_observation_score(
    observation: dict[str, Any], contract: dict[str, Any]
) -> tuple[float | None, list[str]]:
    """Calculate the measurable part of a result without an LLM.

    Hard assertions remain gates. This score intentionally only uses continuous
    metrics, so a failed contract cannot be hidden by averaging it away.
    """
    payload = observation.get("payload") if isinstance(observation, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    contract = contract if isinstance(contract, dict) else {}
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    values: list[float | None] = []
    dimensions: list[str] = []

    if "field_coverage" in metrics:
        for key in ("field_coverage", "field_match_rate"):
            if key in metrics:
                values.append(_bounded(metrics[key]))
                dimensions.append(key)
        if contract.get("expected_questions"):
            for key in ("question_recall", "question_precision"):
                if key in metrics:
                    values.append(_bounded(metrics[key]))
                    dimensions.append(key)

    if "source_fact_coverage" in metrics:
        for key in ("source_fact_coverage", "target_alignment"):
            if key in metrics:
                values.append(_bounded(metrics[key]))
                dimensions.append(key)
        minimum = int(contract.get("min_points") or 0)
        if minimum and "improvement_point_count" in metrics:
            values.append(_bounded(float(metrics["improvement_point_count"]) / minimum))
            dimensions.append("improvement_point_coverage")

    if "taxonomy_validity" in metrics:
        for key in ("taxonomy_validity", "classification_accuracy"):
            if key in metrics:
                values.append(_bounded(metrics[key]))
                dimensions.append(key)

    tool_metrics = payload.get("tool_metrics")
    tool_metrics = tool_metrics if isinstance(tool_metrics, dict) else {}
    tool_expectations = contract.get("tool_expectations") or {}
    if tool_metrics and tool_expectations:
        missing = tool_metrics.get("required_tools_missing") or []
        values.append(1.0 if not missing else 0.0)
        dimensions.append("required_tool_coverage")
        call_count = int(tool_metrics.get("call_count") or 0)
        failed_count = int(tool_metrics.get("failed_call_count") or 0)
        values.append(max(0.0, 1.0 - failed_count / max(call_count, 1)))
        dimensions.append("tool_success_rate")
        if tool_expectations.get("require_result_used"):
            values.append(1.0 if tool_metrics.get("result_used") else 0.0)
            dimensions.append("tool_result_usage")

    intent_metrics = payload.get("intent_metrics")
    intent_metrics = intent_metrics if isinstance(intent_metrics, dict) else {}
    if intent_metrics and contract.get("intent_expectations"):
        for key in ("accuracy", "intent_coverage", "strategy_coverage"):
            if intent_metrics.get(key) is not None:
                values.append(_bounded(intent_metrics[key]))
                dimensions.append(key)

    return _average(values), dimensions


def score_observation(
    observation: dict[str, Any],
    contract: dict[str, Any],
    protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply contract and hard-gate checks without pretending to be the Judge."""
    protocol = protocol if isinstance(protocol, dict) else {}
    if not isinstance(observation, dict):
        return {
            "contract_status": "invalid",
            "hard_gate_status": "failed",
            "judge_status": "not_run",
            "score": None,
            "deterministic_score": None,
            "score_source": "none",
            "contract_violations": ["observation_not_object"],
            "hard_assertions": [],
        }

    assertions = observation.get("hard_assertions") or []
    failed_assertions = [
        assertion
        for assertion in assertions
        if isinstance(assertion, dict) and assertion.get("passed") is False
    ]
    violations = list(observation.get("contract_violations") or [])
    if failed_assertions:
        violations.extend(
            assertion.get("id", "hard_assertion_failed")
            for assertion in failed_assertions
        )

    status = observation.get("status", "unknown")
    contract_status = "valid" if status in {"succeeded", "completed"} else "invalid"
    if contract_status == "invalid":
        violations.append(f"observation_status:{status}")

    deterministic_score, deterministic_dimensions = deterministic_observation_score(
        observation, contract
    )
    deterministic_weight = float(
        protocol.get("deterministic_weight", DEFAULT_DETERMINISTIC_WEIGHT)
    )
    judge_weight = float(protocol.get("judge_weight", DEFAULT_JUDGE_WEIGHT))
    if deterministic_weight < 0 or judge_weight < 0 or deterministic_weight + judge_weight <= 0:
        deterministic_weight = DEFAULT_DETERMINISTIC_WEIGHT
        judge_weight = DEFAULT_JUDGE_WEIGHT
    weight_total = deterministic_weight + judge_weight
    return {
        "contract_status": contract_status,
        "hard_gate_status": "failed" if violations else "passed",
        "judge_status": "pending",
        "score": deterministic_score if deterministic_score is not None else observation.get("score"),
        "deterministic_score": deterministic_score,
        "deterministic_dimensions": deterministic_dimensions,
        "deterministic_weight": round(deterministic_weight / weight_total, 4),
        "judge_weight": round(judge_weight / weight_total, 4),
        "score_source": "deterministic_pending_judge" if deterministic_score is not None else "judge_pending",
        "contract_violations": violations,
        "hard_assertions": assertions,
        "payload": observation.get("payload"),
    }


def combine_hybrid_score(
    score_result: dict[str, Any], judge_score: float | None
) -> dict[str, Any]:
    """Combine fixed deterministic and Judge signals, preserving both values."""
    deterministic_score = _bounded(score_result.get("deterministic_score"))
    normalized_judge_score = _bounded(judge_score)
    deterministic_weight = float(score_result.get("deterministic_weight") or 0.0)
    judge_weight = float(score_result.get("judge_weight") or 0.0)

    if deterministic_score is not None and normalized_judge_score is not None:
        total = deterministic_weight + judge_weight or 1.0
        final_score = (deterministic_score * deterministic_weight + normalized_judge_score * judge_weight) / total
        source = "hybrid"
    elif deterministic_score is not None:
        final_score = deterministic_score
        source = "deterministic_only"
    elif normalized_judge_score is not None:
        final_score = normalized_judge_score
        source = "judge_only"
    else:
        final_score = None
        source = "none"

    return {
        "score": round(final_score, 4) if final_score is not None else None,
        "deterministic_score": deterministic_score,
        "judge_score": normalized_judge_score,
        "score_source": source,
    }

"""Deterministic scoring boundary before Judge and aggregation."""

from __future__ import annotations

from typing import Any


def score_observation(
    observation: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    """Apply contract and hard-gate checks without pretending to be the Judge."""
    if not isinstance(observation, dict):
        return {
            "contract_status": "invalid",
            "hard_gate_status": "failed",
            "judge_status": "not_run",
            "score": None,
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

    return {
        "contract_status": contract_status,
        "hard_gate_status": "failed" if violations else "passed",
        "judge_status": "pending",
        "score": observation.get("score"),
        "contract_violations": violations,
        "hard_assertions": assertions,
        "payload": observation.get("payload"),
    }

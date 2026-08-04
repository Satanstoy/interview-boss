"""Hard feasibility controller for one immutable interview distribution plan."""

from __future__ import annotations

from dataclasses import dataclass
import random

from app.agents.chat.distribution_execution import distribution_execution_from_events


MAX_CONSECUTIVE_PRIMARY_TYPE = 3
_EXCEPTIONS = {"pool_exhausted", "candidate_risk", "remaining_minimums"}


@dataclass(frozen=True)
class DistributionDecision:
    allowed_types: list[str]
    preferred_type: str | None
    forbidden_reasons: dict[str, list[str]]
    selection_reason: str
    constraint_exception: str | None = None


def decide_next_question_type(plan: dict, events: list[dict], candidate_signal: dict | None = None) -> DistributionDecision:
    signal = candidate_signal or {}
    execution = distribution_execution_from_events(plan, events)
    counts = execution["actual_counts"]
    bounds = plan["allowed_counts"]
    eligible = set(signal.get("eligible_types") or bounds)
    allowed, forbidden = [], {}
    history = [event.get("question_type") for event in events if event.get("plan_id") == plan.get("plan_id") and event.get("counts_toward_target")]
    last_type = history[-1] if history else None
    consecutive = 0
    for value in reversed(history):
        if value != last_type:
            break
        consecutive += 1
    exception = signal.get("constraint_exception") if signal.get("constraint_exception") in _EXCEPTIONS and signal.get("exception_evidence") else None
    for question_type, bound in bounds.items():
        reasons = []
        if question_type not in eligible:
            reasons.append("not_eligible")
        if counts.get(question_type, 0) >= bound["max"]:
            reasons.append("maximum_reached")
        if question_type == last_type and consecutive >= MAX_CONSECUTIVE_PRIMARY_TYPE and not exception:
            reasons.append("max_consecutive_primary_type")
        if reasons:
            forbidden[question_type] = reasons
        else:
            allowed.append(question_type)
    deficits = {key: plan["soft_target_counts"].get(key, 0) - counts.get(key, 0) for key in allowed}
    top = max(deficits.values(), default=None)
    tied = sorted(key for key, value in deficits.items() if value == top)
    preferred = random.Random(f"{plan.get('random_seed')}:{execution['actual_primary_count']}").choice(tied) if tied else None
    return DistributionDecision(allowed, preferred, forbidden, "target_deficit", exception)

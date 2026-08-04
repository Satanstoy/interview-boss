"""Pure read model for a frozen distribution plan and append-only events."""

from __future__ import annotations


def distribution_execution_from_events(plan: dict, events: list[dict]) -> dict:
    plan_id = plan.get("plan_id")
    types = tuple(plan.get("soft_target_counts", {}))
    actual_counts = {question_type: 0 for question_type in types}
    terminal = None
    for event in events:
        if not isinstance(event, dict) or event.get("plan_id") != plan_id:
            continue
        if event.get("type") == "distribution_result":
            terminal = event
            continue
        question_type = event.get("question_type")
        if event.get("counts_toward_target") is True and question_type in actual_counts:
            actual_counts[question_type] += 1
    actual_primary_count = sum(actual_counts.values())
    if actual_primary_count >= int(plan.get("target_question_count", 0)):
        status = "completed"
    elif terminal and terminal.get("status") == "incomplete":
        status = "incomplete"
    else:
        status = "in_progress"
    return {
        "plan_id": plan_id,
        "status": status,
        "actual_counts": actual_counts,
        "actual_primary_count": actual_primary_count,
        "remaining_primary_count": max(0, int(plan.get("target_question_count", 0)) - actual_primary_count),
        "result": terminal,
    }

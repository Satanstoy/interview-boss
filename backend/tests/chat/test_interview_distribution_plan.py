"""Conversation plans are immutable snapshots and execution is event-derived."""

import json


def _plan(target=3):
    return {
        "plan_id": "plan-1",
        "target_question_count": target,
        "soft_target_counts": {
            "project_followup": 1,
            "knowledge_probe": 1,
            "algorithm_coding": 1,
            "system_design": 0,
            "behavioral": 0,
        },
        "allowed_counts": {name: {"min": 0, "max": target} for name in (
            "project_followup", "knowledge_probe", "algorithm_coding", "system_design", "behavioral"
        )},
    }


def test_execution_is_in_progress_until_an_explicit_terminal_result():
    from app.agents.chat.distribution_execution import distribution_execution_from_events

    plan = _plan()
    active = distribution_execution_from_events(plan, [
        {"plan_id": "plan-1", "question_type": "knowledge_probe", "counts_toward_target": True}
    ])
    incomplete = distribution_execution_from_events(plan, [
        {"plan_id": "plan-1", "type": "distribution_result", "status": "incomplete", "reason": "candidate_requested_end"}
    ])

    assert active["status"] == "in_progress"
    assert incomplete["status"] == "incomplete"


def test_compile_plan_snapshots_default_and_allocates_exact_integer_total(test_db):
    from app.services.interview_distribution import compile_distribution_plan, refresh_distribution_scope

    refresh_distribution_scope(test_db, "public_job_position", "Agent开发")
    plan = compile_distribution_plan(
        test_db, user_id=1, job_position="Agent开发", request_override={
            "mode": "custom", "target_question_count": 8,
            "custom_distribution": {
                "project_followup": 0.25, "knowledge_probe": 0.25, "algorithm_coding": 0.25,
                "system_design": 0.125, "behavioral": 0.125,
            },
        }, preference=None,
    )

    assert plan["target_question_count"] == 8
    assert sum(plan["soft_target_counts"].values()) == 8
    assert plan["distribution"] == plan["expected_distribution"]


def test_conversation_execution_reads_all_events_when_primary_target_exceeds_bounded_context(test_db):
    """The 100-message LLM context limit must not truncate execution facts."""
    from app.services.chat_service import get_conversation

    plan = _plan(target=50)
    plan["soft_target_counts"] = {
        "project_followup": 0,
        "knowledge_probe": 50,
        "algorithm_coding": 0,
        "system_design": 0,
        "behavioral": 0,
    }
    test_db.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
        (701, "distribution-history-test", "hash"),
    )
    test_db.execute(
        "INSERT INTO chat_conversations (id, user_id, mode, title, metadata) VALUES (?, ?, ?, ?, ?)",
        (
            "distribution-history-conversation",
            701,
            "free_practice",
            "history test",
            json.dumps({"interview_config": {"distribution_plan": plan}}),
        ),
    )
    for index in range(100):
        test_db.execute(
            "INSERT INTO chat_messages (conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (
                "distribution-history-conversation",
                "assistant",
                f"unbound {index}",
                json.dumps({"coverage_events": [{"plan_id": "plan-1", "counts_toward_target": False}]}),
            ),
        )
    for index in range(50):
        test_db.execute(
            "INSERT INTO chat_messages (conversation_id, role, content, metadata) VALUES (?, ?, ?, ?)",
            (
                "distribution-history-conversation",
                "assistant",
                f"bound {index}",
                json.dumps(
                    {
                        "coverage_events": [
                            {
                                "plan_id": "plan-1",
                                "question_type": "knowledge_probe",
                                "counts_toward_target": True,
                            }
                        ]
                    }
                ),
            ),
        )
    test_db.commit()

    conversation = get_conversation("distribution-history-conversation", user_id=701)

    assert conversation["distribution_execution"]["actual_primary_count"] == 50
    assert conversation["distribution_execution"]["status"] == "completed"

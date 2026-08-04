from app.agents.chat.distribution_controller import decide_next_question_type


def _plan():
    types = ("project_followup", "knowledge_probe", "algorithm_coding", "system_design", "behavioral")
    return {"plan_id": "p", "random_seed": "seed", "target_question_count": 5,
            "soft_target_counts": {key: 1 for key in types},
            "allowed_counts": {key: {"min": 0, "max": 5} for key in types}}


def _events(*types):
    return [{"plan_id": "p", "question_type": value, "counts_toward_target": True} for value in types]


def test_fourth_consecutive_type_is_rejected_when_another_is_feasible():
    decision = decide_next_question_type(_plan(), _events("knowledge_probe", "knowledge_probe", "knowledge_probe"), {"eligible_types": ["knowledge_probe", "algorithm_coding"]})
    assert "knowledge_probe" not in decision.allowed_types
    assert decision.preferred_type == "algorithm_coding"


def test_documented_exception_allows_consecutive_type_with_evidence():
    decision = decide_next_question_type(_plan(), _events("knowledge_probe", "knowledge_probe", "knowledge_probe"), {"eligible_types": ["knowledge_probe"], "constraint_exception": "pool_exhausted", "exception_evidence": {"pool": 0}})
    assert decision.preferred_type == "knowledge_probe"
    assert decision.constraint_exception == "pool_exhausted"

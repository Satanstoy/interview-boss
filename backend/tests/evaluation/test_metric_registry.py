from app.evaluation.metric_registry import (
    TARGET_METRIC_DICTIONARY,
    build_progress_distribution,
    build_metric_cards,
    get_target_metric_definition,
)


EXPECTED_TARGETS = {
    "interview",
    "experience_extraction",
    "jd_extraction",
    "resume_analysis",
    "question_tagging",
}


def test_metric_dictionary_covers_all_supported_targets_with_business_labels():
    assert set(TARGET_METRIC_DICTIONARY) == EXPECTED_TARGETS

    for target_type, definition in TARGET_METRIC_DICTIONARY.items():
        assert definition["label"]
        assert 3 <= len(definition["core_metrics"]) <= 5
        assert definition["metrics"]
        assert all(metric["label"] for metric in definition["metrics"].values())
        assert all(metric["unit"] for metric in definition["metrics"].values())
        assert all("threshold" in definition["metrics"][key] for key in definition["core_metrics"])


def test_metric_registry_does_not_expose_internal_field_names_as_primary_labels():
    internal_words = {"tool_metrics", "intent_metrics", "hard_gate_status", "judge_status"}
    labels = {
        metric["label"]
        for definition in TARGET_METRIC_DICTIONARY.values()
        for metric in definition["metrics"].values()
    }

    assert not labels & internal_words
    assert get_target_metric_definition("interview")["label"] == "模拟面试"


def test_build_metric_cards_returns_stable_core_order_and_status():
    cards = build_metric_cards(
        "interview",
        {
            "tool": {"call_count": 4, "failed_call_count": 1, "result_used_rate": 0.75},
            "intent": {"intent_coverage": 0.67, "accuracy": 0.5},
        },
        thresholds={"tool_success_rate": 0.9, "intent_coverage": 0.8},
    )

    assert [card["key"] for card in cards] == [
        "tool_success_rate",
        "tool_result_used_rate",
        "intent_coverage",
        "intent_accuracy",
    ]
    assert cards[0]["value"] == 0.75
    assert cards[0]["status"] == "poor"
    assert cards[2]["label"] == "用户意图理解覆盖率"
    assert cards[2]["status"] == "poor"


def test_build_metric_cards_uses_target_defaults_when_no_override_is_given():
    cards = build_metric_cards(
        "interview",
        {
            "tool": {"call_count": 4, "failed_call_count": 1},
            "intent": {"intent_coverage": 0.67, "accuracy": 0.9},
        },
    )

    assert cards[0]["threshold"] == 0.8
    assert cards[0]["status"] == "poor"
    assert cards[2]["threshold"] == 0.8
    assert cards[2]["status"] == "poor"


def test_build_progress_distribution_separates_execution_and_quality_outcomes():
    distribution = build_progress_distribution(
        [
            {"status": "completed", "contract_status": "valid", "hard_gate_status": "passed", "score": 0.92},
            {"status": "completed", "contract_status": "valid", "hard_gate_status": "passed", "score": 0.58},
            {"status": "failed", "contract_status": "invalid", "hard_gate_status": "failed", "score": None},
            {"status": "running", "contract_status": "pending", "hard_gate_status": "pending", "score": None},
        ],
        poor_score_below=0.6,
    )

    assert distribution == {
        "total": 4,
        "passed": 1,
        "poor": 1,
        "failed": 1,
        "pending": 1,
    }

from app.evaluation.evidence_contract import build_case_evidence_view


def test_case_evidence_view_has_stable_envelope_and_target_payload():
    view = build_case_evidence_view(
        {
            "item": {
                "id": 201,
                "case_id": 301,
                "case_key": "tool_timing",
                "scenario_key": "tool_timing",
                "replication_index": 1,
                "seed": 123,
                "status": "completed",
                "contract_status": "valid",
                "hard_gate_status": "failed",
                "judge_status": "succeeded",
                "score": 0.69,
                "result": {
                    "observation": {
                        "status": "succeeded",
                        "payload": {
                            "conversation_id": "c-1",
                            "turns": [{"turn": 1}],
                            "tool_calls": [{"tool_name": "search_questions", "ok": True}],
                            "tool_metrics": {"call_count": 1, "failed_call_count": 0},
                            "intent_metrics": {"intent_coverage": 0.8},
                        },
                        "hard_assertions": [
                            {"id": "tool_calls_valid", "passed": False, "evidence": "工具时机不符合"}
                        ],
                        "contract_violations": ["tool_calls_valid"],
                    },
                    "score": {"score": 0.69, "judge_score": 0.72, "judge_status": "succeeded"},
                },
            },
            "case": {
                "case_key": "tool_timing",
                "scenario_key": "tool_timing",
                "input_snapshot": {
                    "candidate_view": {"opening": "你好"},
                    "harness_context": {"max_turns": 8},
                },
                "contract": {"hard_assertions": [{"id": "tool_calls_valid"}]},
                "input_digest": "digest-1",
            },
            "attempts": [],
            "artifacts": [],
        },
        run={
            "id": 12,
            "status": "completed",
            "quality_status": "failed",
            "target_type": "interview",
            "target_release_key": "interview-agent@1.0",
            "evaluation_release_key": "interview-eval@1.0",
        },
        target_type="interview",
    )

    assert view.schema_version == "1.0"
    assert view.run.id == 12
    assert view.item.case_key == "tool_timing"
    assert view.case.candidate_input == {"opening": "你好"}
    assert view.case.admin_harness_context == {"max_turns": 8}
    assert view.observation.target_payload.output["conversation_id"] == "c-1"
    assert view.observation.target_payload.trace["tool_calls"][0]["tool_name"] == "search_questions"
    assert view.observation.target_payload.metrics["tool_metrics"]["call_count"] == 1
    assert view.execution.hard_gate_status == "failed"
    assert view.item.primary_failure_reason == "工具时机不符合"


def test_case_evidence_view_keeps_non_interview_outputs_visible():
    view = build_case_evidence_view(
        {
            "item": {
                "id": 2,
                "case_id": 3,
                "case_key": "extract-1",
                "status": "completed",
                "result": {
                    "observation": {
                        "payload": {
                            "doc_type": "jd",
                            "data": {"岗位": "后端工程师"},
                            "quality": {"score": 0.9},
                            "metrics": {"field_coverage": 0.8},
                        },
                        "hard_assertions": [],
                        "contract_violations": [],
                    },
                    "score": {"score": 0.8},
                },
            },
            "case": {"input_snapshot": {}, "contract": {}},
            "attempts": [],
            "artifacts": [],
        },
        run={"id": 1, "status": "completed", "quality_status": "passed", "target_type": "jd_extraction"},
        target_type="jd_extraction",
    )

    assert view.observation.target_payload.output["data"] == {"岗位": "后端工程师"}
    assert view.observation.target_payload.output["quality"] == {"score": 0.9}
    assert view.observation.target_payload.metrics["field_coverage"] == 0.8

"""LLM-as-a-Judge contract for the Evaluation Control Plane."""

import asyncio
import importlib

import pytest


def test_judge_prompt_contains_contract_and_observation_without_hiding_model():
    judge = importlib.import_module("app.evaluation.judge")

    prompt = judge.build_judge_prompt(
        case_key="smoke",
        contract={
            "facts": ["candidate has RAG experience"],
            "actions": ["asks a follow-up"],
            "boundaries": ["does not reveal internal rubric"],
            "quality_requirements": ["natural pacing"],
            "hard_assertions": [{"id": "closing_present"}],
            "rubric": {"flow": {"weight": 1, "anchors": {"1": "bad", "5": "excellent"}}},
        },
        observation={"status": "succeeded", "payload": {"turns": [{"assistant": "hello"}]}},
        judge_model="fixed-judge-model",
    )

    assert "fixed-judge-model" in prompt
    assert "closing_present" in prompt
    assert "natural pacing" in prompt
    assert '"dimensions"' in prompt
    assert '"overall_score"' in prompt


def test_parse_judge_response_normalizes_dimension_scores():
    judge = importlib.import_module("app.evaluation.judge")

    result = judge.parse_judge_response(
        '{"dimensions":{"flow":{"score":4,"reasoning":"smooth"}},'
        '"overall_score":0.75,"critical_issues":[],"highlights":["clear"]}',
        rubric={"flow": {"weight": 1}},
        judge_model="fixed-judge-model",
    )

    assert result["judge_status"] == "succeeded"
    assert result["score"] == 0.75
    assert result["dimensions"]["flow"]["score"] == 4
    assert result["judge_model"] == "fixed-judge-model"


def test_parse_judge_response_rejects_missing_rubric_dimension():
    judge = importlib.import_module("app.evaluation.judge")

    with pytest.raises(ValueError, match="缺少维度"):
        judge.parse_judge_response(
            '{"dimensions":{},"overall_score":0.5}',
            rubric={"flow": {"weight": 1}},
            judge_model="fixed-judge-model",
        )


def test_parse_judge_response_aggregates_score_from_dimensions():
    judge = importlib.import_module("app.evaluation.judge")

    result = judge.parse_judge_response(
        '{"dimensions":{"flow":{"score":4,"reasoning":"evidence"}},"overall_score":0.1}',
        rubric={"flow": {"weight": 1}},
        judge_model="fixed-judge-model",
    )

    assert result["score"] == 0.75
    assert result["judge_reported_score"] == 0.1


def test_judge_call_failure_is_explicit_and_not_rule_based_fallback(monkeypatch):
    judge = importlib.import_module("app.evaluation.judge")

    async def fail_call(*args, **kwargs):
        raise RuntimeError("judge unavailable")

    monkeypatch.setattr(judge, "_call_llm_with_retry", fail_call)
    result = asyncio.run(
        judge.judge_observation(
            case_key="smoke",
            contract={"rubric": {"flow": {"weight": 1}}},
            observation={"status": "succeeded", "payload": {}},
            judge_model="fixed-judge-model",
        )
    )

    assert result["judge_status"] == "failed"
    assert result["score"] is None
    assert result["judge_model"] == "fixed-judge-model"
    assert "judge unavailable" in result["error"]


def test_judge_requests_zero_temperature(monkeypatch):
    judge = importlib.import_module("app.evaluation.judge")
    calls = []

    async def fake_call(*args, **kwargs):
        calls.append(kwargs)
        return '{"dimensions":{"flow":{"score":4,"reasoning":"evidence"}},"overall_score":0.75}'

    monkeypatch.setattr(judge, "_call_llm_with_retry", fake_call)
    result = asyncio.run(
        judge.judge_observation(
            case_key="smoke",
            contract={"rubric": {"flow": {"weight": 1}}},
            observation={"status": "succeeded", "payload": {}},
            judge_model="fixed-judge-model",
        )
    )

    assert result["judge_status"] == "succeeded"
    assert calls[0]["temperature"] == 0


def test_interview_adapter_keeps_rubric_out_of_candidate_view():
    adapter_module = importlib.import_module("app.evaluation.interview_adapter")
    adapter = adapter_module.InterviewE2EAdapter()

    prepared = asyncio.run(
        adapter.prepare(
            {
                "candidate_view": {"profile": "RAG engineer", "opening": "hello"},
                "harness_context": {"max_turns": 2, "behavior_injections": {"2": "ask a counter question"}},
                "_eval_contract": {"rubric": {"flow": {"weight": 1}}},
                "_eval_seed": 123,
                "_eval_replication_index": 2,
            },
            {"release_key": "interview-agent@1.0", "created_by": 1},
        )
    )

    assert prepared["candidate_view"] == {"profile": "RAG engineer", "opening": "hello"}
    assert "rubric" not in prepared["candidate_view"]
    assert prepared["contract"]["rubric"]["flow"]["weight"] == 1
    assert prepared["seed"] == 123
    assert prepared["behavior_injections"][2] == "ask a counter question"

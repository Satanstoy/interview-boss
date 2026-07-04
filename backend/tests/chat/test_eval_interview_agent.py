from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_eval_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "eval_interview_agent.py"
    spec = importlib.util.spec_from_file_location("eval_interview_agent", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scenarios_cover_design_matrix_and_load_candidate_skills():
    module = _load_eval_module()

    assert set(module.SCENARIOS) == {
        "long_session_mid",
        "long_session_senior",
        "long_session_jd",
        "error_correction",
        "early_close_guard",
        "proper_end",
        "insufficient_evidence",
        "counter_question",
    }
    assert module.SCENARIOS["long_session_mid"].max_turns == 16
    assert module.SCENARIOS["long_session_senior"].max_turns == 20
    assert module.SCENARIOS["error_correction"].active_skills == [
        "candidate-rhythm",
        "error-injection",
        "project-storytelling",
        "knowledge-answer",
    ]

    candidate = module.SmartCandidateAgent(
        module.MID_LEVEL_PERSONA,
        ["candidate-rhythm", "project-storytelling"],
        module.CandidateLLMConfig(
            api_key="test-key",
            base_url="https://llm.example.test/v1",
            model="test-model",
            timeout=30,
        ),
    )

    system_prompt = candidate.messages[0]["content"]
    assert "candidate-rhythm" in system_prompt
    assert "project-storytelling" in system_prompt
    assert "2 年 RAG + Agent 开发经验" in system_prompt


def test_extract_metrics_collects_sse_contract_and_detects_duplicates(monkeypatch):
    module = _load_eval_module()
    monkeypatch.setattr(
        module,
        "query_asked_questions_db",
        lambda conv_id: [101, 202] if conv_id == "conv-1" else [],
    )

    turns = [
        {
            "turn": 1,
            "user": "我做过 RAG。",
            "assistant": "请继续介绍。",
            "events": [
                {"type": "thinking", "data": {"text": "分析候选人回答"}},
                {"type": "tool_step", "data": {"tool": "search_questions"}},
                {"type": "selected_question", "data": {"question_id": 101}},
                {"type": "retrieved", "questions": [{"id": 101}, {"id": 202}]},
            ],
            "latency_sec": 1.5,
        },
        {
            "turn": 2,
            "user": "继续。",
            "assistant": "整体表现不错，下面做面试总结。",
            "events": [
                {"type": "tool_step", "data": {"tool": "draw_questions"}},
                {"type": "candidate_questions", "data": {"ids": [202, 303]}},
                {"type": "error", "message": "boom"},
            ],
            "latency_sec": 1.2,
        },
    ]

    metrics = module.extract_metrics(turns, "conv-1")

    assert metrics["turn_count"] == 2
    assert metrics["tool_names"] == ["search_questions", "draw_questions"]
    assert metrics["tool_count"] == 2
    assert metrics["selected_ids"] == [101]
    assert metrics["candidate_ids"] == [101, 202, 202, 303]
    assert metrics["cross_turn_duplicate_candidates"] == [202]
    assert metrics["asked_questions"] == [101, 202]
    assert metrics["has_summary"] is True
    assert metrics["thinking_turns"] == 1
    assert len(metrics["errors"]) == 1
    assert metrics["thinking_chars"] == len("分析候选人回答")


def test_score_scenario_weights_passed_checks_and_writes_reports(tmp_path):
    module = _load_eval_module()
    metrics = {
        "turn_count": 2,
        "tool_count": 2,
        "selected_ids": [101],
        "asked_questions": [101],
        "cross_turn_duplicate_candidates": [],
        "has_summary": True,
        "errors": [],
        "thinking_turns": 1,
        "recent_turns": [{"assistant": "BERT 是 encoder-only 判别式模型，不是生成式模型。"}],
        "correction_in_output_count": 1,
    }

    scores = module.score_scenario(module.SCENARIOS["long_session_mid"], metrics)

    assert scores["passed"] is True
    assert scores["passed_weight"] == scores["total_weight"]
    assert scores["items"]["tool_call_rate"]["passed"] is True

    result = {
        "scenario_id": "long_session_mid",
        "conversation_id": "conv-1",
        "turns": [
            {
                "turn": 1,
                "user": "候选人回答",
                "assistant": "面试官追问",
                "events": [{"type": "tool_step", "data": {"tool": "search_questions"}}],
                "latency_sec": 1.23,
            }
        ],
        "metrics": metrics,
        "scores": scores,
    }

    json_path, md_path = module.write_reports(result, tmp_path, timestamp="20260704_120000")

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["scenario_id"] == "long_session_mid"
    md_text = md_path.read_text(encoding="utf-8")
    assert "# 评测报告：long_session_mid" in md_text
    assert "| tool_call_rate | PASS |" in md_text
    assert "search_questions" in md_text


def test_candidate_config_accepts_design_and_existing_env_names(monkeypatch):
    module = _load_eval_module()
    parser = module._build_parser()

    monkeypatch.setenv("CANDIDATE_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CANDIDATE_LLM_BASE_URL", "https://design-env.example/v1")
    monkeypatch.setenv("CANDIDATE_LLM_MODEL", "mimo-v2.5")
    args = parser.parse_args([])

    config = module._resolve_candidate_config(args)

    assert config.api_key == "test-key"
    assert config.base_url == "https://design-env.example/v1"
    assert config.model == "mimo-v2.5"

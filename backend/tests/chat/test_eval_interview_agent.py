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
        "project-storytelling",
        "knowledge-answer",
    ]

    # Verify candidate_prompt_overrides are set for scenarios that need them
    assert module.SCENARIOS["early_close_guard"].candidate_prompt_overrides is not None
    assert 3 in module.SCENARIOS["early_close_guard"].candidate_prompt_overrides
    assert module.SCENARIOS["error_correction"].candidate_prompt_overrides is not None
    assert 3 in module.SCENARIOS["error_correction"].candidate_prompt_overrides
    assert module.SCENARIOS["counter_question"].candidate_prompt_overrides is not None
    assert 4 in module.SCENARIOS["counter_question"].candidate_prompt_overrides
    assert module.SCENARIOS["insufficient_evidence"].candidate_prompt_overrides is not None
    assert 3 in module.SCENARIOS["insufficient_evidence"].candidate_prompt_overrides

    # Verify long session scenarios have end signal at last turn
    assert 16 in module.SCENARIOS["long_session_mid"].candidate_prompt_overrides
    assert 20 in module.SCENARIOS["long_session_senior"].candidate_prompt_overrides
    assert 16 in module.SCENARIOS["long_session_jd"].candidate_prompt_overrides
    assert 10 in module.SCENARIOS["proper_end"].candidate_prompt_overrides

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


# ── LLM Judge Tests ──────────────────────────────────────


def test_build_conversation_transcript_short():
    """Short transcript should not be truncated."""
    module = _load_eval_module()
    turns = [
        {"user": "我做过 RAG。", "assistant": "请继续。", "events": []},
        {"user": "用的 Faiss。", "assistant": "不错。", "events": []},
    ]
    transcript = module._build_conversation_transcript(turns)
    assert "候选人: 我做过 RAG。" in transcript
    assert "面试官: 请继续。" in transcript
    assert "省略" not in transcript


def test_build_conversation_transcript_long_truncated():
    """Long transcript should be truncated from the middle, preserving head and tail."""
    module = _load_eval_module()
    turns = [
        {"user": f"回答第{i}轮" + "x" * 500, "assistant": f"追问第{i}轮" + "y" * 500, "events": []}
        for i in range(20)
    ]
    transcript = module._build_conversation_transcript(turns, max_chars=2000)
    assert "省略" in transcript
    # Should preserve beginning (first turn) and end (last turn's assistant)
    assert "回答第0轮" in transcript
    assert "追问第19轮" in transcript


def test_build_conversation_transcript_with_tool_tags():
    """Tool calls should be annotated in transcript."""
    module = _load_eval_module()
    turns = [
        {
            "user": "介绍一下项目",
            "assistant": "请看这道题。",
            "events": [
                {"type": "tool_step", "data": {"tool": "search_questions"}},
            ],
        },
    ]
    transcript = module._build_conversation_transcript(turns)
    assert "[tools: search_questions]" in transcript


def test_build_scoring_criteria_text():
    """Scoring criteria should be formatted as readable text."""
    module = _load_eval_module()
    scenario = module.SCENARIOS["long_session_mid"]
    text = module._build_scoring_criteria_text(scenario)
    assert "tool_call_rate" in text
    assert "weight=" in text
    assert "至少 60%" in text


def test_llm_score_scenario_parses_json_response(monkeypatch):
    """LLM judge should parse structured JSON response into score items."""
    module = _load_eval_module()
    scenario = module.SCENARIOS["long_session_mid"]
    turns = [
        {"user": "我做过 RAG。", "assistant": "请继续介绍。", "events": [
            {"type": "tool_step", "data": {"tool": "search_questions"}},
        ], "latency_sec": 1.5},
    ]
    metrics = {
        "turn_count": 1,
        "tool_count": 1,
        "tool_names": ["search_questions"],
        "selected_ids": [101],
        "cross_turn_duplicate_candidates": [],
        "asked_questions": [101],
        "has_summary": False,
        "thinking_turns": 0,
        "errors": [],
        "correction_in_output_count": 0,
        "early_close_refused": False,
        "has_insufficient_evidence_marker": False,
        "counter_question_answered": False,
    }

    judge_response = json.dumps({
        "dimensions": {
            "tool_call_rate": {"passed": True, "score": 1.0, "reasoning": "1/1=100%>60%", "evidence": "T0: search_questions"},
            "selected_question_present": {"passed": True, "score": 1.0, "reasoning": "有1个selected", "evidence": "selected_id=101"},
            "asked_questions_recorded": {"passed": True, "score": 1.0, "reasoning": "DB有记录", "evidence": "asked=101"},
            "no_cross_turn_duplicate_candidates": {"passed": True, "score": 1.0, "reasoning": "无重复", "evidence": "N/A"},
            "has_summary": {"passed": False, "score": 0.0, "reasoning": "只有1轮，无总结", "evidence": "N/A"},
            "no_sse_errors": {"passed": True, "score": 1.0, "reasoning": "无错误", "evidence": "N/A"},
            "thinking_transparency": {"passed": False, "score": 0.0, "reasoning": "无thinking事件", "evidence": "N/A"},
        },
        "overall_score": 0.71,
        "overall_passed": False,
        "critical_issues": ["无结构化总结"],
        "highlights": ["工具调用率达标"],
    }, ensure_ascii=False)

    def mock_call(config, messages, **kwargs):
        return judge_response

    monkeypatch.setattr(module, "_call_openai_compatible_chat", mock_call)

    judge_config = module.JudgeLLMConfig(api_key="test", base_url="http://test", model="gpt-4o", timeout=30)
    result = module.llm_score_scenario(scenario, turns, metrics, judge_config)

    assert result["passed"] is False
    assert result["items"]["tool_call_rate"]["passed"] is True
    assert result["items"]["tool_call_rate"]["reasoning"] == "1/1=100%>60%"
    assert result["items"]["has_summary"]["passed"] is False
    assert result["critical_issues"] == ["无结构化总结"]
    assert result["highlights"] == ["工具调用率达标"]
    assert result["judge_model"] == "gpt-4o"


def test_llm_score_scenario_fallback_on_parse_error(monkeypatch):
    """LLM judge should fallback to rule-based on JSON parse error with fallback notice."""
    module = _load_eval_module()
    scenario = module.SCENARIOS["long_session_mid"]
    turns = [{"user": "test", "assistant": "ok", "events": [], "latency_sec": 1.0}]
    metrics = {
        "turn_count": 1, "tool_count": 0, "tool_names": [], "selected_ids": [],
        "cross_turn_duplicate_candidates": [], "asked_questions": [], "has_summary": False,
        "thinking_turns": 0, "errors": [], "correction_in_output_count": 0,
        "early_close_refused": False, "has_insufficient_evidence_marker": False,
        "counter_question_answered": False,
    }

    def mock_call(config, messages, **kwargs):
        return "This is not valid JSON at all!"

    monkeypatch.setattr(module, "_call_openai_compatible_chat", mock_call)

    judge_config = module.JudgeLLMConfig(api_key="test", base_url="http://test", model="gpt-4o", timeout=30)
    result = module.llm_score_scenario(scenario, turns, metrics, judge_config)

    # Should fallback to rule-based and still return valid structure
    assert "items" in result
    assert "passed" in result
    assert result.get("judge_error") is not None
    # Must include fallback notice
    assert "fallback_notice" in result
    assert "降级" in result["fallback_notice"]
    assert "规则评分" in result["fallback_notice"]


def test_llm_generate_report_uses_llm_output(monkeypatch):
    """LLM report generation should return LLM-generated markdown."""
    module = _load_eval_module()
    result = {
        "scenario_id": "long_session_mid",
        "turns": [{"turn": 1, "user": "test", "assistant": "ok", "events": [], "latency_sec": 1.0}],
        "metrics": {
            "turn_count": 1, "tool_count": 0, "tool_names": [], "selected_ids": [],
            "cross_turn_duplicate_candidates": [], "errors": [], "thinking_turns": 0,
        },
        "scores": {
            "passed": True, "overall_score": 0.85, "judge_model": "gpt-4o",
            "items": {
                "tool_call_rate": {"passed": True, "score": 1.0, "reasoning": "达标"},
            },
            "critical_issues": [],
            "highlights": ["工具调用正常"],
        },
    }

    def mock_call(config, messages, **kwargs):
        return "# 评测报告\n\n面试质量良好。"

    monkeypatch.setattr(module, "_call_openai_compatible_chat", mock_call)

    judge_config = module.JudgeLLMConfig(api_key="test", base_url="http://test", model="gpt-4o", timeout=30)
    report = module.llm_generate_report(result, judge_config)

    assert "# 评测报告" in report
    assert "面试质量良好" in report


def test_llm_generate_report_fallback_on_error(monkeypatch):
    """LLM report should fallback to template with fallback notice."""
    module = _load_eval_module()
    result = {
        "scenario_id": "long_session_mid",
        "turns": [{"turn": 1, "user": "test", "assistant": "ok", "events": [], "latency_sec": 1.0}],
        "metrics": {
            "turn_count": 1, "tool_count": 0, "tool_names": [], "selected_ids": [],
            "cross_turn_duplicate_candidates": [], "errors": [], "thinking_turns": 0,
        },
        "scores": {
            "passed": True, "overall_score": 0.85, "judge_model": "gpt-4o",
            "items": {
                "tool_call_rate": {"passed": True, "score": 1.0, "reasoning": "达标", "description": "test"},
            },
            "critical_issues": [], "highlights": [],
        },
    }

    def mock_call(config, messages, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(module, "_call_openai_compatible_chat", mock_call)

    judge_config = module.JudgeLLMConfig(api_key="test", base_url="http://test", model="gpt-4o", timeout=30)
    report = module.llm_generate_report(result, judge_config)

    # Should fallback to template report with fallback notice
    assert "降级提醒" in report
    assert "LLM 报告生成失败" in report
    assert "# 评测报告：long_session_mid" in report


def test_resolve_judge_config_returns_none_without_key(monkeypatch):
    """No API key at all → returns None (falls back to rule-based)."""
    module = _load_eval_module()
    parser = module._build_parser()
    monkeypatch.delenv("JUDGE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    args = parser.parse_args([])

    config = module._resolve_judge_config(args)
    assert config is None


def test_resolve_judge_config_returns_none_when_explicitly_disabled(monkeypatch):
    """--no-llm-judge → returns None even if API key exists."""
    module = _load_eval_module()
    parser = module._build_parser()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    args = parser.parse_args(["--no-llm-judge"])

    config = module._resolve_judge_config(args)
    assert config is None


def test_resolve_judge_config_from_env(monkeypatch):
    """Judge config should resolve from environment variables."""
    module = _load_eval_module()
    parser = module._build_parser()
    monkeypatch.setenv("JUDGE_OPENAI_API_KEY", "judge-key")
    monkeypatch.setenv("JUDGE_LLM_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("JUDGE_LLM_MODEL", "gpt-4o-mini")
    args = parser.parse_args([])

    config = module._resolve_judge_config(args)

    assert config is not None
    assert config.api_key == "judge-key"
    assert config.base_url == "https://judge.example/v1"
    assert config.model == "gpt-4o-mini"


def test_resolve_judge_config_defaults_to_interviewer_config(monkeypatch):
    """Without JUDGE_* vars, judge should use OPENAI_* (interviewer's config)."""
    module = _load_eval_module()
    parser = module._build_parser()
    monkeypatch.delenv("JUDGE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "interviewer-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://interviewer.example/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "mimo-v2.5-pro")
    monkeypatch.setenv("LLM_TIMEOUT", "60")
    args = parser.parse_args([])

    config = module._resolve_judge_config(args)

    assert config is not None
    assert config.api_key == "interviewer-key"
    assert config.base_url == "https://interviewer.example/v1"
    assert config.model == "mimo-v2.5-pro"
    assert config.timeout == 60


def test_llm_generate_report_includes_scoring_fallback_notice(monkeypatch):
    """When scoring fell back to rules, report should include fallback notice."""
    module = _load_eval_module()
    result = {
        "scenario_id": "long_session_mid",
        "turns": [{"turn": 1, "user": "test", "assistant": "ok", "events": [], "latency_sec": 1.0}],
        "metrics": {
            "turn_count": 1, "tool_count": 0, "tool_names": [], "selected_ids": [],
            "cross_turn_duplicate_candidates": [], "errors": [], "thinking_turns": 0,
        },
        "scores": {
            "passed": False, "overall_score": 0.5, "judge_model": "gpt-4o",
            "fallback_notice": "⚠️ LLM 评分失败（gpt-4o: timeout），已降级为规则评分。",
            "items": {
                "tool_call_rate": {"passed": False, "score": 0.0, "reasoning": "规则判断"},
            },
            "critical_issues": [], "highlights": [],
        },
    }

    def mock_call(config, messages, **kwargs):
        # Verify the prompt includes fallback context
        prompt = messages[0]["content"]
        assert "降级提醒" in prompt
        return "# 评测报告\n\n评分使用了规则匹配。"

    monkeypatch.setattr(module, "_call_openai_compatible_chat", mock_call)

    judge_config = module.JudgeLLMConfig(api_key="test", base_url="http://test", model="gpt-4o", timeout=30)
    report = module.llm_generate_report(result, judge_config)

    assert "降级提醒" in report
    assert "评测报告" in report


def test_write_reports_with_llm_report(tmp_path):
    """write_reports should use LLM report when provided."""
    module = _load_eval_module()
    result = {
        "scenario_id": "test",
        "turns": [],
        "metrics": {"turn_count": 0},
        "scores": {"passed": True, "items": {}},
    }
    llm_report = "# LLM 生成的报告\n\n这是 LLM 生成的内容。"

    json_path, md_path = module.write_reports(result, tmp_path, llm_report=llm_report)

    md_content = md_path.read_text(encoding="utf-8")
    assert "LLM 生成的报告" in md_content
    assert "LLM 生成的内容" in md_content

#!/usr/bin/env python3
"""Entry point for the InterviewBoss eval framework.

Delegates to the eval_framework package. Run with:
    RUN_REAL_INTERVIEW_EVAL=1 PYTHONPATH=backend:backend/scripts python3 backend/scripts/eval_interview_agent.py --scenario greeting_role_adherence
"""

import sys
from pathlib import Path

# Add scripts directory to path so eval_framework package can be imported
scripts_dir = str(Path(__file__).resolve().parent)
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# Keep the historical single-file import surface while the implementation lives
# in eval_framework. Tests and one-off operators import these helpers directly.
from eval_framework.candidate import (
    SmartCandidateAgent,
    _resolve_candidate_config,
    _resolve_judge_config,
)
from eval_framework import metrics as _metrics
from eval_framework import reports as _reports
from eval_framework import scoring as _scoring
from eval_framework.http_client import _call_openai_compatible_chat
from eval_framework.metrics import query_asked_questions_db
from eval_framework.reports import write_reports
from eval_framework.runner import _build_parser, main
from eval_framework.scenarios import SCENARIOS
from eval_framework.scoring import (
    _build_conversation_transcript,
    _build_scoring_criteria_text,
    llm_score_scenario,
    score_scenario,
)
from eval_framework.types import CandidateLLMConfig, JudgeLLMConfig, MID_LEVEL_PERSONA


def extract_metrics(turns, conversation_id):
    """Compatibility wrapper that preserves the historical monkeypatch seam."""
    _metrics.query_asked_questions_db = query_asked_questions_db
    return _metrics.extract_metrics(turns, conversation_id)


def llm_score_scenario(scenario, turns, metrics, judge_config):
    """Compatibility wrapper for callers patching the old entry module."""
    _scoring._call_openai_compatible_chat = _call_openai_compatible_chat
    return _scoring.llm_score_scenario(scenario, turns, metrics, judge_config)


def llm_generate_report(result, judge_config):
    """Compatibility wrapper for callers patching the old entry module."""
    _reports._call_openai_compatible_chat = _call_openai_compatible_chat
    return _reports.llm_generate_report(result, judge_config)

if __name__ == "__main__":
    raise SystemExit(main())

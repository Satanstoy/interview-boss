"""Tests for the manual chat tools real E2E verifier helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_chat_tools_real_e2e.py"
_SPEC = importlib.util.spec_from_file_location("verify_chat_tools_real_e2e", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = verifier
_SPEC.loader.exec_module(verifier)


def test_extract_case_result_reads_split_sse_question_events():
    """Verifier should read router-split selected_question and question_plan events."""
    events = [
        {"type": "step", "step": "search_questions"},
        {"type": "selected_question", "question": {"id": 7, "question": "RAG 检索怎么设计？"}},
        {
            "type": "question_plan",
            "question_id": 7,
            "adherence": {"adheres": True, "score": 0.75, "reason": "keyword_overlap"},
            "repaired": True,
            "fallback_used": False,
        },
        {"type": "chunk", "content": "可以从召回、排序、上下文拼装讲。"},
        {"type": "done"},
    ]

    result = verifier._extract_case_result("practice_request_rag", "出一道 RAG 题", events)

    assert result.verdict == "PASS"
    assert result.selected_question_id == 7
    assert result.selected_question_text == "RAG 检索怎么设计？"
    assert result.question_plan_id == 7
    assert result.adherence_score == 0.75
    assert result.repaired is True
    assert result.fallback_used is False


def test_extract_case_result_fails_required_tool_case_without_tool_step():
    """Verifier should not let selected_question/question_plan hide a missing tool call."""
    events = [
        {"type": "selected_question", "question": {"id": 7, "question": "RAG 检索怎么设计？"}},
        {"type": "question_plan", "question_id": 7, "adherence": {"score": 0.75}},
        {"type": "chunk", "content": "可以从召回、排序、上下文拼装讲。"},
        {"type": "done"},
    ]

    result = verifier._extract_case_result("practice_request_rag", "出一道 RAG 题", events)

    assert result.verdict == "FAIL"
    assert "expected tool call" in "; ".join(result.errors)



def test_extract_case_result_keeps_legacy_done_metadata_fallback():
    """Verifier should still parse old done.metadata shape for compatibility."""
    events = [
        {"type": "step", "step": "search_questions"},
        {"type": "chunk", "content": "可以从召回、排序、上下文拼装讲。"},
        {
            "type": "done",
            "metadata": {
                "selected_question": {"id": 8, "question": "向量数据库如何评估召回？"},
                "question_plan": {
                    "question_id": 8,
                    "adherence": {"adheres": True, "score": 0.6, "reason": "legacy_metadata"},
                    "repaired": False,
                    "fallback_used": True,
                },
            },
        },
    ]

    result = verifier._extract_case_result("practice_request_rag", "出一道 RAG 题", events)

    assert result.verdict == "PASS"
    assert result.selected_question_id == 8
    assert result.selected_question_text == "向量数据库如何评估召回？"
    assert result.question_plan_id == 8
    assert result.adherence_score == 0.6
    assert result.repaired is False
    assert result.fallback_used is True

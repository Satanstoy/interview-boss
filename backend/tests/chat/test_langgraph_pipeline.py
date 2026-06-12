"""Tests for the async chat pipeline (replaces LangGraph-backed pipeline)."""

import asyncio

import pytest


# ── Pipeline import and basic structure ──

def test_pipeline_run_chat_is_importable():
    from app.agents.chat.graph import run_chat
    assert callable(run_chat)


def test_pipeline_module_has_all_steps():
    from app.agents.chat import pipeline
    assert hasattr(pipeline, "_step_load_context")
    assert hasattr(pipeline, "_step_classify")
    assert hasattr(pipeline, "_step_extract_memory")
    assert hasattr(pipeline, "_react_loop")


# ── Basis / retrieval helpers ──

def test_basis_guidance_is_metadata_only():
    from app.agents.chat.prompts import BASIS_EXTRACT_GUIDANCE
    assert "[BASIS]" in BASIS_EXTRACT_GUIDANCE
    assert "不要在回复正文中输出" in BASIS_EXTRACT_GUIDANCE
    assert "必须输出一个 JSON 块" not in BASIS_EXTRACT_GUIDANCE


def test_basis_alignment_filters_unasked_rerank_basis():
    from app.agents.chat.nodes import _filter_basis_ids_by_response

    retrieved = [
        {"id": 1, "question": "说一下RRF融合算法，它的公式是什么？K参数一般怎么设？"},
        {"id": 2, "question": "cosine similarity 和 inner product 有什么区别？"},
    ]

    aligned = _filter_basis_ids_by_response(
        "你项目里用了 bge-small 做向量召回。cosine similarity 和 inner product 有什么区别？",
        [1, 2],
        retrieved,
    )

    assert aligned == [2]


# ── Prompt end_interview guidance ──

def test_practice_prompt_has_end_interview():
    from app.agents.chat.prompts import INTERVIEW_SYSTEM_PROMPT_PRACTICE
    assert "结束面试" in INTERVIEW_SYSTEM_PROMPT_PRACTICE
    assert "生成面试总结" in INTERVIEW_SYSTEM_PROMPT_PRACTICE


def test_jd_prompt_has_end_interview():
    from app.agents.chat.prompts import INTERVIEW_SYSTEM_PROMPT_JD
    assert "结束面试" in INTERVIEW_SYSTEM_PROMPT_JD

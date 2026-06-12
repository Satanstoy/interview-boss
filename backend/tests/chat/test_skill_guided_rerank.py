"""Tests for skill-guided rerank validation."""

import pytest


def _candidate(qid, question, cat1="项目复盘", cat2="RAG", tags=""):
    return {
        "id": qid,
        "question": question,
        "cat1": cat1,
        "cat2": cat2,
        "tags": tags,
        "_rrf_score": 0.03,
    }


def test_validate_rerank_filters_non_candidate_ids():
    from app.agents.chat.nodes import validate_rerank_result

    candidates = [_candidate(1, "RAG 混合检索怎么做？")]
    result = validate_rerank_result(
        {
            "ranked_question_ids": [1, 999],
            "selected_basis_ids": [999],
            "confidence": 0.9,
            "should_show_references": True,
        },
        candidates,
        [],
        "deep_dive",
        "RAG 混合检索",
        "RAG 混合检索",
    )

    assert result["ranked_question_ids"] == [1]
    assert result["selected_basis_ids"] == []
    assert result["should_show_references"] is False
    assert "non_candidate:999" in result["filtered_reasons"]


def test_validate_rerank_filters_negative_basis():
    from app.agents.chat.nodes import validate_rerank_result

    candidates = [
        _candidate(1, "RAG 混合检索怎么做？"),
        _candidate(2, "手撕 LRU Cache", cat1="算法", cat2="缓存", tags="LRU"),
    ]
    result = validate_rerank_result(
        {
            "ranked_question_ids": [2, 1],
            "selected_basis_ids": [2],
            "confidence": 0.9,
            "should_show_references": True,
        },
        candidates,
        ["LRU"],
        "topic_shift",
        "岗位高频基础题",
        "RAG rerank",
    )

    assert 2 not in result["ranked_question_ids"]
    assert result["selected_basis_ids"] == []
    assert result["should_show_references"] is False
    assert "negative_term:2" in result["filtered_reasons"]


def test_deep_dive_requires_basis_overlap():
    from app.agents.chat.nodes import validate_rerank_result

    candidates = [_candidate(1, "TCP 三次握手是什么？", cat1="网络", cat2="TCP")]
    result = validate_rerank_result(
        {
            "ranked_question_ids": [1],
            "selected_basis_ids": [1],
            "confidence": 0.9,
            "should_show_references": True,
        },
        candidates,
        [],
        "deep_dive",
        "RAG selected_basis 引用一致性",
        "RAG selected_basis",
    )

    assert result["selected_basis_ids"] == []
    assert result["should_show_references"] is False
    assert "deep_dive_weak_basis:1" in result["filtered_reasons"]


def test_clarification_never_shows_references():
    from app.agents.chat.nodes import validate_rerank_result

    candidates = [_candidate(1, "RAG 混合检索怎么做？")]
    result = validate_rerank_result(
        {
            "ranked_question_ids": [1],
            "selected_basis_ids": [1],
            "confidence": 0.9,
            "should_show_references": True,
        },
        candidates,
        [],
        "clarification",
        "澄清上一轮回答",
        "RAG",
    )

    assert result["selected_basis_ids"] == []
    assert result["should_show_references"] is False


@pytest.mark.asyncio
async def test_default_rerank_is_deterministic_without_llm(monkeypatch):
    from app.agents.chat import nodes

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("LLM rerank should not be called by default")

    monkeypatch.delenv("CHAT_LLM_RERANK_MODE", raising=False)
    monkeypatch.setattr(nodes, "_call_llm_with_retry", fail_if_called)

    result = await nodes.llm_rerank_questions(
        {
            "retrieved_questions": [
                _candidate(1, "说一下RRF融合算法，它的公式是什么？K参数怎么设？", cat1="B.Agent与LLM应用", cat2="RAG"),
                _candidate(2, "Redis 热 key 怎么解决？", cat1="C.基础工程能力", cat2="Redis"),
            ],
            "strategy": "deep_dive",
            "search_query": "RRF reciprocal rank fusion",
            "strategy_target_topic": "RRF 融合",
            "search_negative_terms": [],
        }
    )

    assert result["rerank_metadata"]["ranked_question_ids"][0] == 1
    assert result["rerank_metadata"]["selected_basis_ids"] == [1]
    assert result["rerank_metadata"]["reasoning_summary"] == "deterministic_rrf_overlap_rerank"

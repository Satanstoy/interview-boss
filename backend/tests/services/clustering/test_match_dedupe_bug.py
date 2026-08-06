"""BUG 回归：match_new_questions 同题多匹配去重。

LLM 对同一道新题可能返回多个 cluster 匹配（如 GraphRAG vs RAG 基础题，
mock 增量评估实测 5888 → 6075/6116/6264 三个聚类），个人题库合并路径
必须与生产 cluster_batch 路径（_match_and_cluster_cat2 已去重）语义一致：
同一 new_id 只保留第一个匹配。
"""
import asyncio
import json


def _candidate_clusters():
    return {
        "B2.RAG系统设计": [
            {"id": 6075, "question": "详细介绍一下RAG的具体流程", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
            {"id": 6116, "question": "RAG是怎么做的", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
            {"id": 6264, "question": "对RAG的理解", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
        ]
    }


async def test_match_new_questions_dedupes_multi_matches(monkeypatch):
    """同一新题被 LLM 匹配到多个聚类 → 只保留第一个（其余丢弃）"""
    from app.services.clustering.matcher import match_new_questions

    async def fake_llm(prompt, system_msg=None, response_format=None, user_id=None, model=None):
        # LLM 对 new_id=1 返回 3 个 cluster 匹配（bug 复现场景）
        return json.dumps({
            "matches": [
                {"new_id": 1, "cluster_id": 6075},
                {"new_id": 1, "cluster_id": 6116},
                {"new_id": 1, "cluster_id": 6264},
            ]
        })

    monkeypatch.setattr(
        "app.services.clustering.matcher._call_llm_with_retry", fake_llm
    )

    new_rows = [{"id": 1, "question": "GraphRAG和普通RAG的区别是什么？",
                 "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""}]
    result = await match_new_questions(
        new_rows, _candidate_clusters(), user_id=1
    )

    assert len(result["matched"]) == 1  # 只保留一个匹配
    assert result["matched"][0]["new_id"] == 1
    assert result["matched"][0]["question_bank_id"] in {6075, 6116, 6264}
    assert result["unmatched"] == []  # 已匹配的不进未匹配


async def test_match_new_questions_distinct_questions_still_match_all(monkeypatch):
    """不同新题各匹配各自聚类 → 不受去重影响（全部保留）"""
    from app.services.clustering.matcher import match_new_questions

    async def fake_llm(prompt, system_msg=None, response_format=None, user_id=None, model=None):
        return json.dumps({
            "matches": [
                {"new_id": 1, "cluster_id": 6075},
                {"new_id": 2, "cluster_id": 6116},
            ]
        })

    monkeypatch.setattr(
        "app.services.clustering.matcher._call_llm_with_retry", fake_llm
    )

    new_rows = [
        {"id": 1, "question": "RAG 流程", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
        {"id": 2, "question": "RAG 怎么做", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
    ]
    result = await match_new_questions(
        new_rows, _candidate_clusters(), user_id=1
    )

    assert len(result["matched"]) == 2
    matched_ids = {m["new_id"] for m in result["matched"]}
    assert matched_ids == {1, 2}


async def test_match_new_questions_unmatched_stays_unmatched(monkeypatch):
    """未匹配的新题进入 unmatched（不被误标为已匹配）"""
    from app.services.clustering.matcher import match_new_questions

    async def fake_llm(prompt, system_msg=None, response_format=None, user_id=None, model=None):
        return json.dumps({"matches": [{"new_id": 1, "cluster_id": 6075}]})

    monkeypatch.setattr(
        "app.services.clustering.matcher._call_llm_with_retry", fake_llm
    )

    new_rows = [
        {"id": 1, "question": "RAG 流程", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
        {"id": 2, "question": "SFT 场景", "cat1": "B.Agent与LLM应用", "cat2": "B2.RAG系统设计", "tags": ""},
    ]
    result = await match_new_questions(
        new_rows, _candidate_clusters(), user_id=1
    )

    assert len(result["matched"]) == 1
    assert [u["id"] for u in result["unmatched"]] == [2]

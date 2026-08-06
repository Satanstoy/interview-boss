"""变体归一化去重（根因 #2）：重复变体 21.5% → <5%。

两层：
1. writer 写库文本规则（零成本）：规范化相等 + 子串包含
2. clustering_maintenance LLM 语义判重（批量清洗，幂等）
"""
import json


def test_dedupe_variants_exact_and_substring():
    """文本规则：规范化相等 + 子串包含去重，保留较长者"""
    from app.services.pipeline.writer import _dedupe_variants

    variants = [
        "介绍rag流程",
        "rag流程",           # ⊂ 介绍rag流程（规范化后）→ 去重
        "讲述一下rag的流程",  # 规范化后含"rag流程"→ 被"介绍rag流程"去重？检查
        "RAG是怎么做的",      # 独立
    ]
    result = _dedupe_variants(variants)
    assert "rag流程" not in result
    assert "介绍rag流程" in result
    assert "RAG是怎么做的" in result


def test_dedupe_variants_keeps_distinct():
    """不同考察点的变体不被误去重"""
    from app.services.pipeline.writer import _dedupe_variants

    variants = ["缓存的穿透怎么解决", "缓存击穿和雪崩的区别", "Redis 缓存穿透"]
    result = _dedupe_variants(variants)
    assert len(result) == 3


async def test_llm_dedupe_variants_marks_duplicates(monkeypatch):
    """LLM 语义判重：识别文本不相似但语义重复的变体"""
    from app.services.clustering_maintenance import _llm_find_duplicate_variants

    async def fake_llm(prompt, system_msg, response_format, user_id, model):
        return json.dumps({"duplicates": [[0, 1]]})

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", fake_llm
    )
    result = await _llm_find_duplicate_variants(
        ["介绍rag流程", "讲述一下rag的流程", "RAG是怎么做的"],
        user_id=1,
    )
    assert [0, 1] in result


async def test_llm_dedupe_variants_failure_graceful(monkeypatch):
    """LLM 判重失败 → 返回空（不动数据，等待下次清洗）"""
    from app.services.clustering_maintenance import _llm_find_duplicate_variants

    async def broken_llm(prompt, system_msg, response_format, user_id, model):
        raise RuntimeError("llm down")

    monkeypatch.setattr(
        "app.services.llm._call_llm_with_retry", broken_llm
    )
    result = await _llm_find_duplicate_variants(["a", "b"], user_id=1)
    assert result == []


def test_merge_variant_duplicates_keeps_representative():
    """合并重复变体：保留第一个（代表题若在列表中不受影响），更新 frequency"""
    from app.services.clustering_maintenance import _merge_variant_duplicates

    oq = ["介绍rag流程", "讲述一下rag的流程", "RAG是怎么做的", "rag流程"]
    dup_pairs = [[0, 1], [3, 0]]
    result = _merge_variant_duplicates(oq, dup_pairs)
    assert len(result) == 2  # 4 → 2（1 并入 0，3 并入 0）
    assert result[0] == "介绍rag流程"
    assert "RAG是怎么做的" in result

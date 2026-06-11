"""heuristic_rerank 单元测试 — 关键词重叠 + 意图对齐 + 边界情况"""

import pytest


def _doc(q: str = "", tags: str = "", cat1: str = "", cat2: str = "") -> dict:
    return {"question": q, "tags": tags, "cat1": cat1, "cat2": cat2}


def _rerank(results, keywords, intent):
    from app.services.fts_service import _heuristic_rerank

    return _heuristic_rerank(results, keywords, intent)


class TestKeywordOverlap:
    def test_single_keyword_in_question(self):
        results = [_doc(q="Python GIL 是什么")]
        out = _rerank(results, ["GIL"], [])
        assert out[0]["_heuristic_score"] == 11.0

    def test_multiple_keywords_in_question(self):
        results = [_doc(q="Python GIL 多线程")]
        out = _rerank(results, ["Python", "GIL"], [])
        assert out[0]["_heuristic_score"] == 21.0

    def test_keyword_in_tags(self):
        results = [_doc(q="GIL 是什么", tags="Python,并发")]
        out = _rerank(results, ["Python"], [])
        assert out[0]["_heuristic_score"] == 6.0

    def test_keyword_in_cat1(self):
        results = [_doc(cat1="Python")]
        out = _rerank(results, ["Python"], [])
        assert out[0]["_heuristic_score"] == 6.0

    def test_keyword_in_cat2(self):
        results = [_doc(cat2="并发编程")]
        out = _rerank(results, ["并发编程"], [])
        assert out[0]["_heuristic_score"] == 6.0

    def test_question_and_tags_cumulative(self):
        results = [_doc(q="Python GIL", tags="Python")]
        out = _rerank(results, ["Python"], [])
        assert out[0]["_heuristic_score"] == 16.0

    def test_case_insensitive(self):
        results = [_doc(q="python gil")]
        out = _rerank(results, ["Python", "GIL"], [])
        assert out[0]["_heuristic_score"] == 21.0


class TestIntentAlignment:
    def test_matching_cat1_boost(self):
        results = [
            _doc(q="GIL 机制", cat1="Python", cat2="基础概念"),
            _doc(q="GIL 机制", cat1="Java", cat2="基础概念"),
        ]
        out = _rerank(results, ["GIL"], ["Python"])
        assert out[0]["cat1"] == "Python"
        assert out[0]["_heuristic_score"] > out[1]["_heuristic_score"]

    def test_matching_cat2_boost(self):
        results = [
            _doc(q="GC 算法", cat1="Java", cat2="垃圾回收"),
            _doc(q="GC 算法", cat1="Java", cat2="内存管理"),
        ]
        out = _rerank(results, ["GC"], ["垃圾回收"])
        assert out[0]["cat2"] == "垃圾回收"

    def test_no_intent_no_boost(self):
        results = [_doc(q="GIL"), _doc(q="GIL")]
        out = _rerank(results, ["GIL"], [])
        assert out[0]["_heuristic_score"] == 11.0
        assert out[1]["_heuristic_score"] == 10.9

    def test_intent_boost_is_additive(self):
        results = [_doc(q="Python", cat2="Python")]
        out = _rerank(results, ["Python"], ["Python"])
        assert out[0]["_heuristic_score"] == 21.0


class TestStability:
    def test_earlier_result_tiebreak(self):
        results = [_doc(q="GIL"), _doc(q="GIL")]
        out = _rerank(results, ["GIL"], [])
        assert out[0]["_heuristic_score"] == 11.0
        assert out[1]["_heuristic_score"] == 10.9

    def test_stability_does_not_override_real_difference(self):
        results = [_doc(q="Python"), _doc(q="Python GIL")]
        out = _rerank(results, ["Python", "GIL"], [])
        assert out[0]["_heuristic_score"] == 20.9
        assert out[1]["_heuristic_score"] == 11.0


class TestEdgeCases:
    def test_empty_results(self):
        out = _rerank([], ["Python"], [])
        assert out == []

    def test_empty_keywords(self):
        results = [_doc(q="Python GIL")]
        out = _rerank(results, [], [])
        assert out[0]["_heuristic_score"] == 0

    def test_no_matching_keywords(self):
        results = [_doc(q="Java GC")]
        out = _rerank(results, ["Python"], [])
        assert out[0]["_heuristic_score"] == 0

    def test_results_preserved(self):
        results = [_doc(q="Python", tags="编程", cat1="语言", cat2="基础")]
        out = _rerank(results, ["Python"], [])
        assert out[0]["question"] == "Python"
        assert out[0]["tags"] == "编程"
        assert out[0]["cat1"] == "语言"
        assert out[0]["cat2"] == "基础"

    def test_original_order_preserved_when_scores_equal(self):
        docs = [_doc(q=f"topic-{i}") for i in range(5)]
        out = _rerank(docs, [], [])
        for i, item in enumerate(out):
            assert item["_heuristic_score"] == 0

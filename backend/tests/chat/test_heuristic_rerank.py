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


class TestRetrievalIntent:
    """retrieval_intent 参数对 _heuristic_rerank 评分的影响"""

    def _rerank_with_intent(
        self,
        results,
        keywords,
        intent_categories,
        retrieval_intent=None,
        question_type=None,
    ):
        from app.services.fts_service import _heuristic_rerank

        return _heuristic_rerank(
            results,
            keywords,
            intent_categories,
            retrieval_intent=retrieval_intent,
            question_type=question_type,
        )

    def test_review_weakness_boosts_knowledge_over_project(self):
        results = [
            _doc(q="Redis 缓存穿透", cat1="基础原理", cat2="缓存"),
            _doc(q="项目架构设计", cat1="项目复盘", cat2="系统设计"),
        ]
        out = self._rerank_with_intent(
            results, ["Redis"], [], retrieval_intent="review_weakness"
        )
        assert out[0]["cat1"] == "基础原理", (
            "review_weakness should boost knowledge questions"
        )

    def test_review_weakness_penalizes_project(self):
        results = [
            _doc(q="项目架构", cat1="项目复盘"),
            _doc(q="Redis 缓存", cat1="基础原理"),
        ]
        out = self._rerank_with_intent(
            results, ["Redis"], [], retrieval_intent="review_weakness"
        )
        knowledge_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "基础原理"
        )
        project_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "项目复盘"
        )
        assert knowledge_score > project_score, (
            "review_weakness: knowledge should outrank project"
        )

    def test_expand_knowledge_boosts_knowledge(self):
        results = [
            _doc(q="Redis 缓存", cat1="基础原理"),
            _doc(q="项目架构", cat1="项目复盘"),
        ]
        out = self._rerank_with_intent(
            results, ["Redis"], [], retrieval_intent="expand_knowledge"
        )
        knowledge_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "基础原理"
        )
        project_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "项目复盘"
        )
        assert knowledge_score > project_score, (
            "expand_knowledge: knowledge should get +3 boost"
        )

    def test_find_similar_no_extra_boost(self):
        results = [
            _doc(q="Redis 缓存", cat1="基础原理"),
            _doc(q="项目架构", cat1="项目复盘"),
        ]
        out_none = self._rerank_with_intent(
            results, ["Redis"], [], retrieval_intent=None
        )
        out_find = self._rerank_with_intent(
            results, ["Redis"], [], retrieval_intent="find_similar"
        )
        assert out_none[0]["_heuristic_score"] == out_find[0]["_heuristic_score"], (
            "find_similar should not change scores vs None"
        )

    def test_question_type_project_followup_boosts_project(self):
        results = [
            _doc(q="Redis 缓存原理", cat1="基础原理"),
            _doc(q="Redis 缓存架构", cat1="项目复盘"),
        ]
        out = self._rerank_with_intent(
            results, ["Redis", "缓存"], [], question_type="project_followup"
        )
        project_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "项目复盘"
        )
        knowledge_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "基础原理"
        )
        assert project_score > knowledge_score, (
            "project_followup: project should outrank knowledge when keyword scores equal"
        )

    def test_question_type_knowledge_probe_boosts_knowledge(self):
        results = [
            _doc(q="项目架构", cat1="项目复盘"),
            _doc(q="Redis 缓存", cat1="基础原理"),
        ]
        out = self._rerank_with_intent(
            results, ["Redis"], [], question_type="knowledge_probe"
        )
        knowledge_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "基础原理"
        )
        project_score = next(
            r["_heuristic_score"] for r in out if r["cat1"] == "项目复盘"
        )
        assert knowledge_score > project_score, (
            "knowledge_probe: knowledge should get +8 boost"
        )

    def test_question_type_still_applies_without_keywords(self):
        results = [
            _doc(q="项目架构", cat1="项目复盘"),
            _doc(q="Redis 缓存", cat1="基础原理"),
        ]
        out = self._rerank_with_intent(
            results, [], [], question_type="knowledge_probe"
        )
        assert out[0]["cat1"] == "基础原理"
        assert out[0]["_heuristic_score"] > out[1]["_heuristic_score"]

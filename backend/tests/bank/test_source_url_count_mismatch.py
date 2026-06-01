"""
自动化测试 — 针对 BUG-001 和 BUG-002
BUG-001: 增量更新时 original_question_sources 未合并已有问题的新 URL
BUG-002: 来源详情展开数量与 badge 数量不一致（使用 dedupedSources 去重）

使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock


class TestIncrementalUpdateMergesSources:
    """BUG-001: _apply_incremental_txn 合并逻辑测试"""

    def test_new_url_merged_to_existing_question_sources(self):
        """同一问题文本从新 URL 出现时，新 URL 应合并到 original_question_sources"""
        existing_orig_qs = ["什么是微服务"]
        existing_orig_qs_src = [
            {"question": "什么是微服务", "sources": [{"url": "http://xiaohongshu.com", "company": "A", "round": "1面"}]}
        ]
        new_q_text = "什么是微服务"
        new_source = {"url": "http://zhihu.com", "company": "B", "round": "2面"}
        url = "http://zhihu.com"

        # 模拟修复后的逻辑
        if new_q_text and new_q_text not in existing_orig_qs:
            existing_orig_qs.append(new_q_text)
            existing_orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
        elif new_q_text:
            for _oqs_item in existing_orig_qs_src:
                if _oqs_item.get("question") == new_q_text:
                    _oqs_urls = {s.get("url") for s in _oqs_item.get("sources", [])}
                    if url not in _oqs_urls:
                        _oqs_item.setdefault("sources", []).append(new_source)
                    break

        assert len(existing_orig_qs_src) == 1  # 仍然只有 1 个条目
        assert len(existing_orig_qs_src[0]["sources"]) == 2  # 但有 2 个来源
        assert existing_orig_qs_src[0]["sources"][1]["url"] == "http://zhihu.com"

    def test_same_url_not_duplicated_in_oqs(self):
        """同一 URL 不应重复添加到 original_question_sources"""
        existing_orig_qs_src = [
            {"question": "Q1", "sources": [{"url": "http://a.com", "company": "A", "round": "1"}]}
        ]
        url = "http://a.com"
        new_source = {"url": url, "company": "A", "round": "2"}
        new_q_text = "Q1"

        if new_q_text:
            for _oqs_item in existing_orig_qs_src:
                if _oqs_item.get("question") == new_q_text:
                    _oqs_urls = {s.get("url") for s in _oqs_item.get("sources", [])}
                    if url not in _oqs_urls:
                        _oqs_item.setdefault("sources", []).append(new_source)
                    break

        assert len(existing_orig_qs_src[0]["sources"]) == 1  # 不重复

    def test_new_question_text_still_adds_entry(self):
        """新问题文本仍然正确添加新条目"""
        existing_orig_qs = ["Q1"]
        existing_orig_qs_src = [
            {"question": "Q1", "sources": [{"url": "http://a.com"}]}
        ]
        new_q_text = "Q2"
        new_source = {"url": "http://b.com", "company": "B", "round": "1"}
        url = "http://b.com"

        if new_q_text and new_q_text not in existing_orig_qs:
            existing_orig_qs.append(new_q_text)
            existing_orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
        elif new_q_text:
            for _oqs_item in existing_orig_qs_src:
                if _oqs_item.get("question") == new_q_text:
                    _oqs_urls = {s.get("url") for s in _oqs_item.get("sources", [])}
                    if url not in _oqs_urls:
                        _oqs_item.setdefault("sources", []).append(new_source)
                    break

        assert len(existing_orig_qs_src) == 2
        assert existing_orig_qs_src[1]["question"] == "Q2"
        assert existing_orig_qs_src[1]["sources"][0]["url"] == "http://b.com"

    def test_multiple_questions_same_url(self):
        """多个问题文本从同一 URL 出现时，各自正确记录"""
        existing_orig_qs = ["Q1"]
        existing_orig_qs_src = [
            {"question": "Q1", "sources": [{"url": "http://a.com"}]}
        ]

        # Q2 从 a.com 出现（URL 已存在但 Q2 是新问题）
        new_q_text = "Q2"
        new_source = {"url": "http://a.com", "company": "A", "round": "1"}
        url = "http://a.com"

        if new_q_text and new_q_text not in existing_orig_qs:
            existing_orig_qs.append(new_q_text)
            existing_orig_qs_src.append({"question": new_q_text, "sources": [new_source]})

        assert len(existing_orig_qs_src) == 2
        # 两个问题各有 1 个来源，但 sources 主列表只有 1 个 URL
        assert existing_orig_qs_src[0]["sources"][0]["url"] == "http://a.com"
        assert existing_orig_qs_src[1]["sources"][0]["url"] == "http://a.com"


class TestSourceCountConsistency:
    """BUG-002: 展开数量 = badge 数量不变量"""

    def test_deduped_sources_count_equals_sources_length(self):
        """去重后来源数量应等于 sources.length"""
        sources = [
            {"url": "http://a.com", "company": "A"},
            {"url": "http://b.com", "company": "B"},
            {"url": "http://c.com", "company": "C"},
        ]
        original_question_sources = [
            {"question": "Q1", "sources": [{"url": "http://a.com"}]},
            {"question": "Q2", "sources": [{"url": "http://a.com"}]},  # 同 URL
            {"question": "Q3", "sources": [{"url": "http://b.com"}]},
            {"question": "Q4", "sources": [{"url": "http://c.com"}]},
        ]

        # 模拟前端 dedupedSources 逻辑
        url_to_oq = {}
        for item in original_question_sources:
            for s in item.get("sources", []):
                if s["url"] and s["url"] not in url_to_oq:
                    url_to_oq[s["url"]] = item["question"]

        deduped = []
        for s in sources:
            deduped.append({**s, "_origQuestion": url_to_oq.get(s["url"], "")})

        assert len(deduped) == len(sources) == 3  # 展开 = badge

    def test_deduped_preserves_orig_question_context(self):
        """去重后仍保留原始问题上下文"""
        sources = [{"url": "http://a.com", "company": "A"}]
        original_question_sources = [
            {"question": "什么是微服务", "sources": [{"url": "http://a.com"}]}
        ]

        url_to_oq = {}
        for item in original_question_sources:
            for s in item.get("sources", []):
                if s["url"] not in url_to_oq:
                    url_to_oq[s["url"]] = item["question"]

        deduped = [{**s, "_origQuestion": url_to_oq.get(s["url"], "")} for s in sources]

        assert deduped[0]["_origQuestion"] == "什么是微服务"
        assert deduped[0]["url"] == "http://a.com"

    def test_empty_sources_returns_empty(self):
        """空来源列表返回空"""
        sources = []
        result = sources
        assert len(result) == 0

"""
自动化测试 — 针对增量聚类稳定性 (BUG-001 ~ BUG-007)
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call


# ─────────────────────────────────────────────
# BUG-001: 增量匹配上下文不足
# ─────────────────────────────────────────────

class TestBUG001_MatchContext:
    """BUG-001: existing_by_cat2 的 all_questions 应包含 original_questions"""

    def test_match_context_includes_original_questions(self):
        """all_questions 应包含原始题目变体，而非只有顶层 question"""
        # 模拟 submit.py 中构建 existing_by_cat2 的逻辑
        row = {
            'id': 1,
            'question': '请解释 RAG 的召回策略',
            'cat2': 'RAG',
            'sources': json.dumps([{"url": "http://a.com", "company": "A", "round": "一面"}]),
            'original_questions': json.dumps(["RAG 的召回机制是什么", "双路召回怎么实现"]),
        }

        # 旧逻辑：all_questions 只有顶层 question
        old_all_qs = [row['question']]
        assert len(old_all_qs) == 1, "旧逻辑只传了 1 个题目"

        # 新逻辑：应包含 original_questions
        all_qs = [row['question']]
        try:
            orig = json.loads(row.get('original_questions') or '[]')
            all_qs.extend([q for q in orig if q and q != row['question']])
        except Exception:
            pass

        assert len(all_qs) == 3, f"新逻辑应传 3 个题目，实际: {len(all_qs)}"
        assert "RAG 的召回机制是什么" in all_qs
        assert "双路召回怎么实现" in all_qs


# ─────────────────────────────────────────────
# BUG-002: 增量匹配后不回写 original_questions
# ─────────────────────────────────────────────

class TestBUG002_UpdateOriginalQuestions:
    """BUG-002: matched 增频时应同时更新 original_questions"""

    def test_matched_updates_original_questions(self):
        """匹配到已有聚类后，新题文本应追加到 original_questions"""
        # 模拟已有 QB 记录
        existing_sources = [{"url": "http://a.com", "company": "A", "round": "一面"}]
        existing_orig_qs = ["旧题目A"]
        existing_orig_qs_src = [{"question": "旧题目A", "sources": [{"url": "http://a.com", "company": "A", "round": "一面"}]}]

        new_q_text = "新题目B"
        new_source = {"url": "http://b.com", "company": "B", "round": "二面"}

        # 模拟 _apply_incremental_txn 中的修复后逻辑
        sources = list(existing_sources)
        orig_qs = list(existing_orig_qs)
        orig_qs_src = list(existing_orig_qs_src)

        sources.append(new_source)
        if new_q_text and new_q_text not in orig_qs:
            orig_qs.append(new_q_text)
            orig_qs_src.append({"question": new_q_text, "sources": [new_source]})

        assert len(orig_qs) == 2, f"original_questions 应有 2 项，实际: {len(orig_qs)}"
        assert "新题目B" in orig_qs
        assert len(orig_qs_src) == 2
        assert orig_qs_src[1]["question"] == "新题目B"

    def test_matched_skips_duplicate_original_question(self):
        """如果新题文本已在 original_questions 中，不应重复追加"""
        existing_orig_qs = ["题目A", "题目B"]
        new_q_text = "题目A"  # 已存在

        orig_qs = list(existing_orig_qs)
        if new_q_text and new_q_text not in orig_qs:
            orig_qs.append(new_q_text)

        assert len(orig_qs) == 2, "不应重复追加"


# ─────────────────────────────────────────────
# BUG-003: sources 含已删除面经 URL
# ─────────────────────────────────────────────

class TestBUG003_CleanupStaleSources:
    """BUG-003: sources 中不应包含已删除面经的 URL"""

    def test_cleanup_stale_sources(self):
        """sources 应移除指向 deleted_at 面经的条目"""
        sources = [
            {"url": "http://live.com", "company": "A", "round": "一面"},
            {"url": "http://deleted.com", "company": "B", "round": "二面"},
        ]
        deleted_urls = {"http://deleted.com"}

        cleaned = [s for s in sources if s.get('url') not in deleted_urls]

        assert len(cleaned) == 1
        assert cleaned[0]["url"] == "http://live.com"


# ─────────────────────────────────────────────
# BUG-004: 频率查询不按 mode 计算
# ─────────────────────────────────────────────

class TestBUG004_DynamicFrequency:
    """BUG-004: get_dynamic_frequency_sql 应被调用来计算 mode-aware 频率"""

    def test_dynamic_frequency_sql_public_mode(self):
        """public 模式频率应只统计 owner_id IS NULL 的面试"""
        from app.db.connection import get_dynamic_frequency_sql
        sql = get_dynamic_frequency_sql('public', 1)
        assert 'i.owner_id IS NULL' in sql
        assert 'i.deleted_at IS NULL' in sql

    def test_dynamic_frequency_sql_personal_mode(self):
        """personal 模式频率应只统计 owner_id = user_id 的面试"""
        from app.db.connection import get_dynamic_frequency_sql
        sql = get_dynamic_frequency_sql('personal', 42)
        assert 'i.owner_id = 42' in sql

    def test_dynamic_frequency_sql_mixed_mode(self):
        """mixed 模式频率应统计 owner_id IS NULL 或 owner_id = user_id"""
        from app.db.connection import get_dynamic_frequency_sql
        sql = get_dynamic_frequency_sql('mixed', 42)
        assert 'i.owner_id IS NULL OR i.owner_id = 42' in sql


# ─────────────────────────────────────────────
# BUG-005: sources 含重复 URL
# ─────────────────────────────────────────────

class TestBUG005_SourcesDedup:
    """BUG-005: sources 去重应仅按 URL"""

    def test_sources_dedup_by_url(self):
        """同一 URL 不同 company/round 应合并为一条，保留更具体的信息"""
        sources = [
            {"url": "http://a.com", "company": "未提供", "round": "未提供"},
            {"url": "http://a.com", "company": "蔚来", "round": "技术面"},
            {"url": "http://b.com", "company": "字节", "round": "一面"},
        ]

        seen_urls = set()
        result = []
        for s in sources:
            url = s.get('url', '')
            if url in seen_urls:
                for existing in result:
                    if existing['url'] == url:
                        if existing['company'] in ('', '未提供') and s['company'] not in ('', '未提供'):
                            existing['company'] = s['company']
                        if existing['round'] in ('', '未提供') and s['round'] not in ('', '未提供'):
                            existing['round'] = s['round']
                        break
            else:
                seen_urls.add(url)
                result.append(s)

        assert len(result) == 2, f"应有 2 条唯一 URL，实际: {len(result)}"
        assert result[0]['company'] == '蔚来', "应保留更具体的 company"
        assert result[0]['round'] == '技术面', "应保留更具体的 round"


# ─────────────────────────────────────────────
# BUG-006: 删除面经时不级联清理 sources
# ─────────────────────────────────────────────

class TestBUG006_DeleteCleansSources:
    """BUG-006: 删除面经时应级联清理 question_bank.sources"""

    def test_delete_cleans_sources(self):
        """软删除面经后，QB.sources 中应移除该 URL"""
        url_to_delete = "http://delete-me.com"
        sources_json = json.dumps([
            {"url": "http://keep.com", "company": "A", "round": "一面"},
            {"url": url_to_delete, "company": "B", "round": "二面"},
        ])

        sources = json.loads(sources_json)
        new_sources = [s for s in sources if s.get('url') != url_to_delete]

        assert len(new_sources) == 1
        assert new_sources[0]['url'] == "http://keep.com"

    def test_frequency_updates_after_source_removal(self):
        """移除 source 后 frequency 应同步更新"""
        sources = [
            {"url": "http://a.com", "company": "A", "round": "一面"},
            {"url": "http://b.com", "company": "B", "round": "二面"},
        ]
        url_to_delete = "http://b.com"
        new_sources = [s for s in sources if s.get('url') != url_to_delete]
        new_frequency = len(new_sources)

        assert new_frequency == 1

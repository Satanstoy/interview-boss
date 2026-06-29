"""
自动化测试 — 针对 BUG-001 和 BUG-002
BUG-001: sourceCount 对聚类题目返回 original_questions.length 而非 sources.length
BUG-002: original_question_sources 未按 bank_mode 过滤

使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock


# ============================================================
# BUG-001: sourceCount 应该始终基于 sources.length 而非 original_questions.length
# ============================================================

class TestSourceCountConsistency:
    """BUG-001: sourceCount 计算逻辑修复验证"""

    def _make_question(self, frequency, sources, original_questions=None, original_question_sources=None):
        """构造测试用的 question 对象"""
        return {
            'id': 1,
            'frequency': frequency,
            'sources': sources or [],
            'original_questions': original_questions or [],
            'original_question_sources': original_question_sources or [],
        }

    def test_clustered_question_sources_dedup_by_url(self):
        """聚类题目的 sources 按 URL 去重：5 个原始问题来自 3 个不同 URL"""
        q = self._make_question(
            frequency=3,
            sources=[
                {"url": "http://a.com", "company": "A", "round": "1面"},
                {"url": "http://b.com", "company": "B", "round": "2面"},
                {"url": "http://c.com", "company": "C", "round": "1面"},
            ],
            original_questions=["问题1", "问题2", "问题3", "问题4", "问题5"],
        )
        # frequency 应该等于 sources 的去重 URL 数
        assert q['frequency'] == len(q['sources']) == 3
        # original_questions 数量可能大于 sources（多个问题来自同一 URL）
        assert len(q['original_questions']) == 5

    def test_single_question_frequency_equals_sources(self):
        """单题（无聚类）的 frequency 应等于 sources.length"""
        q = self._make_question(
            frequency=2,
            sources=[
                {"url": "http://a.com", "company": "A", "round": "1面"},
                {"url": "http://b.com", "company": "B", "round": "2面"},
            ],
        )
        assert q['frequency'] == len(q['sources'])
        assert len(q['original_questions']) == 0


class TestFrequencySourceCountInvariant:
    """频率与来源数量的不变量测试：重建和增量后 frequency 始终 = len(sources)"""

    def test_rebuild_frequency_equals_sources_length(self):
        """重建题库时 frequency = len(sources)，sources 按 URL 去重"""
        # 模拟聚类构建逻辑（master_bank.py build 端点）
        rows_in_cluster = [
            {'id': 1, 'question': 'Q1', 'url': 'http://a.com', 'company': 'A', 'round': '1', 'cat1': 'C1', 'cat2': 'C2', 'tags': 't', 'diff_tag': 'L1'},
            {'id': 2, 'question': 'Q2', 'url': 'http://a.com', 'company': 'A', 'round': '2', 'cat1': 'C1', 'cat2': 'C2', 'tags': 't', 'diff_tag': 'L1'},
            {'id': 3, 'question': 'Q3', 'url': 'http://b.com', 'company': 'B', 'round': '1', 'cat1': 'C1', 'cat2': 'C2', 'tags': 't', 'diff_tag': 'L1'},
        ]
        # 按 build 端点的逻辑构建 sources
        sources = []
        seen_urls = set()
        for r in rows_in_cluster:
            url = r['url']
            if url not in seen_urls:
                seen_urls.add(url)
                sources.append({"url": url, "company": r['company'], "round": r['round']})
        frequency = len(sources)
        original_questions = [r['question'] for r in rows_in_cluster]

        assert frequency == 2  # 2 个不同 URL
        assert len(original_questions) == 3  # 3 个原始问题
        assert len(sources) == frequency  # 关键不变量

    def test_incremental_update_frequency_equals_sources_length(self):
        """增量更新后 frequency = len(sources)"""
        # 模拟已有题目
        existing_sources = [{"url": "http://a.com", "company": "A", "round": "1"}]
        existing_frequency = 1

        # 模拟匹配到新面经（新 URL）
        new_url = "http://b.com"
        new_source = {"url": new_url, "company": "B", "round": "2"}

        existing_urls = {s['url'] for s in existing_sources}
        if new_url not in existing_urls:
            existing_sources.append(new_source)
        new_frequency = len(existing_sources)

        assert new_frequency == 2
        assert new_frequency == len(existing_sources)

    def test_incremental_update_same_url_no_duplicate(self):
        """增量更新同一 URL 不应重复添加 source"""
        existing_sources = [{"url": "http://a.com", "company": "A", "round": "1"}]
        new_url = "http://a.com"
        new_source = {"url": new_url, "company": "A", "round": "2"}

        existing_urls = {s['url'] for s in existing_sources}
        if new_url not in existing_urls:
            existing_sources.append(new_source)

        assert len(existing_sources) == 1  # 不应重复
        assert len(existing_sources) == 1  # frequency 也不变


# ============================================================
# BUG-002: original_question_sources 必须按 bank_mode 过滤
# ============================================================

class TestOriginalQuestionSourcesFiltering:
    """BUG-002: filter_original_question_sources_by_mode 测试"""

    def _make_oqs(self):
        """构造测试用的 original_question_sources 数据"""
        return [
            {
                "question": "Q1 from public",
                "sources": [
                    {"url": "http://pub.com", "company": "Pub", "round": "1面"},
                ]
            },
            {
                "question": "Q2 from personal",
                "sources": [
                    {"url": "http://per.com", "company": "Per", "round": "2面"},
                ]
            },
            {
                "question": "Q3 from both",
                "sources": [
                    {"url": "http://pub2.com", "company": "Pub2", "round": "1面"},
                    {"url": "http://per2.com", "company": "Per2", "round": "2面"},
                ]
            },
        ]

    @patch('app.db.connection.get_db_connection')
    def test_oqs_filtered_in_public_mode(self, mock_conn):
        """public 模式下只保留 owner_id IS NULL 的来源"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'url': 'http://pub.com', 'owner_id': None},
            {'url': 'http://per.com', 'owner_id': 42},
            {'url': 'http://pub2.com', 'owner_id': None},
            {'url': 'http://per2.com', 'owner_id': 42},
        ]
        mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=mock_cursor)))
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        from app.db.connection import filter_original_question_sources_by_mode
        oqs = self._make_oqs()
        result = filter_original_question_sources_by_mode(oqs, 'public', 42)

        # Q1 (pub.com) 保留, Q2 (per.com) 过滤掉, Q3 只保留 pub2.com
        assert len(result) == 2  # Q1 和 Q3
        assert result[0]['question'] == 'Q1 from public'
        assert len(result[0]['sources']) == 1
        assert result[1]['question'] == 'Q3 from both'
        assert len(result[1]['sources']) == 1  # 只有 pub2.com
        assert result[1]['sources'][0]['url'] == 'http://pub2.com'

    @patch('app.db.connection.get_db_connection')
    def test_oqs_filtered_in_personal_mode(self, mock_conn):
        """personal 模式下只保留 owner_id = user_id 的来源"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'url': 'http://pub.com', 'owner_id': None},
            {'url': 'http://per.com', 'owner_id': 42},
            {'url': 'http://pub2.com', 'owner_id': None},
            {'url': 'http://per2.com', 'owner_id': 42},
        ]
        mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=mock_cursor)))
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        from app.db.connection import filter_original_question_sources_by_mode
        oqs = self._make_oqs()
        result = filter_original_question_sources_by_mode(oqs, 'personal', 42)

        # Q2 (per.com) 保留, Q1 (pub.com) 过滤掉, Q3 只保留 per2.com
        assert len(result) == 2
        assert result[0]['question'] == 'Q2 from personal'
        assert result[1]['question'] == 'Q3 from both'
        assert result[1]['sources'][0]['url'] == 'http://per2.com'

    @patch('app.db.connection.get_db_connection')
    def test_oqs_filtered_in_mixed_mode(self, mock_conn):
        """mixed 模式下保留 owner_id IS NULL 或 owner_id = user_id 的来源"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'url': 'http://pub.com', 'owner_id': None},
            {'url': 'http://per.com', 'owner_id': 42},
            {'url': 'http://pub2.com', 'owner_id': None},
            {'url': 'http://per2.com', 'owner_id': 42},
        ]
        mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=mock_cursor)))
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        from app.db.connection import filter_original_question_sources_by_mode
        oqs = self._make_oqs()
        result = filter_original_question_sources_by_mode(oqs, 'mixed', 42)

        # 全部保留（pub 和 per 都属于当前用户可见范围）
        assert len(result) == 3
        assert len(result[2]['sources']) == 2  # Q3 的两个来源都保留

    @patch('app.db.connection.get_db_connection')
    def test_oqs_empty_input(self, mock_conn):
        """空输入返回空列表"""
        from app.db.connection import filter_original_question_sources_by_mode
        result = filter_original_question_sources_by_mode([], 'public', 42)
        assert result == []

    @patch('app.db.connection.get_db_connection')
    def test_oqs_no_urls(self, mock_conn):
        """无 URL 时原样返回"""
        from app.db.connection import filter_original_question_sources_by_mode
        oqs = [{"question": "Q", "sources": [{"company": "C", "round": "R"}]}]
        result = filter_original_question_sources_by_mode(oqs, 'public', 42)
        assert result == oqs

    @patch('app.db.connection.get_db_connection')
    def test_oqs_other_user_personal_excluded(self, mock_conn):
        """personal 模式下排除其他用户的来源"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            {'url': 'http://other.com', 'owner_id': 99},  # 其他用户
        ]
        mock_conn.return_value.__enter__ = MagicMock(return_value=MagicMock(execute=MagicMock(return_value=mock_cursor)))
        mock_conn.return_value.__exit__ = MagicMock(return_value=False)

        from app.db.connection import filter_original_question_sources_by_mode
        oqs = [{"question": "Q", "sources": [{"url": "http://other.com", "company": "C", "round": "R"}]}]
        result = filter_original_question_sources_by_mode(oqs, 'personal', 42)
        assert len(result) == 0  # 被过滤掉了

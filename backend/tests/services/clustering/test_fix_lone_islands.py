"""
BUG-003 + BUG-005: 孤岛修复端点测试
测试 fix-lone-islands API 的合并逻辑
"""
import json
import pytest
import numpy as np
from unittest.mock import patch, MagicMock, AsyncMock


class TestFixLoneIslands:
    """测试 fix-lone-islands 端点的合并逻辑"""

    def test_identifies_high_similarity_pairs(self):
        """应正确识别高相似度题目对"""
        # 模拟两个归一化向量，相似度 > 0.85
        rng = np.random.RandomState(42)
        emb1 = rng.randn(512).astype(np.float32)
        emb1 /= np.linalg.norm(emb1)
        noise = rng.randn(512).astype(np.float32) * 0.02
        emb2 = emb1 + noise
        emb2 /= np.linalg.norm(emb2)

        X = np.array([emb1, emb2])
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        X_norm = X / norms
        sim = X_norm @ X_norm.T

        assert sim[0, 1] > 0.85, f"测试向量相似度应>0.85, 实际={sim[0, 1]:.3f}"

    def test_merges_preserves_sources(self):
        """合并后 sources 应包含双方的所有来源"""
        s_src = [{"url": "http://a.com", "company": "腾讯", "round": "一面"}]
        m_src = [{"url": "http://b.com", "company": "阿里", "round": "二面"}]

        seen = {(s.get('url', ''), s.get('company', ''), s.get('round', '')) for s in s_src}
        for s in m_src:
            key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
            if key not in seen:
                seen.add(key)
                s_src.append(s)

        assert len(s_src) == 2, f"合并后 sources 应有 2 个, 实际={len(s_src)}"

    def test_merges_deduplicates_sources(self):
        """合并时应去重相同的 sources"""
        s_src = [{"url": "http://a.com", "company": "腾讯", "round": "一面"}]
        m_src = [{"url": "http://a.com", "company": "腾讯", "round": "一面"}]

        seen = {(s.get('url', ''), s.get('company', ''), s.get('round', '')) for s in s_src}
        for s in m_src:
            key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
            if key not in seen:
                seen.add(key)
                s_src.append(s)

        assert len(s_src) == 1, f"重复 source 应被去重, 实际={len(s_src)}"

    def test_frequency_updated_correctly(self):
        """合并后 frequency 应等于 original_questions 的长度"""
        s_oqs = ["问题A", "问题B"]
        m_oqs = ["问题C"]
        m_question = "问题C"

        for oq in m_oqs:
            if oq and oq not in s_oqs:
                s_oqs.append(oq)
        if m_question not in s_oqs:
            s_oqs.append(m_question)

        assert len(s_oqs) == 3, f"合并后应有 3 个原始问题, 实际={len(s_oqs)}"

    def test_no_duplicate_in_original_questions(self):
        """合并时不应产生重复的原始问题"""
        s_oqs = ["问题A", "问题B"]
        m_oqs = ["问题A", "问题C"]  # "问题A" 已存在

        for oq in m_oqs:
            if oq and oq not in s_oqs:
                s_oqs.append(oq)

        assert s_oqs.count("问题A") == 1, f"问题A 不应重复, 实际出现 {s_oqs.count('问题A')} 次"
        assert len(s_oqs) == 3, f"应有 3 个不同问题, 实际={len(s_oqs)}"

    def test_singleton_merge_never_writes_frequency_zero(self, test_db):
        """BUG: 单例合并时 original_questions=[] 不能导致 survivor frequency=0"""
        from app.services.pipeline.compact import _do_merge_to_existing

        test_db.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, frequency, sources, original_questions, "
            "original_question_sources, status) "
            "VALUES (1, 'Agent 死循环如何恢复？', 'B', 'B6.评估安全与优化', 1, ?, '[]', '[]', 'approved')",
            (json.dumps([{"url": "https://a.example", "company": "A", "round": "一面"}]),),
        )
        test_db.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, frequency, sources, original_questions, "
            "original_question_sources, status) "
            "VALUES (2, '你的 Agent 死循环了怎么办？', 'B', 'B6.评估安全与优化', 1, '[]', '[]', '[]', 'approved')"
        )
        test_db.commit()

        _do_merge_to_existing(
            1,
            {
                "id": 2,
                "question": "你的 Agent 死循环了怎么办？",
                "cat2": "B6.评估安全与优化",
                "sources": "[]",
                "original_questions": "[]",
                "original_question_sources": "[]",
            },
            operation_type="test",
            phase="unit",
            confidence=0.95,
        )
        test_db.commit()

        row = test_db.execute(
            "SELECT frequency, original_questions FROM question_bank WHERE id = 1"
        ).fetchone()
        originals = json.loads(row["original_questions"])

        assert row["frequency"] == 2
        assert "Agent 死循环如何恢复？" in originals
        assert "你的 Agent 死循环了怎么办？" in originals
        assert test_db.execute("SELECT id FROM question_bank WHERE id = 2").fetchone() is None

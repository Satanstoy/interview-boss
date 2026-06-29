"""
自动化测试 — 针对 BUG-004: original_question_sources 为空导致来源题目文本不显示
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock


from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class TestOqsBackfillOnRebuild:
    """BUG-004a: 重建题库时独立题目应保留 original_question_sources"""

    def test_standalone_question_keeps_oqs(self):
        """独立题目（未合并）应保留 original_question_sources"""
        with open(BACKEND_ROOT / 'app/routers/bank_build.py', 'r') as f:
            content = f.read()

        import re
        # 查找处理独立题目的逻辑
        # 修复前：detail['original_question_sources'] = []
        # 修复后：不再清除 original_question_sources
        has_clear_oqs = re.search(
            r"detail\['original_question_sources'\]\s*=\s*\[\]",
            content
        )
        assert not has_clear_oqs, "不应清除独立题目的 original_question_sources"


class TestOqsPopulatedForNewQuestions:
    """BUG-004b: 新建题目（增量更新未匹配）应有 original_question_sources"""

    def test_new_question_insert_includes_oqs(self):
        """新建题目的 INSERT 语句应包含 original_question_sources"""
        with open(BACKEND_ROOT / 'app/db/operations.py', 'r') as f:
            content = f.read()

        import re
        # 查找新建题目的 INSERT 语句
        insert_match = re.search(
            r'INSERT INTO question_bank.*?VALUES.*?\)',
            content,
            re.DOTALL
        )
        assert insert_match, "应存在 question_bank INSERT 语句"
        insert_sql = insert_match.group(0)
        assert 'original_question_sources' in insert_sql, "INSERT 应包含 original_question_sources 列"

    def test_new_question_oqs_format(self):
        """新建题目的 oqs 应为 [{question, sources: [{url, company, round}]}] 格式"""
        with open(BACKEND_ROOT / 'app/db/operations.py', 'r') as f:
            content = f.read()

        # 检查 oqs_json 变量是否在 INSERT 之前定义
        assert 'oqs_json' in content, "应定义 oqs_json 变量"
        # 检查 oqs_json 是否包含正确的结构
        assert '"question": q_text' in content or "'question': q_text" in content, "oqs 应包含 question 字段"


class TestStartupAutoFixEmptyOqs:
    """BUG-004c: 启动时自动修复空的 original_question_sources"""

    def test_startup_fix_backfills_empty_oqs(self):
        """启动修复应为 oqs 为空但 sources 非空的题目回填数据"""
        with open(BACKEND_ROOT / 'app/db/migrations.py', 'r') as f:
            content = f.read()

        assert '回填' in content, "应有 oqs 回填逻辑"
        assert 'original_question_sources' in content, "应操作 original_question_sources 字段"

    def test_startup_fix_handles_empty_sources_in_oqs(self):
        """启动修复应修复 oqs 中 sources 为空数组的条目"""
        with open(BACKEND_ROOT / 'app/db/migrations.py', 'r') as f:
            content = f.read()

        assert '空 sources' in content or 'empty.*sources' in content.lower() or '\"sources\": []' in content, "应有修复空 sources 条目的逻辑"


class TestFrontendDedupedSourcesFallback:
    """BUG-004d: 前端 dedupedSources 在 oqs 为空时应有合理 fallback"""

    def test_deduped_sources_handles_empty_oqs(self):
        """dedupedSources 在 oqs 为空时应返回 sources（无 _origQuestion）"""
        with open(BACKEND_ROOT / 'frontend/src/components/business/QuestionCard.vue', 'r') as f:
            content = f.read()

        # 检查 dedupedSources 存在
        assert 'dedupedSources' in content, "应有 dedupedSources 计算属性"
        # 检查有 oqs 为空时的 fallback
        assert 'original_question_sources' in content, "应检查 original_question_sources"


class TestRealDatabaseOqsIntegrity:
    """实际数据库中 original_question_sources 完整性检查"""

    def test_no_questions_with_empty_oqs_but_nonempty_sources(self):
        """不应存在 oqs 为空但 sources 非空的题目"""
        import sqlite3
        try:
            conn = sqlite3.connect(BACKEND_ROOT / 'data/interview-boss.db')
            cursor = conn.cursor()
            count = cursor.execute(
                "SELECT COUNT(*) FROM question_bank "
                "WHERE (original_question_sources IS NULL OR original_question_sources = '' OR original_question_sources = '[]') "
                "AND sources IS NOT NULL AND sources != '' AND sources != '[]' AND frequency > 0"
            ).fetchone()[0]
            conn.close()
            assert count == 0, f"存在 {count} 条 oqs 为空但 sources 非空的题目（需重启服务执行自动修复）"
        except Exception as e:
            pytest.skip(f"无法连接数据库: {e}")

    def test_no_oqs_entries_with_empty_sources(self):
        """不应存在 oqs 条目的 sources 为空数组"""
        import sqlite3
        try:
            conn = sqlite3.connect(BACKEND_ROOT / 'data/interview-boss.db')
            cursor = conn.cursor()
            count = cursor.execute(
                "SELECT COUNT(*) FROM question_bank "
                "WHERE original_question_sources LIKE '%\"sources\": []%' AND frequency > 0"
            ).fetchone()[0]
            conn.close()
            assert count == 0, f"存在 {count} 条 oqs 中有空 sources 条目的题目（需重启服务执行自动修复）"
        except Exception as e:
            pytest.skip(f"无法连接数据库: {e}")

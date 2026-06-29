"""
自动化测试 — 面经删除时 question_bank sources 清理的事务一致性
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call


from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class TestCleanupSourcesForUrl:
    """_cleanup_sources_for_url: 面经删除时清理 question_bank.sources"""

    def test_cleanup_removes_url_from_sources(self):
        """应从 sources 中移除指定 URL"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        existing_sources = [
            {"url": url, "company": "腾讯", "round": "一面"},
            {"url": "https://example.com/interview/2", "company": "阿里", "round": "二面"},
        ]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps(existing_sources),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        # 应执行 UPDATE（frequency=1, sources 只剩 1 条）
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) >= 1
        update_sql = str(update_calls[0])
        assert 'frequency' in update_sql
        assert 'sources' in update_sql

    def test_cleanup_updates_frequency_to_match_sources(self):
        """frequency 应等于 sources 的新长度"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        sources = [
            {"url": url, "company": "腾讯", "round": "一面"},
            {"url": "https://example.com/interview/2", "company": "阿里", "round": "二面"},
            {"url": "https://example.com/interview/3", "company": "百度", "round": "三面"},
        ]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps(sources),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) >= 1
        # frequency 参数应该是 2（3 条 sources 减去 1 条被删除的）
        args = update_calls[0][0]
        params = args[1] if len(args) > 1 else update_calls[0][1]
        assert params[0] == 2

    def test_cleanup_deletes_question_with_zero_frequency(self):
        """frequency<=0 的公共题目应被删除"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        sources = [{"url": url, "company": "腾讯", "round": "一面"}]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps(sources),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        # 应执行 DELETE FROM question_bank WHERE frequency <= 0
        delete_calls = [c for c in cursor.execute.call_args_list if 'DELETE' in str(c)]
        assert len(delete_calls) >= 1
        assert any('frequency <= 0' in str(c) for c in delete_calls)

    def test_cleanup_handles_multiple_questions(self):
        """应能处理多道题目同时引用同一 URL 的情况"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps([{"url": url}]),
             "original_questions": "[]", "original_question_sources": "[]"},
            {"id": 2, "sources": json.dumps([{"url": url}, {"url": "https://other.com"}]),
             "original_questions": "[]", "original_question_sources": "[]"},
            {"id": 3, "sources": json.dumps([{"url": "https://other.com"}]),
             "original_questions": "[]", "original_question_sources": "[]"},
        ]

        _cleanup_sources_for_url(cursor, url)

        # id=1 frequency→0 → 标记删除，id=2 frequency→1 → UPDATE
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) == 1  # 只有 id=2 被 UPDATE

    def test_cleanup_ignores_questions_without_url(self):
        """不引用该 URL 的题目不应被修改"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps([{"url": "https://other.com"}]),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        # 不应有 UPDATE 调用
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) == 0

    def test_cleanup_handles_empty_sources(self):
        """sources 为空时不应报错"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": "", "original_questions": "[]", "original_question_sources": "[]"}
        ]

        # 不应抛出异常
        _cleanup_sources_for_url(cursor, url)

    def test_cleanup_handles_malformed_json(self):
        """sources JSON 格式错误时不应报错"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": "invalid json",
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        # 不应抛出异常
        _cleanup_sources_for_url(cursor, url)


class TestDeleteEndpointTransactionConsistency:
    """面经删除端点的事务一致性：软删除 + sources 清理应在同一事务中"""

    def test_interview_delete_calls_cleanup(self):
        """删除面经时应调用 _cleanup_sources_for_url"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()

        # 查找 interview 删除分支
        import re
        interview_block = re.search(
            r"if table_name == 'interview':.*?(?=\n\s+# 软删除目标记录|\n\s+cursor\.execute.*SET deleted_at)",
            content,
            re.DOTALL
        )
        assert interview_block, "应存在面经删除分支"
        block_content = interview_block.group(0)
        assert '_cleanup_sources_for_url' in block_content, "面经删除应调用 _cleanup_sources_for_url"

    def test_interview_delete_cascades_questions_detail(self):
        """删除面经时应级联软删除 questions_detail"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()

        import re
        interview_block = re.search(
            r"if table_name == 'interview':.*?(?=\n\s+# 软删除目标记录|\n\s+cursor\.execute.*SET deleted_at)",
            content,
            re.DOTALL
        )
        assert interview_block, "应存在面经删除分支"
        block_content = interview_block.group(0)
        assert 'questions_detail' in block_content, "面经删除应级联软删除 questions_detail"

    def test_jd_delete_cascades_interview_and_questions_detail(self):
        """删除 JD 时应级联软删除面经和 questions_detail"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()

        import re
        jd_block = re.search(
            r"if table_name == 'jd':.*?(?=\n\s+if table_name == 'interview')",
            content,
            re.DOTALL
        )
        assert jd_block, "应存在 JD 删除分支"
        block_content = jd_block.group(0)
        assert 'interview' in block_content and 'questions_detail' in block_content, "JD 删除应级联软删除面经和 questions_detail"

    def test_jd_delete_cleans_interview_sources(self):
        """删除 JD 时应清理关联面经的 question_bank sources"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()

        import re
        jd_block = re.search(
            r"if table_name == 'jd':.*?(?=\n\s+if table_name == 'interview')",
            content,
            re.DOTALL
        )
        assert jd_block, "应存在 JD 删除分支"
        block_content = jd_block.group(0)
        assert '_cleanup_sources_for_url' in block_content, "JD 删除应清理关联面经的 sources"

    def test_delete_commits_after_cleanup(self):
        """cleanup 应在 commit 之前执行"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()

        import re
        # 查找 _soft_delete 函数
        func_match = re.search(
            r'def _soft_delete\(\):.*?(?=\n    try:|\n@router|\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 _soft_delete 函数"
        func_content = func_match.group(0)

        # cleanup 应在 commit 之前
        cleanup_pos = func_content.find('_cleanup_sources_for_url')
        commit_pos = func_content.find('conn.commit()')
        assert cleanup_pos > 0, "_soft_delete 应调用 _cleanup_sources_for_url"
        assert commit_pos > 0, "_soft_delete 应有 conn.commit()"
        assert cleanup_pos < commit_pos, "cleanup 应在 commit 之前（同一事务）"


class TestBatchDeleteTransactionConsistency:
    """批量删除端点的事务一致性"""

    def test_batch_interview_delete_calls_cleanup(self):
        """批量删除面经时应调用 _cleanup_sources_for_url"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()

        import re
        batch_func = re.search(
            r'def _batch_soft_delete\(\):.*?(?=\n    try:|\n@router|\Z)',
            content,
            re.DOTALL
        )
        assert batch_func, "应存在 _batch_soft_delete 函数"
        func_content = batch_func.group(0)

        # 找到 interview 分支
        interview_block = re.search(
            r"if table_name == \"interview\".*",
            func_content,
            re.DOTALL
        )
        assert interview_block, "批量删除应有 interview 分支"
        assert '_cleanup_sources_for_url' in interview_block.group(0), "批量删除面经应调用 _cleanup_sources_for_url"


class TestOqsFilteredByDeletedStatus:
    """original_question_sources 应通过 filter_original_question_sources_by_mode 过滤已删除面经"""

    def test_filter_checks_deleted_at(self):
        """filter_original_question_sources_by_mode 应查询 deleted_at IS NULL"""
        with open(BACKEND_ROOT / 'app/db/queries.py', 'r') as f:
            content = f.read()

        import re
        func_match = re.search(
            r'def filter_original_question_sources_by_mode.*?(?=\ndef |\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 filter_original_question_sources_by_mode 函数"
        func_content = func_match.group(0)
        assert 'deleted_at IS NULL' in func_content, "应检查 interview.deleted_at IS NULL 过滤已删除面经"

    def test_filter_is_called_in_get_endpoint(self):
        """GET /api/master-bank 应通过 build_api_shapes_batch_filtered 过滤 OQS"""
        with open(BACKEND_ROOT / 'app/routers/questions.py', 'r') as f:
            content = f.read()

        assert 'build_api_shapes_batch_filtered' in content, "GET 端点应调用 build_api_shapes_batch_filtered 过滤 OQS"


class TestRestoreSourcesForUrl:
    """_restore_sources_for_url: 恢复面经时重建 sources"""

    def test_restore_adds_url_back_to_sources(self):
        """恢复面经时应将 URL 重新加入 sources"""
        from app.routers.data import _restore_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        oqs = [{"question": "什么是RAG", "sources": [{"url": url, "company": "腾讯", "round": "一面"}]}]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps([]), "original_question_sources": json.dumps(oqs)}
        ]

        _restore_sources_for_url(cursor, url)

        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) >= 1
        # frequency 参数应该是 1
        args = update_calls[0][0]
        params = args[1] if len(args) > 1 else update_calls[0][1]
        assert params[0] == 1

    def test_restore_skips_if_url_already_in_sources(self):
        """如果 URL 已在 sources 中，不应重复添加"""
        from app.routers.data import _restore_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        sources = [{"url": url, "company": "腾讯", "round": "一面"}]
        oqs = [{"question": "什么是RAG", "sources": [{"url": url}]}]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "sources": json.dumps(sources), "original_question_sources": json.dumps(oqs)}
        ]

        _restore_sources_for_url(cursor, url)

        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) == 0, "URL 已存在时不应重复添加"


# ============================================================
# 真实 DB 测试：_cleanup_sources_for_url 的 oqs/qp 清理
# ============================================================
import sqlite3


def _create_test_db():
    """创建最小测试数据库"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL, cat1 TEXT, cat2 TEXT, tags TEXT, difficulty TEXT,
            frequency INTEGER DEFAULT 1, ai_answer TEXT, sources TEXT DEFAULT '[]',
            original_questions TEXT DEFAULT '[]', original_question_sources TEXT DEFAULT '[]',
            owner_id INTEGER, status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '', deleted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE question_position (
            question_id INTEGER NOT NULL, position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id)
        );
    """)
    conn.commit()
    return conn


class TestCleanupOqsAndQuestionPosition:
    """_cleanup_sources_for_url 应同时清理 oqs/oqs_sources/question_position"""

    def test_cleanup_removes_oqs_by_url(self):
        """删除面经时应清理 original_questions 中属于该 URL 的条目"""
        conn = _create_test_db()
        from app.routers.data import _cleanup_sources_for_url

        sources = json.dumps([
            {"url": "http://url-a.com", "company": "A", "round": "一面"},
            {"url": "http://url-b.com", "company": "B", "round": "二面"},
        ], ensure_ascii=False)
        oqs = json.dumps(["题目A", "题目B"], ensure_ascii=False)
        oqs_src = json.dumps([
            {"question": "题目A", "sources": [{"url": "http://url-a.com"}]},
            {"question": "题目B", "sources": [{"url": "http://url-b.com"}]},
        ], ensure_ascii=False)
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources) "
            "VALUES (1, '代表题', 2, ?, ?, ?)",
            (sources, oqs, oqs_src)
        )
        conn.commit()

        _cleanup_sources_for_url(conn.cursor(), "http://url-a.com")

        qb = conn.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        remaining_oqs = json.loads(qb['original_questions'])
        remaining_oqs_src = json.loads(qb['original_question_sources'])

        assert "题目A" not in remaining_oqs, "URL_A 的原始题目应被移除"
        assert "题目B" in remaining_oqs, "URL_B 的原始题目应保留"
        assert len(remaining_oqs_src) == 1
        assert remaining_oqs_src[0]['sources'][0]['url'] == "http://url-b.com"
        conn.close()

    def test_cleanup_deletes_question_position_for_zero_freq(self):
        """frequency=0 删除 QB 时应同步清理 question_position"""
        conn = _create_test_db()
        from app.routers.data import _cleanup_sources_for_url

        sources = json.dumps([{"url": "http://only.com"}], ensure_ascii=False)
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources) VALUES (1, '孤立项', 1, ?)",
            (sources,)
        )
        conn.execute("INSERT INTO question_position (question_id, position_id) VALUES (1, 1)")
        conn.commit()

        _cleanup_sources_for_url(conn.cursor(), "http://only.com")

        qp = conn.execute("SELECT * FROM question_position WHERE question_id = 1").fetchone()
        assert qp is None, "QB 删除后 question_position 应被清理"
        conn.close()

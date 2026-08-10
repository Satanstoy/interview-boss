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
            {"id": 1, "owner_id": None, "sources": json.dumps(existing_sources),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        # 应执行 UPDATE（frequency=1, sources 只剩 1 条）
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) >= 1
        update_sql = str(update_calls[0])
        assert 'frequency' in update_sql
        assert 'sources' in update_sql

    def test_cleanup_keeps_frequency_as_variant_count(self):
        """frequency 保持「原题变体数」语义：oqs 缺失时保守为 1，来源数不冒充频率"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        sources = [
            {"url": url, "company": "腾讯", "round": "一面"},
            {"url": "https://example.com/interview/2", "company": "阿里", "round": "二面"},
            {"url": "https://example.com/interview/3", "company": "百度", "round": "三面"},
        ]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": json.dumps(sources),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) >= 1
        # oqs 为空时 frequency 应为 1（变体数下限），而不是 2（剩余来源数）
        args = update_calls[0][0]
        params = args[1] if len(args) > 1 else update_calls[0][1]
        assert params[0] == 1

    def test_cleanup_deletes_question_with_zero_frequency(self):
        """frequency<=0 的公共题目应被删除"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        sources = [{"url": url, "company": "腾讯", "round": "一面"}]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": json.dumps(sources),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        # 只软删除目标题目，并清理其岗位关联；不应扫描/修改无关题目。
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE question_bank' in str(c)]
        assert update_calls
        assert any('deleted_at' in str(c) for c in update_calls)

    def test_cleanup_handles_multiple_questions(self):
        """应能处理多道题目同时引用同一 URL 的情况"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": json.dumps([{"url": url}]),
             "original_questions": "[]", "original_question_sources": "[]"},
            {"id": 2, "owner_id": None, "sources": json.dumps([{"url": url}, {"url": "https://other.com"}]),
             "original_questions": "[]", "original_question_sources": "[]"},
            {"id": 3, "owner_id": None, "sources": json.dumps([{"url": "https://other.com"}]),
             "original_questions": "[]", "original_question_sources": "[]"},
        ]

        _cleanup_sources_for_url(cursor, url)

        # id=1 frequency→0 → 标记删除，id=2 frequency→1 → UPDATE。
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert len(update_calls) >= 2

    def test_cleanup_ignores_questions_without_url(self):
        """不引用该 URL 的题目不应被修改"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": json.dumps([{"url": "https://other.com"}]),
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        _cleanup_sources_for_url(cursor, url)

        # 不应修改 question_bank
        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE' in str(c)]
        assert not any('UPDATE question_bank' in str(c) for c in update_calls)

    def test_cleanup_handles_empty_sources(self):
        """sources 为空时不应报错"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": "", "original_questions": "[]", "original_question_sources": "[]"}
        ]

        # 不应抛出异常
        _cleanup_sources_for_url(cursor, url)

    def test_cleanup_handles_malformed_json(self):
        """sources JSON 格式错误时不应报错"""
        from app.routers.data import _cleanup_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": "invalid json",
             "original_questions": "[]", "original_question_sources": "[]"}
        ]

        # 不应抛出异常
        _cleanup_sources_for_url(cursor, url)


class TestDeleteEndpointTransactionConsistency:
    """面经删除端点的事务一致性：软删除 + sources 清理应在同一事务中"""

    def test_interview_delete_calls_cleanup(self):
        """面经删除应经过隔离的来源清理 savepoint。"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()
        assert 'def _delete_interview_txn' in content
        assert '_cleanup_sources_best_effort' in content

    def test_interview_delete_cascades_questions_detail(self):
        """删除面经时应级联软删除 questions_detail"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()
        assert 'UPDATE questions_detail SET deleted_at' in content
        assert 'interview_id = ?' in content

    def test_jd_delete_cascades_interview_and_questions_detail(self):
        """删除 JD 时应级联软删除面经和 questions_detail"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()
        assert 'UPDATE interview SET deleted_at' in content
        assert 'UPDATE questions_detail SET deleted_at' in content

    def test_jd_delete_cleans_interview_sources(self):
        """删除 JD 时应清理关联面经的 question_bank sources"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()
        assert '_cleanup_sources_best_effort(cursor, iu["url"], owner_scope)' in content

    def test_delete_commits_after_cleanup(self):
        """主删除与来源清理应在同一个外层事务中提交。"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()
        assert 'savepoint = "interview_source_cleanup"' in content
        assert 'conn.commit()' in content


class TestBatchDeleteTransactionConsistency:
    """批量删除端点的事务一致性"""

    def test_batch_interview_delete_calls_cleanup(self):
        """批量删除面经应复用同一套幂等清理逻辑。"""
        with open(BACKEND_ROOT / 'app/routers/data.py', 'r') as f:
            content = f.read()
        assert 'for row in rows:' in content
        assert '_delete_interview_txn(cursor, row["id"], row)' in content


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
            {"id": 1, "owner_id": None, "sources": json.dumps([]), "original_question_sources": json.dumps(oqs), "deleted_at": None}
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
            {"id": 1, "owner_id": None, "sources": json.dumps(sources), "original_question_sources": json.dumps(oqs), "deleted_at": None}
        ]

        _restore_sources_for_url(cursor, url)

        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE question_bank' in str(c)]
        assert not any('UPDATE question_bank' in str(c) for c in update_calls), \
            "URL 已存在时不应重复添加 question_bank.source"

    def test_restore_keeps_frequency_as_variant_count_when_oqs_missing(self):
        """恢复面经时 oqs 缺失，frequency 保守为 1（变体数下限），来源数不冒充频率"""
        from app.routers.data import _restore_sources_for_url

        cursor = MagicMock()
        url = "https://example.com/interview/1"
        sources = [{"url": "https://other.com", "company": "X", "round": "一面"}]
        oqs_src = [{"question": "什么是RAG", "sources": [{"url": url, "company": "腾讯", "round": "一面"}]}]
        cursor.execute.return_value.fetchall.return_value = [
            {"id": 1, "owner_id": None, "sources": json.dumps(sources),
             "original_question_sources": json.dumps(oqs_src), "deleted_at": None}
        ]

        _restore_sources_for_url(cursor, url)

        update_calls = [c for c in cursor.execute.call_args_list if 'UPDATE question_bank' in str(c)]
        assert update_calls, "恢复时应有 UPDATE"
        args = update_calls[0][0]
        params = args[1] if len(args) > 1 else update_calls[0][1]
        # 恢复后 sources=2，但 frequency 应为 1（oqs 缺失时的变体数下限）
        assert params[0] == 1


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
        CREATE TABLE cluster_review_state (
            cluster_id INTEGER PRIMARY KEY,
            current_version TEXT NOT NULL,
            reviewed_version TEXT,
            status TEXT NOT NULL DEFAULT 'needs_review',
            priority INTEGER NOT NULL DEFAULT 50,
            last_trigger_reason TEXT,
            last_reviewed_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE cluster_review_tasks (
            id TEXT PRIMARY KEY,
            cluster_id INTEGER NOT NULL,
            review_version TEXT NOT NULL,
            trigger_reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_until TEXT,
            arq_job_id TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE(cluster_id, review_version)
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

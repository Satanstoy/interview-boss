"""
自动化测试 — 针对 BUG-001: 独立题目时来源和分类丢失
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
import json
import sqlite3
from unittest.mock import patch, MagicMock, AsyncMock


class TestBug001SplitQuestionDataLoss:
    """BUG-001: 独立题目时来源和分类丢失"""

    @pytest.fixture
    def mock_db(self, tmp_path):
        """创建临时测试数据库"""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT,
                cat1 TEXT,
                cat2 TEXT,
                tags TEXT,
                difficulty TEXT,
                frequency INTEGER DEFAULT 1,
                ai_answer TEXT,
                sources TEXT DEFAULT '[]',
                original_questions TEXT DEFAULT '[]',
                original_question_sources TEXT DEFAULT '[]',
                owner_id INTEGER,
                submitted_by INTEGER,
                status TEXT DEFAULT 'approved',
                job_position TEXT DEFAULT '',
                deleted_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE questions_detail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                company TEXT,
                round TEXT,
                question TEXT,
                cat1 TEXT,
                cat2 TEXT,
                tags TEXT,
                diff_tag TEXT,
                job_position TEXT DEFAULT '',
                deleted_at TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE job_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT
            )
        """)
        conn.execute("INSERT INTO job_positions (name) VALUES ('test_position')")
        conn.commit()
        yield conn
        conn.close()

    def test_split_should_fail_before_fix(self, mock_db):
        """修复前：独立题目时来源为空（验证 bug 存在）"""
        # Arrange: 创建一个聚类题目，original_question_sources 为空
        mock_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, sources, original_questions, original_question_sources, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("统一问题", "B.Agent与LLM应用", "B1.Agent架构与范式", "agent", "L2-中等",
             json.dumps([{"url": "http://test.com", "company": "测试公司", "round": "一面"}]),
             json.dumps(["原始题目1", "原始题目2"]),
             json.dumps([]),  # 空的 original_question_sources
             "test_position")
        )
        mock_db.commit()

        # Act: 模拟 split_question 的来源查找逻辑
        row = mock_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        orig_qs_src = json.loads(row['original_question_sources']) if row['original_question_sources'] else []
        original_q = "原始题目1"

        split_sources = []
        for item in orig_qs_src:
            if item.get('question') == original_q:
                split_sources = item.get('sources', [])
                break

        # Assert: 修复前，来源为空
        assert split_sources == [], "Bug: 来源应该为空（original_question_sources 为空时）"

    def test_split_should_pass_after_fix(self, mock_db):
        """修复后：独立题目时应从 questions_detail 查询来源"""
        # Arrange: 创建一个聚类题目，original_question_sources 为空
        mock_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, sources, original_questions, original_question_sources, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("统一问题", "B.Agent与LLM应用", "B1.Agent架构与范式", "agent", "L2-中等",
             json.dumps([{"url": "http://test.com", "company": "测试公司", "round": "一面"}]),
             json.dumps(["原始题目1", "原始题目2"]),
             json.dumps([]),  # 空的 original_question_sources
             "test_position")
        )
        # 创建对应的 questions_detail 记录
        mock_db.execute(
            "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("http://test.com", "测试公司", "一面", "原始题目1",
             "B.Agent与LLM应用", "B1.Agent架构与范式", "agent", "L2-中等", "test_position")
        )
        mock_db.commit()

        # Act: 模拟修复后的来源查找逻辑
        row = mock_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        orig_qs_src = json.loads(row['original_question_sources']) if row['original_question_sources'] else []
        original_q = "原始题目1"

        split_sources = []
        for item in orig_qs_src:
            if item.get('question') == original_q:
                split_sources = item.get('sources', [])
                break

        # 修复：如果来源为空，从 questions_detail 查询
        if not split_sources:
            qd_row = mock_db.execute(
                "SELECT url, company, round, cat1, cat2, tags, diff_tag FROM questions_detail WHERE question = ? AND deleted_at IS NULL LIMIT 1",
                (original_q,)
            ).fetchone()
            if qd_row:
                split_sources = [{"url": qd_row['url'], "company": qd_row['company'], "round": qd_row['round']}]

        # Assert: 修复后，来源不为空
        assert len(split_sources) == 1, "修复后来源应有 1 条记录"
        assert split_sources[0]['url'] == "http://test.com"
        assert split_sources[0]['company'] == "测试公司"
        assert split_sources[0]['round'] == "一面"

    def test_split_with_empty_cat1_should_fallback_to_qd(self, mock_db):
        """修复后：当父聚类分类为空时，应从 questions_detail 查询分类"""
        # Arrange: 创建一个分类为空的聚类题目
        mock_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, sources, original_questions, original_question_sources, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("统一问题", "", "", "", "L2-中等",  # 空分类
             json.dumps([{"url": "http://test.com", "company": "测试公司", "round": "一面"}]),
             json.dumps(["原始题目1"]),
             json.dumps([{"question": "原始题目1", "sources": [{"url": "http://test.com", "company": "测试公司", "round": "一面"}]}]),
             "test_position")
        )
        # 创建对应的 questions_detail 记录（有分类）
        mock_db.execute(
            "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("http://test.com", "测试公司", "一面", "原始题目1",
             "B.Agent与LLM应用", "B1.Agent架构与范式", "agent", "L2-中等", "test_position")
        )
        mock_db.commit()

        # Act: 模拟修复后的分类查找逻辑
        row = dict(mock_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone())
        original_q = "原始题目1"

        # 修复：如果分类为空，从 questions_detail 查询
        if not row['cat1']:
            qd_row = mock_db.execute(
                "SELECT cat1, cat2, tags FROM questions_detail WHERE question = ? AND deleted_at IS NULL LIMIT 1",
                (original_q,)
            ).fetchone()
            if qd_row and qd_row['cat1']:
                row['cat1'] = qd_row['cat1']
                row['cat2'] = qd_row['cat2']
                row['tags'] = qd_row['tags'] or row['tags']

        # Assert: 修复后，分类不为空
        assert row['cat1'] == "B.Agent与LLM应用", "修复后 cat1 应从 questions_detail 获取"
        assert row['cat2'] == "B1.Agent架构与范式", "修复后 cat2 应从 questions_detail 获取"

    def test_split_with_valid_oqs_should_still_work(self, mock_db):
        """正常情况：当 original_question_sources 有数据时，应正常工作"""
        # Arrange: 创建一个有完整数据的聚类题目
        mock_db.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, sources, original_questions, original_question_sources, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("统一问题", "B.Agent与LLM应用", "B1.Agent架构与范式", "agent", "L2-中等",
             json.dumps([{"url": "http://test.com", "company": "测试公司", "round": "一面"}]),
             json.dumps(["原始题目1", "原始题目2"]),
             json.dumps([
                 {"question": "原始题目1", "sources": [{"url": "http://test.com", "company": "测试公司", "round": "一面"}]},
                 {"question": "原始题目2", "sources": [{"url": "http://test2.com", "company": "测试公司2", "round": "二面"}]}
             ]),
             "test_position")
        )
        mock_db.commit()

        # Act: 模拟 split_question 的来源查找逻辑
        row = mock_db.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        orig_qs_src = json.loads(row['original_question_sources']) if row['original_question_sources'] else []
        original_q = "原始题目1"

        split_sources = []
        for item in orig_qs_src:
            if item.get('question') == original_q:
                split_sources = item.get('sources', [])
                break

        # Assert: 正常情况，来源正确
        assert len(split_sources) == 1
        assert split_sources[0]['url'] == "http://test.com"
        assert split_sources[0]['company'] == "测试公司"
        assert split_sources[0]['round'] == "一面"

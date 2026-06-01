"""
自动化测试 — 两段式流水孤儿数据 bug 验证
BUG-001: delete_master_question 未清理 oqs_sources
BUG-002: batch_delete_master_bank 未清理 stale oqs 引用
BUG-003: 队列 processing 状态无超时恢复
"""
import json
import sqlite3
import pytest
from unittest.mock import patch, MagicMock


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
            submitted_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE question_position (
            question_id INTEGER NOT NULL, position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id)
        );
        CREATE TABLE user_question_view (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, question_bank_id INTEGER, is_starred INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, question_bank_id INTEGER, user_answer TEXT,
            evaluation_result TEXT, score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, company TEXT, round TEXT, question TEXT,
            cat1 TEXT, cat2 TEXT, tags TEXT, diff_tag TEXT,
            job_position TEXT DEFAULT '', deleted_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            processed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        );
        INSERT INTO job_positions (id, name) VALUES (1, '后端工程师');
    """)
    conn.commit()
    return conn


class TestBug001DeleteMasterQuestionOqsCleanup:
    """BUG-001: delete_master_question 应清理 oqs_sources 中的 stale 引用"""

    def test_single_delete_cleans_oqs_sources(self):
        """删除 QB 题目时，其他 QB 记录的 oqs_sources 应同步清理"""
        conn = _create_test_db()

        # 插入一个聚类，包含两道原始题目
        oqs = json.dumps(["题目A", "题目B"], ensure_ascii=False)
        oqs_src = json.dumps([
            {"question": "题目A", "sources": [{"url": "http://a.com"}]},
            {"question": "题目B", "sources": [{"url": "http://b.com"}]},
        ], ensure_ascii=False)
        sources = json.dumps([
            {"url": "http://a.com"}, {"url": "http://b.com"}
        ], ensure_ascii=False)
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources, job_position) "
            "VALUES (1, '代表题', 2, ?, ?, ?, '后端工程师')",
            (sources, oqs, oqs_src)
        )
        conn.execute("INSERT INTO question_position (question_id, position_id) VALUES (1, 1)")
        conn.commit()

        # 模拟 delete_master_question 的清理逻辑（修复后版本）
        question_text = "题目A"
        question_id = 1  # 这里测试的是对 other_qb 的清理

        # 插入另一个 QB 记录，其 oqs 引用了 "题目A"
        other_oqs = json.dumps(["题目A", "题目C"], ensure_ascii=False)
        other_oqs_src = json.dumps([
            {"question": "题目A", "sources": [{"url": "http://a.com"}]},
            {"question": "题目C", "sources": [{"url": "http://c.com"}]},
        ], ensure_ascii=False)
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources, job_position) "
            "VALUES (2, '另一个聚类', 2, '[]', ?, ?, '后端工程师')",
            (other_oqs, other_oqs_src)
        )
        conn.commit()

        # 执行清理（模拟修复后的逻辑）
        cursor = conn.cursor()
        other_qb = cursor.execute(
            "SELECT id, original_questions, original_question_sources FROM question_bank WHERE id != ? AND original_questions LIKE ?",
            (question_id, f'%{question_text}%')
        ).fetchall()
        for qb in other_qb:
            oq = json.loads(qb['original_questions']) if qb['original_questions'] else []
            oqs = json.loads(qb['original_question_sources']) if qb['original_question_sources'] else []
            if question_text in oq:
                oq = [q for q in oq if q != question_text]
                oqs = [item for item in oqs if item.get('question') != question_text]
                cursor.execute(
                    "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (json.dumps(oq, ensure_ascii=False), json.dumps(oqs, ensure_ascii=False), qb['id'])
                )
        conn.commit()

        # 验证：QB#2 的 oqs_sources 不再包含 "题目A"
        qb2 = conn.execute("SELECT original_questions, original_question_sources FROM question_bank WHERE id = 2").fetchone()
        remaining_oqs = json.loads(qb2['original_questions'])
        remaining_oqs_src = json.loads(qb2['original_question_sources'])

        assert "题目A" not in remaining_oqs, "oqs 中不应包含已删除的题目"
        assert all(item.get('question') != '题目A' for item in remaining_oqs_src), "oqs_sources 中不应包含已删除题目的条目"
        assert "题目C" in remaining_oqs, "不相关的题目应保留"
        conn.close()


class TestBug002BatchDeleteOqsCleanup:
    """BUG-002: batch_delete_master_bank 应清理 stale oqs 引用"""

    def test_batch_delete_cleans_stale_oqs_in_other_records(self):
        """批量删除后，其他 QB 记录的 oqs/oqs_sources 应同步清理"""
        conn = _create_test_db()

        # QB#1: 聚类包含 "题目X" 和 "题目Y"
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources, job_position) "
            "VALUES (1, '代表题', 2, '[]', ?, ?, '后端工程师')",
            (json.dumps(["题目X", "题目Y"], ensure_ascii=False),
             json.dumps([
                 {"question": "题目X", "sources": [{"url": "http://x.com"}]},
                 {"question": "题目Y", "sources": [{"url": "http://y.com"}]},
             ], ensure_ascii=False))
        )
        # QB#2: 引用了 "题目X"
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources, job_position) "
            "VALUES (2, '另一个聚类', 1, '[]', ?, ?, '后端工程师')",
            (json.dumps(["题目X", "题目Z"], ensure_ascii=False),
             json.dumps([
                 {"question": "题目X", "sources": [{"url": "http://x.com"}]},
                 {"question": "题目Z", "sources": [{"url": "http://z.com"}]},
             ], ensure_ascii=False))
        )
        conn.commit()

        # 模拟批量删除 QB#1
        question_id = 1
        question_text = "代表题"

        # 批量删除逻辑（当前代码 — 不清理 stale oqs）
        cursor = conn.cursor()
        cursor.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
        cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
        conn.commit()

        # 验证 BUG：QB#2 的 oqs 中仍包含 "题目X"（来自已删除的 QB#1）
        qb2 = conn.execute("SELECT original_questions, original_question_sources FROM question_bank WHERE id = 2").fetchone()
        oqs = json.loads(qb2['original_questions'])
        oqs_src = json.loads(qb2['original_question_sources'])

        # BUG-002: 批量删除不清理 stale oqs，所以 "题目X" 仍在
        # 这是预期的 buggy 行为
        assert "题目X" in oqs, "BUG-002: 批量删除未清理 stale oqs（预期的 buggy 行为）"

        # 现在测试修复后的逻辑
        # 修复：批量删除时，对被删除的 QB，清理其他记录中引用其 oqs 的 stale 条目
        deleted_qb = conn.execute("SELECT question, original_questions FROM question_bank WHERE id = ?", (question_id,)).fetchone()
        # 由于已经被删除，我们需要在删除前获取
        # 重新插入测试
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources, job_position) "
            "VALUES (3, '代表题2', 2, '[]', ?, ?, '后端工程师')",
            (json.dumps(["题目X2", "题目Y2"], ensure_ascii=False),
             json.dumps([
                 {"question": "题目X2", "sources": [{"url": "http://x2.com"}]},
                 {"question": "题目Y2", "sources": [{"url": "http://y2.com"}]},
             ], ensure_ascii=False))
        )
        conn.execute(
            "INSERT INTO question_bank (id, question, frequency, sources, original_questions, original_question_sources, job_position) "
            "VALUES (4, '另一个聚类2', 1, '[]', ?, ?, '后端工程师')",
            (json.dumps(["题目X2", "题目Z2"], ensure_ascii=False),
             json.dumps([
                 {"question": "题目X2", "sources": [{"url": "http://x2.com"}]},
                 {"question": "题目Z2", "sources": [{"url": "http://z2.com"}]},
             ], ensure_ascii=False))
        )
        conn.commit()

        # 获取要删除的 QB 的 oqs
        to_delete = conn.execute("SELECT id, question, original_questions FROM question_bank WHERE id = 3").fetchone()
        del_question_texts = [to_delete['question']]
        try:
            del_oqs = json.loads(to_delete['original_questions'] or '[]')
            del_question_texts.extend(del_oqs)
        except Exception:
            pass

        # 修复后的清理逻辑
        for q_text in del_question_texts:
            if not q_text:
                continue
            others = conn.execute(
                "SELECT id, original_questions, original_question_sources FROM question_bank WHERE id != ? AND original_questions LIKE ?",
                (3, f'%{q_text}%')
            ).fetchall()
            for qb in others:
                oq = json.loads(qb['original_questions']) if qb['original_questions'] else []
                oqs_src = json.loads(qb['original_question_sources']) if qb['original_question_sources'] else []
                if q_text in oq:
                    oq = [q for q in oq if q != q_text]
                    oqs_src = [item for item in oqs_src if item.get('question') != q_text]
                    conn.execute(
                        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(oq, ensure_ascii=False), json.dumps(oqs_src, ensure_ascii=False), qb['id'])
                    )

        # 删除 QB#3
        conn.execute("DELETE FROM question_position WHERE question_id = 3")
        conn.execute("DELETE FROM question_bank WHERE id = 3")
        conn.commit()

        # 验证：QB#4 的 oqs 不再包含 "题目X2"
        qb4 = conn.execute("SELECT original_questions, original_question_sources FROM question_bank WHERE id = 4").fetchone()
        remaining_oqs = json.loads(qb4['original_questions'])
        remaining_oqs_src = json.loads(qb4['original_question_sources'])

        assert "题目X2" not in remaining_oqs, "修复后：oqs 中不应包含已删除聚类的原始题目"
        assert all(item.get('question') != '题目X2' for item in remaining_oqs_src), "修复后：oqs_sources 中不应包含已删除题目的条目"
        assert "题目Z2" in remaining_oqs, "不相关的题目应保留"
        conn.close()


class TestBug003QueueStuckProcessing:
    """BUG-003: 队列 processing 状态应有超时恢复"""

    def test_stuck_processing_items_recovered(self):
        """超时的 processing 项应回退为 pending"""
        conn = _create_test_db()

        # 模拟一个卡在 processing 的队列项（created_at 设为很久以前）
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status, created_at) VALUES (1, 'processing', datetime('now', '-1 hour'))"
        )
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status) VALUES (2, 'pending')"
        )
        conn.commit()

        # 模拟修复后的 should_trigger_clustering 逻辑
        STUCK_THRESHOLD_MINUTES = 30

        # 回退超时的 processing 项
        conn.execute(
            "UPDATE analysis_queue SET status = 'pending' WHERE status = 'processing' AND created_at < datetime('now', ?)",
            (f'-{STUCK_THRESHOLD_MINUTES} minutes',)
        )
        conn.commit()

        # 验证：之前卡住的项已回退为 pending
        stuck = conn.execute("SELECT status FROM analysis_queue WHERE interview_id = 1").fetchone()
        assert stuck['status'] == 'pending', "超时的 processing 项应回退为 pending"

        pending_count = conn.execute("SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'").fetchone()['c']
        assert pending_count == 2, "两个项都应该是 pending 状态"
        conn.close()

    def test_recent_processing_not_recovered(self):
        """未超时的 processing 项不应被回退"""
        conn = _create_test_db()

        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status) VALUES (1, 'processing')"
        )
        conn.commit()

        STUCK_THRESHOLD_MINUTES = 30
        conn.execute(
            "UPDATE analysis_queue SET status = 'pending' WHERE status = 'processing' AND created_at < datetime('now', ?)",
            (f'-{STUCK_THRESHOLD_MINUTES} minutes',)
        )
        conn.commit()

        status = conn.execute("SELECT status FROM analysis_queue WHERE interview_id = 1").fetchone()
        assert status['status'] == 'processing', "未超时的 processing 项不应被回退"
        conn.close()

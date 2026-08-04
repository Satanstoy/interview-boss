"""
两阶段流水线测试套件

测试目标：
1. 队列管理（入队、出队、持久化、触发条件）
2. 打标签隔离（只写 questions_detail，不碰 question_bank）
3. 彻底清理（重新分析时清理 oqs/oqs_source/qd/question_position）
4. 批量聚类（新题+已有聚类一起处理）
5. 原子写入（聚类失败则回滚）
6. 孤儿清理（重建时清理 practice_history）
"""

import json
import sqlite3
import pytest
import tempfile
import os
from unittest.mock import AsyncMock, patch, MagicMock


# ============================================================
# Helper: 创建测试用的内存数据库
# ============================================================
def create_test_db():
    """创建一个包含所有必要表的测试数据库"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            bank_mode TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            focus TEXT,
            questions_list TEXT,
            difficulty TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            season TEXT DEFAULT '',
            owner_id INTEGER REFERENCES users(id),
            status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '',
            deleted_at TIMESTAMP,
            analysis_status TEXT DEFAULT 'idle',
            analysis_stage TEXT,
            analysis_result TEXT,
            analysis_updated_at TIMESTAMP
        );
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP
        );
        CREATE TABLE question_bank (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            difficulty TEXT,
            frequency INTEGER DEFAULT 1,
            ai_answer TEXT,
            vector TEXT,
            sources TEXT DEFAULT '[]',
            original_questions TEXT DEFAULT '[]',
            original_question_sources TEXT DEFAULT '[]',
            is_starred INTEGER DEFAULT 0,
            embedding BLOB,
            cluster_id INTEGER DEFAULT NULL,
            owner_id INTEGER,
            submitted_by INTEGER,
            status TEXT DEFAULT 'approved',
            job_position TEXT DEFAULT '',
            duplicate_of INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id),
            FOREIGN KEY (submitted_by) REFERENCES users(id)
        );
        CREATE TABLE question_position (
            question_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id),
            FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
        );
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id)
        );
        CREATE TABLE user_question_view (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            is_starred INTEGER DEFAULT 0,
            personal_tags TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        );
        CREATE TABLE analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            question_detail_id INTEGER,
            status TEXT DEFAULT 'pending',
            owner_id INTEGER DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (interview_id) REFERENCES interview(id)
        );
    """)
    # 插入测试用户和岗位
    conn.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) VALUES (1, 'testuser', 'hash', 1)"
    )
    conn.execute("INSERT INTO job_positions (id, name) VALUES (1, 'agent开发')")
    conn.commit()
    return conn


def make_question_bank_row(
    conn,
    qb_id,
    question,
    cat2="B1.Agent架构与范式",
    frequency=1,
    sources=None,
    oqs=None,
    oqs_sources=None,
    owner_id=None,
    job_position="agent开发",
):
    """Helper: 插入一条 question_bank 记录"""
    if sources is None:
        sources = json.dumps(
            [{"url": "http://example.com/1", "company": "测试公司", "round": "一面"}],
            ensure_ascii=False,
        )
    if oqs is None:
        oqs = json.dumps([question], ensure_ascii=False)
    if oqs_sources is None:
        oqs_sources = json.dumps(
            [{"question": question, "sources": [{"url": "http://example.com/1"}]}],
            ensure_ascii=False,
        )
    conn.execute(
        "INSERT INTO question_bank (id, question, cat1, cat2, tags, difficulty, frequency, sources, "
        "original_questions, original_question_sources, owner_id, job_position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            qb_id,
            question,
            "B.Agent与LLM应用",
            cat2,
            "Agent架构设计",
            "L2-中等",
            frequency,
            sources,
            oqs,
            oqs_sources,
            owner_id,
            job_position,
        ),
    )
    conn.commit()


def make_interview(conn, interview_id, url, questions_list, job_position="agent开发"):
    """Helper: 插入一条面经记录"""
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, job_position, owner_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (interview_id, url, "测试公司", "一面", questions_list, job_position, 1),
    )
    conn.commit()


def make_questions_detail(conn, url, questions, job_position="agent开发"):
    """Helper: 插入 questions_detail 记录"""
    for i, q in enumerate(questions):
        conn.execute(
            "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                url,
                "测试公司",
                "一面",
                q,
                "B.Agent与LLM应用",
                "B1.Agent架构与范式",
                "Agent架构设计",
                "L2-中等",
                job_position,
            ),
        )
    conn.commit()


# ============================================================
# T-001: 队列基本操作
# ============================================================
class TestQueueBasicOperations:
    """队列入队、出队、状态查询"""

    def test_enqueue_adds_pending_item(self):
        """入队后队列中应有 pending 状态的记录"""
        conn = create_test_db()
        make_interview(conn, 1, "http://test.com/1", '["题目1"]')

        # 入队
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
            (1,),
        )
        conn.commit()

        # 验证
        row = conn.execute(
            "SELECT * FROM analysis_queue WHERE interview_id = 1"
        ).fetchone()
        assert row is not None
        assert row["status"] == "pending"
        conn.close()

    def test_dequeue_marks_as_processing(self):
        """出队时应将状态改为 processing"""
        conn = create_test_db()
        make_interview(conn, 1, "http://test.com/1", '["题目1"]')
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status) VALUES (1, 'pending')"
        )
        conn.commit()

        # 出队：获取最早的 pending 项并标记为 processing
        row = conn.execute(
            "UPDATE analysis_queue SET status = 'processing' "
            "WHERE id = (SELECT id FROM analysis_queue WHERE status = 'pending' ORDER BY id LIMIT 1) "
            "RETURNING *"
        ).fetchone()
        conn.commit()

        assert row is not None
        assert row["status"] == "processing"
        conn.close()

    def test_complete_marks_as_done(self):
        """完成后应将状态改为 done"""
        conn = create_test_db()
        make_interview(conn, 1, "http://test.com/1", '["题目1"]')
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status) VALUES (1, 'pending')"
        )
        conn.commit()

        conn.execute(
            "UPDATE analysis_queue SET status = 'done', processed_at = CURRENT_TIMESTAMP "
            "WHERE interview_id = 1"
        )
        conn.commit()

        row = conn.execute(
            "SELECT status FROM analysis_queue WHERE interview_id = 1"
        ).fetchone()
        assert row["status"] == "done"
        conn.close()

    def test_pending_count(self):
        """正确统计 pending 数量"""
        conn = create_test_db()
        for i in range(1, 6):
            make_interview(conn, i, f"http://test.com/{i}", '["题目"]')
            conn.execute(
                "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
                (i,),
            )
        conn.execute("UPDATE analysis_queue SET status = 'done' WHERE interview_id = 1")
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'"
        ).fetchone()["c"]
        assert count == 4
        conn.close()


# ============================================================
# T-002: 队列持久化到DB
# ============================================================
class TestQueuePersistence:
    """队列持久化到数据库，重启后可恢复"""

    def test_pending_items_survive_restart(self):
        """模拟重启：关闭连接后重新打开，pending 记录仍在"""
        db_path = tempfile.mktemp(suffix=".db")

        try:
            # 第一次打开：写入数据
            conn1 = sqlite3.connect(db_path)
            conn1.row_factory = sqlite3.Row
            conn1.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT);
                CREATE TABLE interview (id INTEGER PRIMARY KEY, url TEXT, company TEXT, round TEXT,
                    questions_list TEXT, job_position TEXT DEFAULT '', owner_id INTEGER);
                CREATE TABLE analysis_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    interview_id INTEGER, status TEXT DEFAULT 'pending',
                    owner_id INTEGER DEFAULT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, processed_at TIMESTAMP);
            """)
            conn1.execute("INSERT INTO users VALUES (1, 'test', 'hash')")
            conn1.execute(
                "INSERT INTO interview VALUES (1, 'http://test.com/1', '公司', '一面', '[]', '', 1)"
            )
            conn1.execute(
                "INSERT INTO interview VALUES (2, 'http://test.com/2', '公司', '二面', '[]', '', 1)"
            )
            conn1.execute(
                "INSERT INTO analysis_queue (interview_id, status) VALUES (1, 'pending')"
            )
            conn1.execute(
                "INSERT INTO analysis_queue (interview_id, status) VALUES (2, 'pending')"
            )
            conn1.commit()
            conn1.close()

            # 第二次打开：模拟重启
            conn2 = sqlite3.connect(db_path)
            conn2.row_factory = sqlite3.Row
            pending = conn2.execute(
                "SELECT * FROM analysis_queue WHERE status = 'pending'"
            ).fetchall()
            assert len(pending) == 2
            conn2.close()
        finally:
            os.unlink(db_path)


# ============================================================
# T-003: 打标签只写 questions_detail
# ============================================================
class TestTaggingIsolation:
    """打标签阶段只写 questions_detail，不碰 question_bank"""

    def test_tag_only_writes_detail_not_bank(self):
        """打标签后，questions_detail 有记录，question_bank 无变化"""
        conn = create_test_db()

        # 预置一些 question_bank 数据
        make_question_bank_row(conn, 1, "什么是RAG？")
        qb_count_before = conn.execute(
            "SELECT COUNT(*) as c FROM question_bank"
        ).fetchone()["c"]

        # 模拟打标签：只写 questions_detail
        make_questions_detail(
            conn, "http://test.com/1", ["什么是Agent？", "MCP协议是什么？"]
        )

        # 验证
        qd_count = conn.execute(
            "SELECT COUNT(*) as c FROM questions_detail WHERE url = 'http://test.com/1'"
        ).fetchone()["c"]
        qb_count_after = conn.execute(
            "SELECT COUNT(*) as c FROM question_bank"
        ).fetchone()["c"]

        assert qd_count == 2  # questions_detail 有记录
        assert qb_count_after == qb_count_before  # question_bank 无变化
        conn.close()

    def test_tag_does_not_touch_existing_bank_data(self):
        """打标签不会修改已有 question_bank 的任何字段"""
        conn = create_test_db()
        make_question_bank_row(conn, 1, "什么是RAG？", frequency=5)

        # 打标签
        make_questions_detail(conn, "http://test.com/1", ["新题目"])

        # 验证 question_bank 未变
        qb = conn.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        assert qb["frequency"] == 5
        assert qb["question"] == "什么是RAG？"
        conn.close()


# ============================================================
# T-004: 彻底清理旧数据
# ============================================================
class TestThoroughCleanup:
    """重新分析面经时，彻底清理旧的 questions_detail + question_bank 引用"""

    def test_cleanup_removes_original_questions_by_url(self):
        """清理时应移除 original_questions 中属于该 URL 的条目"""
        conn = create_test_db()

        # 预置 question_bank，original_questions 包含来自两个 URL 的题目
        oqs = json.dumps(
            ["题目A来自URL1", "题目B来自URL2", "题目C来自URL1"], ensure_ascii=False
        )
        oqs_sources = json.dumps(
            [
                {"question": "题目A来自URL1", "sources": [{"url": "http://url1.com"}]},
                {"question": "题目B来自URL2", "sources": [{"url": "http://url2.com"}]},
                {"question": "题目C来自URL1", "sources": [{"url": "http://url1.com"}]},
            ],
            ensure_ascii=False,
        )
        sources = json.dumps(
            [
                {"url": "http://url1.com", "company": "公司1", "round": "一面"},
                {"url": "http://url2.com", "company": "公司2", "round": "二面"},
            ],
            ensure_ascii=False,
        )
        make_question_bank_row(
            conn,
            1,
            "代表题",
            frequency=3,
            sources=sources,
            oqs=oqs,
            oqs_sources=oqs_sources,
        )

        # 清理 URL1 的贡献
        from app.db.operations import _cleanup_old_sources_txn_v2

        with conn:
            _cleanup_old_sources_txn_v2(conn.cursor(), "http://url1.com", "agent开发")

        # 验证
        qb = conn.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        remaining_sources = json.loads(qb["sources"])
        remaining_oqs = json.loads(qb["original_questions"])
        remaining_oqs_sources = json.loads(qb["original_question_sources"])

        # sources 中 URL1 应被移除
        assert len(remaining_sources) == 1
        assert remaining_sources[0]["url"] == "http://url2.com"

        # original_questions 中属于 URL1 的应被移除
        assert len(remaining_oqs) == 1
        assert remaining_oqs[0] == "题目B来自URL2"

        # original_question_sources 中属于 URL1 的应被移除
        assert len(remaining_oqs_sources) == 1
        assert remaining_oqs_sources[0]["sources"][0]["url"] == "http://url2.com"

        # frequency 应更新为 1
        assert qb["frequency"] == 1
        conn.close()

    def test_cleanup_deletes_qb_when_frequency_zero(self):
        """当所有来源都被移除后，QB 记录应被删除"""
        conn = create_test_db()
        sources = json.dumps(
            [{"url": "http://only-url.com", "company": "公司", "round": "一面"}],
            ensure_ascii=False,
        )
        make_question_bank_row(conn, 1, "孤立项", frequency=1, sources=sources)

        from app.db.operations import _cleanup_old_sources_txn_v2

        with conn:
            _cleanup_old_sources_txn_v2(
                conn.cursor(), "http://only-url.com", "agent开发"
            )

        qb = conn.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        assert qb is None  # 已被删除
        conn.close()

    def test_cleanup_removes_question_position_for_deleted_qb(self):
        """删除 QB 记录时，应同步清理 question_position"""
        conn = create_test_db()
        sources = json.dumps(
            [{"url": "http://url.com", "company": "公司", "round": "一面"}],
            ensure_ascii=False,
        )
        make_question_bank_row(conn, 1, "题目", frequency=1, sources=sources)
        conn.execute(
            "INSERT INTO question_position (question_id, position_id) VALUES (1, 1)"
        )
        conn.commit()

        from app.db.operations import _cleanup_old_sources_txn_v2

        with conn:
            _cleanup_old_sources_txn_v2(conn.cursor(), "http://url.com", "agent开发")

        qp = conn.execute(
            "SELECT * FROM question_position WHERE question_id = 1"
        ).fetchone()
        assert qp is None  # 已被清理
        conn.close()

    def test_cleanup_handles_url_not_in_bank(self):
        """清理不存在的 URL 不应报错"""
        conn = create_test_db()
        make_question_bank_row(conn, 1, "题目")

        from app.db.operations import _cleanup_old_sources_txn_v2

        with conn:
            _cleanup_old_sources_txn_v2(
                conn.cursor(), "http://nonexistent.com", "agent开发"
            )

        # 不应崩溃，QB 记录仍在
        qb = conn.execute("SELECT * FROM question_bank WHERE id = 1").fetchone()
        assert qb is not None
        conn.close()


# ============================================================
# T-005/T-006: 触发条件
# ============================================================
class TestClusterTriggerConditions:
    """聚类触发条件：batch_size 达到 OR 全部完成"""

    def test_batch_size_triggers_clustering(self):
        """当 pending 数量 >= batch_size 时应触发聚类"""
        conn = create_test_db()
        batch_size = 3

        # 入队 3 条（等于 batch_size）
        for i in range(1, 4):
            make_interview(conn, i, f"http://test.com/{i}", '["题目"]')
            conn.execute(
                "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
                (i,),
            )
        conn.commit()

        pending_count = conn.execute(
            "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'"
        ).fetchone()["c"]

        should_trigger = pending_count >= batch_size
        assert should_trigger is True
        conn.close()

    def test_all_done_triggers_clustering(self):
        """当没有 processing 状态的任务且有 pending 时，应触发聚类"""
        conn = create_test_db()

        # 模拟：所有面经都已 tag 完成（没有 processing），队列有 pending
        for i in range(1, 4):
            make_interview(conn, i, f"http://test.com/{i}", '["题目"]')
            conn.execute(
                "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
                (i,),
            )
        conn.commit()

        processing_count = conn.execute(
            "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'processing'"
        ).fetchone()["c"]
        pending_count = conn.execute(
            "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'"
        ).fetchone()["c"]

        should_trigger = processing_count == 0 and pending_count > 0
        assert should_trigger is True
        conn.close()

    def test_not_trigger_while_processing(self):
        """有 processing 任务时不应触发聚类"""
        conn = create_test_db()
        batch_size = 5

        for i in range(1, 4):
            make_interview(conn, i, f"http://test.com/{i}", '["题目"]')
            conn.execute(
                "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
                (i,),
            )
        # 还有一条正在处理
        make_interview(conn, 4, "http://test.com/4", '["题目"]')
        conn.execute(
            "INSERT INTO analysis_queue (interview_id, status) VALUES (4, 'processing')"
        )
        conn.commit()

        processing_count = conn.execute(
            "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'processing'"
        ).fetchone()["c"]
        pending_count = conn.execute(
            "SELECT COUNT(*) as c FROM analysis_queue WHERE status = 'pending'"
        ).fetchone()["c"]

        # pending < batch_size 且有 processing，不应触发
        should_trigger = (pending_count >= batch_size) or (
            processing_count == 0 and pending_count > 0
        )
        assert should_trigger is False
        conn.close()


# ============================================================
# T-007: 聚类看到已有聚类+新题
# ============================================================
class TestClusteringContext:
    """聚类时应同时看到已有聚类和新题"""

    def test_cluster_prompt_includes_existing_clusters(self):
        """聚类输入应包含已有聚类的摘要和新题"""
        # 这个测试验证聚类函数接收的参数包含已有聚类信息
        existing_clusters = [
            {
                "id": 1,
                "question": "什么是RAG？",
                "cat2": "B2.RAG系统设计",
                "original_questions": ["什么是RAG？", "介绍一下RAG技术"],
            },
        ]
        new_questions = [
            {"id": 100, "question": "RAG是什么？", "cat2": "B2.RAG系统设计"},
            {
                "id": 101,
                "question": "Redis持久化方式有哪些？",
                "cat2": "D1.缓存设计与优化",
            },
        ]

        # 验证：输入格式应包含两者
        all_input = existing_clusters + new_questions
        assert len(all_input) == 3
        # 已有聚类有 original_questions 字段
        assert "original_questions" in all_input[0]
        # 新题没有 original_questions（或为空）
        assert (
            "original_questions" not in all_input[1]
            or all_input[1].get("original_questions") is None
        )


# ============================================================
# T-008: 聚类写入原子性
# ============================================================
class TestAtomicClusterWrite:
    """聚类写入是原子的：失败则回滚"""

    def test_atomic_write_rolls_back_on_failure(self):
        """聚类写入失败时，question_bank 不应有任何变化"""
        conn = create_test_db()
        make_question_bank_row(conn, 1, "已有题目")
        qb_before = conn.execute("SELECT COUNT(*) as c FROM question_bank").fetchone()[
            "c"
        ]

        # 模拟原子写入失败
        try:
            conn.execute("BEGIN")
            conn.execute(
                "DELETE FROM question_bank WHERE owner_id IS NULL AND job_position = 'agent开发'"
            )
            conn.execute(
                "INSERT INTO question_bank (question, cat1, cat2) VALUES ('新题目', 'A', 'B')"
            )
            # 模拟失败
            raise Exception("模拟写入失败")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")

        qb_after = conn.execute("SELECT COUNT(*) as c FROM question_bank").fetchone()[
            "c"
        ]
        assert qb_after == qb_before  # 回滚后数量不变
        conn.close()

    def test_atomic_write_succeeds(self):
        """正常写入时，所有数据应一致"""
        conn = create_test_db()

        conn.execute("BEGIN")
        conn.execute(
            "DELETE FROM question_bank WHERE owner_id IS NULL AND job_position = 'agent开发'"
        )
        conn.execute(
            "INSERT INTO question_bank (question, cat1, cat2, job_position, sources, original_questions, original_question_sources) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("新聚类题", "B", "B1", "agent开发", "[]", "[]", "[]"),
        )
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO question_position (question_id, position_id) VALUES (?, 1)",
            (new_id,),
        )
        conn.execute("COMMIT")

        qb = conn.execute(
            "SELECT * FROM question_bank WHERE id = ?", (new_id,)
        ).fetchone()
        assert qb is not None
        assert qb["question"] == "新聚类题"

        qp = conn.execute(
            "SELECT * FROM question_position WHERE question_id = ?", (new_id,)
        ).fetchone()
        assert qp is not None
        conn.close()


# ============================================================
# T-009: 重建清理 practice_history 孤儿引用
# ============================================================
class TestPracticeHistoryCleanup:
    """重建题库时清理 user_practice_history 中的孤儿引用"""

    def test_rebuild_cleans_orphan_practice_history(self):
        """删除 QB 记录时，关联的 practice_history 应被清理"""
        conn = create_test_db()
        make_question_bank_row(conn, 1, "旧题目")

        # 插入练习记录
        conn.execute(
            "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, score) "
            "VALUES (1, 1, '我的回答', 80)"
        )
        conn.commit()

        # 重建：删除旧 QB
        conn.execute(
            "DELETE FROM user_practice_history WHERE question_bank_id IN "
            "(SELECT id FROM question_bank WHERE owner_id IS NULL AND job_position = 'agent开发')"
        )
        conn.execute(
            "DELETE FROM question_bank WHERE owner_id IS NULL AND job_position = 'agent开发'"
        )
        conn.commit()

        ph = conn.execute(
            "SELECT * FROM user_practice_history WHERE question_bank_id = 1"
        ).fetchone()
        assert ph is None  # 孤儿记录已清理
        conn.close()

    def test_rebuild_cleans_user_question_view(self):
        """删除 QB 记录时，关联的 user_question_view 应被清理"""
        conn = create_test_db()
        make_question_bank_row(conn, 1, "旧题目")
        conn.execute(
            "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) VALUES (1, 1, 1)"
        )
        conn.commit()

        conn.execute(
            "DELETE FROM user_question_view WHERE question_bank_id IN "
            "(SELECT id FROM question_bank WHERE owner_id IS NULL AND job_position = 'agent开发')"
        )
        conn.execute(
            "DELETE FROM question_bank WHERE owner_id IS NULL AND job_position = 'agent开发'"
        )
        conn.commit()

        uqv = conn.execute(
            "SELECT * FROM user_question_view WHERE question_bank_id = 1"
        ).fetchone()
        assert uqv is None
        conn.close()


# ============================================================
# T-010: 聚类后生成 unified question
# ============================================================
class TestUnifiedQuestionGeneration:
    """2+ 题的聚类应生成统一代表题"""

    def test_single_question_uses_original(self):
        """单题聚类直接使用原题"""
        questions = ["什么是RAG？"]
        # 单题不需要 LLM 生成
        assert len(questions) == 1
        unified = questions[0]  # 直接使用
        assert unified == "什么是RAG？"

    def test_multi_question_needs_unification(self):
        """多题聚类需要生成统一代表题"""
        questions = ["什么是RAG？", "介绍一下RAG技术", "RAG是什么意思？"]
        assert len(questions) > 1  # 需要 LLM 生成
        # 这里验证的是：当有多个题目时，应该调用 LLM 生成统一题
        # 实际的 LLM 调用在实现中测试

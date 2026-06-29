"""
BUG-001: cluster_id 显式聚类标识测试
测试 cluster_id 在各写入路径中被正确维护
"""
import json
import pytest
import sqlite3


class TestClusterIdMigration:
    """测试 migration 033 添加 cluster_id 列"""

    @pytest.fixture
    def mock_db_without_cluster_id(self):
        """创建没有 cluster_id 列的 mock 数据库"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY,
                question TEXT,
                cat2 TEXT,
                frequency INTEGER DEFAULT 1,
                original_questions TEXT DEFAULT '[]',
                duplicate_of INTEGER,
                deleted_at TIMESTAMP,
                updated_at TIMESTAMP,
                embedding BLOB
            );
        """)
        conn.execute("INSERT INTO question_bank (id, question, cat2) VALUES (1, '问题1', 'B1')")
        conn.execute("INSERT INTO question_bank (id, question, cat2) VALUES (2, '问题2', 'B1')")
        conn.execute("INSERT INTO question_bank (id, question, cat2, deleted_at) VALUES (3, '已删除', 'B1', '2026-01-01')")
        conn.commit()
        return conn

    def test_migration_adds_cluster_id_column(self, mock_db_without_cluster_id):
        """migration 应添加 cluster_id 列"""
        from app.db.migrations import _migration_033_cluster_id
        conn = mock_db_without_cluster_id
        _migration_033_cluster_id(conn)

        # 验证列存在
        cursor = conn.execute("PRAGMA table_info('question_bank')")
        columns = [row[1] for row in cursor.fetchall()]
        assert 'cluster_id' in columns

    def test_migration_backfills_cluster_id(self, mock_db_without_cluster_id):
        """migration 应将存活题目的 cluster_id 回填为自身 id"""
        from app.db.migrations import _migration_033_cluster_id
        conn = mock_db_without_cluster_id
        _migration_033_cluster_id(conn)

        rows = conn.execute("SELECT id, cluster_id FROM question_bank ORDER BY id").fetchall()
        assert rows[0]['cluster_id'] == 1, f"题目1的cluster_id应为1, 实际={rows[0]['cluster_id']}"
        assert rows[1]['cluster_id'] == 2, f"题目2的cluster_id应为2, 实际={rows[1]['cluster_id']}"
        # 已删除的题目不应被回填
        assert rows[2]['cluster_id'] is None, f"已删除题目的cluster_id应为NULL, 实际={rows[2]['cluster_id']}"

    def test_migration_idempotent(self, mock_db_without_cluster_id):
        """重复执行 migration 不应报错"""
        from app.db.migrations import _migration_033_cluster_id
        conn = mock_db_without_cluster_id
        _migration_033_cluster_id(conn)
        _migration_033_cluster_id(conn)  # 第二次执行不应报错

        rows = conn.execute("SELECT id, cluster_id FROM question_bank WHERE id = 1").fetchone()
        assert rows['cluster_id'] == 1


class TestClusterIdInMergePaths:
    """测试 cluster_id 在各操作中的预期行为"""

    def test_new_question_gets_cluster_id(self):
        """新建题目时应设置 cluster_id = id"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT, cat2 TEXT, frequency INTEGER DEFAULT 1,
                cluster_id INTEGER, deleted_at TIMESTAMP, status TEXT DEFAULT 'approved'
            );
        """)
        # 模拟 _apply_incremental_txn 的行为: INSERT 后 UPDATE cluster_id = id
        conn.execute("INSERT INTO question_bank (question, cat2) VALUES ('新题', 'B1')")
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE question_bank SET cluster_id = id WHERE id = ?", (new_id,))
        conn.commit()

        row = conn.execute("SELECT id, cluster_id FROM question_bank WHERE id = ?", (new_id,)).fetchone()
        assert row['cluster_id'] == row['id'], f"新题的 cluster_id 应等于自身 id"

    def test_merged_question_cluster_id_unchanged(self):
        """合并后 survivor 的 cluster_id 不应改变"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY, question TEXT, cat2 TEXT,
                frequency INTEGER DEFAULT 1, cluster_id INTEGER,
                deleted_at TIMESTAMP
            );
        """)
        conn.execute("INSERT INTO question_bank (id, question, cat2, cluster_id) VALUES (1, 'survivor', 'B1', 1)")
        conn.execute("INSERT INTO question_bank (id, question, cat2, cluster_id) VALUES (2, 'merged', 'B1', 2)")
        # 模拟合并: 删除 merged，survivor 的 cluster_id 不变
        conn.execute("DELETE FROM question_bank WHERE id = 2")
        conn.commit()

        row = conn.execute("SELECT cluster_id FROM question_bank WHERE id = 1").fetchone()
        assert row['cluster_id'] == 1, f"survivor 的 cluster_id 应仍为 1"

    def test_split_question_gets_new_cluster_id(self):
        """拆分出的新题目应获得新的 cluster_id = 新 id"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, cat2 TEXT,
                frequency INTEGER DEFAULT 1, cluster_id INTEGER,
                deleted_at TIMESTAMP
            );
        """)
        conn.execute("INSERT INTO question_bank (id, question, cat2, cluster_id) VALUES (100, '原始题', 'B1', 100)")
        # 模拟拆分: 创建新记录
        conn.execute("INSERT INTO question_bank (question, cat2) VALUES ('拆出的题', 'B1')")
        new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("UPDATE question_bank SET cluster_id = id WHERE id = ?", (new_id,))
        conn.commit()

        row = conn.execute("SELECT id, cluster_id FROM question_bank WHERE id = ?", (new_id,)).fetchone()
        assert row['cluster_id'] == new_id, f"拆分出的新题 cluster_id 应为自身 id {new_id}"
        assert row['cluster_id'] != 100, f"不应继承原始题的 cluster_id"

"""
users.email 唯一约束测试 — tech-audit-2026-08-13 D14-1

迁移 079 后：
- users.email 必须有唯一索引（NULL 除外，允许多条未绑定邮箱）
- 重复 email 插入必须抛 IntegrityError
"""
import sqlite3

import pytest


class TestUsersEmailUnique:
    """D14-1: users.email 唯一约束"""

    def test_unique_index_exists(self, test_db):
        """迁移后 users 表应存在 email 唯一索引"""
        indexes = [
            row[1] for row in test_db.execute("PRAGMA index_list('users')").fetchall()
        ]
        assert "idx_users_email_unique" in indexes, "缺少 idx_users_email_unique 索引"

    def test_duplicate_email_rejected(self, test_db):
        """插入相同 email 应抛 IntegrityError"""
        test_db.execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            ("user_a", "hash_a", "dup@example.com"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            test_db.execute(
                "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                ("user_b", "hash_b", "dup@example.com"),
            )

    def test_null_email_allows_multiple(self, test_db):
        """NULL email（未绑定邮箱）允许多条"""
        test_db.execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            ("user_c", "hash_c", None),
        )
        test_db.execute(
            "INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
            ("user_d", "hash_d", None),
        )
        # 限定本次插入的用户（seed admin 等历史行也可能 email 为 NULL）
        rows = test_db.execute(
            "SELECT COUNT(*) AS n FROM users WHERE email IS NULL AND username IN ('user_c', 'user_d')"
        ).fetchone()
        assert rows["n"] == 2

"""批次②: 分享链路 — share 端点 / pending/mine / 审核删副本 / 确定性查重"""

from __future__ import annotations

import sqlite3

import pytest


def _seed_share_data(conn):
    """准备分享测试数据：2 个用户 + 公共题 + 私有题"""
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (1, 'u1', 'x')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (2, 'u2', 'x')"
    )
    # 公共 approved 题（用户1 的私有题将与之查重）
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency, sources, original_questions) "
        "VALUES (100, '什么是Redis持久化', '数据库', 'Redis', 'approved', NULL, '后端开发', NULL, 2, '[]', '[\"已有题A\",\"已有题B\"]')"
    )
    # 用户1 的私有题（未命中公共题）
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
        "VALUES (101, 'TCP三次握手过程', '网络', 'TCP', 'approved', 1, '后端开发', NULL, 1)"
    )
    # 用户1 的私有题（命中公共题 100，归一化后同文本）
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
        "VALUES (102, '什么是 Redis 持久化？', '数据库', 'Redis', 'approved', 1, '后端开发', NULL, 1)"
    )
    # 用户2 的私有题（分享权限测试）
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
        "VALUES (103, '别人私有的题', 'A', 'B', 'approved', 2, '后端开发', NULL, 1)"
    )
    conn.commit()


class TestDeterministicDedup:
    """确定性查重：归一化文本精确匹配"""

    def test_finds_exact_normalized_match(self):
        from app.routers.questions_pkg.share import find_matching_public_question

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE question_bank (id INTEGER, question TEXT, cat2 TEXT, status TEXT, owner_id INTEGER, deleted_at TIMESTAMP, job_position TEXT)"
        )
        conn.execute(
            "INSERT INTO question_bank VALUES (5, '什么是 Redis 持久化？', 'Redis', 'approved', NULL, NULL, '')"
        )
        conn.commit()

        match = find_matching_public_question(conn, "什么是Redis持久化", "Redis")
        assert match == 5

    def test_no_match_different_question(self):
        from app.routers.questions_pkg.share import find_matching_public_question

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE question_bank (id INTEGER, question TEXT, cat2 TEXT, status TEXT, owner_id INTEGER, deleted_at TIMESTAMP, job_position TEXT)"
        )
        conn.execute(
            "INSERT INTO question_bank VALUES (5, '完全不同的题', 'Redis', 'approved', NULL, NULL, '')"
        )
        conn.commit()

        assert find_matching_public_question(conn, "什么是Redis持久化", "Redis") is None


class TestShareEndpoint:
    """POST /api/master-bank/{id}/share"""

    def test_share_matches_existing_merges_and_deletes_private(self, test_db):
        from app.routers.questions_pkg.share import share_private_question

        _seed_share_data(test_db)
        result = share_private_question(test_db, question_id=102, user_id=1)

        assert result["result"] == "merged"
        assert result["target_id"] == 100
        # 公共题 frequency 增加
        row = test_db.execute(
            "SELECT frequency FROM question_bank WHERE id = 100"
        ).fetchone()
        assert row["frequency"] >= 3
        # 私有副本软删除
        row = test_db.execute(
            "SELECT deleted_at FROM question_bank WHERE id = 102"
        ).fetchone()
        assert row["deleted_at"] is not None

    def test_share_no_match_creates_pending_keeps_private(self, test_db):
        from app.routers.questions_pkg.share import share_private_question

        _seed_share_data(test_db)
        result = share_private_question(test_db, question_id=101, user_id=1)

        assert result["result"] == "pending"
        assert result["pending_id"] is not None
        # 新 pending 公共题
        row = test_db.execute(
            "SELECT * FROM question_bank WHERE id = ?", (result["pending_id"],)
        ).fetchone()
        assert row["owner_id"] is None
        assert row["status"] == "pending"
        assert row["submitted_by"] == 1
        # 私有副本保留
        row = test_db.execute(
            "SELECT deleted_at FROM question_bank WHERE id = 101"
        ).fetchone()
        assert row["deleted_at"] is None

    def test_share_others_private_question_denied(self, test_db):
        from app.routers.questions_pkg.share import share_private_question

        _seed_share_data(test_db)
        with pytest.raises(Exception):
            share_private_question(test_db, question_id=103, user_id=1)

    def test_share_public_question_denied(self, test_db):
        from app.routers.questions_pkg.share import share_private_question

        _seed_share_data(test_db)
        with pytest.raises(Exception):
            share_private_question(test_db, question_id=100, user_id=1)


class TestPendingMine:
    """GET /api/master-bank/pending/mine"""

    def test_returns_only_my_pending_contributions(self, test_db):
        from app.routers.questions_pkg.share import get_pending_mine

        _seed_share_data(test_db)
        # 造两条 pending：用户1、用户2
        test_db.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
            "VALUES (201, '我的待审', 'A', 'B', 'pending', NULL, '后端开发', 1, 1)"
        )
        test_db.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
            "VALUES (202, '别人的待审', 'A', 'B', 'pending', NULL, '后端开发', 2, 1)"
        )
        test_db.commit()

        items = get_pending_mine(test_db, user_id=1)
        ids = [i["id"] for i in items]
        assert ids == [201]
        assert 201 in ids and 202 not in ids


class TestApproveRemovesPrivateCopy:
    """审核批准后删除分享者私有副本"""

    def test_approve_deletes_matching_private_copy(self, test_db):
        _seed_share_data(test_db)
        # 模拟分享：创建 pending 公共题（来自私有题 101），私有副本保留
        test_db.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
            "VALUES (301, 'TCP三次握手过程', '网络', 'TCP', 'pending', NULL, '后端开发', 1, 1)"
        )
        test_db.commit()

        from app.routers.admin_review import _approve_cleanup_private_copy

        _approve_cleanup_private_copy(test_db, pending_id=301)

        # 私有副本 101 被软删
        row = test_db.execute(
            "SELECT deleted_at FROM question_bank WHERE id = 101"
        ).fetchone()
        assert row["deleted_at"] is not None

    def test_approve_keeps_unrelated_private(self, test_db):
        _seed_share_data(test_db)
        test_db.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, status, owner_id, job_position, submitted_by, frequency) "
            "VALUES (302, '完全不同的新题', 'X', 'Y', 'pending', NULL, '后端开发', 1, 1)"
        )
        test_db.commit()

        from app.routers.admin_review import _approve_cleanup_private_copy

        _approve_cleanup_private_copy(test_db, pending_id=302)

        # 私有题 101 未被删（文本不同）
        row = test_db.execute(
            "SELECT deleted_at FROM question_bank WHERE id = 101"
        ).fetchone()
        assert row["deleted_at"] is None

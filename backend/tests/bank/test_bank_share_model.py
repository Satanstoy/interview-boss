"""批次①: 题库共享模型重构 — migration 051 + 统一过滤口径 + 权限矩阵"""

from __future__ import annotations

import sqlite3

import pytest


def _new_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class TestMigration051ShareDefault:
    def test_adds_share_default_column(self):
        conn = _new_conn()
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"
        )
        conn.commit()

        from app.db.migrations.auth import _migration_051_share_default

        _migration_051_share_default(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info('users')")}
        assert "share_default" in cols
        # 默认值必须是 'private'（安全优先）
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        assert "'private'" in (row["sql"] or "")

    def test_is_idempotent(self):
        conn = _new_conn()
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.commit()

        from app.db.migrations.auth import _migration_051_share_default

        _migration_051_share_default(conn)
        _migration_051_share_default(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info('users')")}
        assert "share_default" in cols

    def test_existing_rows_default_to_private(self):
        conn = _new_conn()
        conn.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT)"
        )
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (1, 'a', 'x')"
        )
        conn.commit()

        from app.db.migrations.auth import _migration_051_share_default

        _migration_051_share_default(conn)

        row = conn.execute("SELECT share_default FROM users WHERE id = 1").fetchone()
        assert row["share_default"] == "private"

    def test_registered_after_050(self):
        from app.db.migrations import _MIGRATIONS

        versions = [v for v, _, _ in _MIGRATIONS]
        assert 51 in versions
        assert versions.index(51) == versions.index(50) + 1


class TestBuildBankWhereClause:
    """统一过滤口径 all/public/mine（新函数，替代 bank_mode 三分支）"""

    def _call(self, user_id, filter_mode, **kw):
        from app.db.queries import build_bank_where_clause

        return build_bank_where_clause(user_id, filter_mode, **kw)

    def test_public_filter_only_public_approved(self):
        with pytest.MonkeyPatch.context() as mp:
            from app.db import queries

            mp.setattr(queries, "get_user_job_position", lambda uid: (1, "后端"))
            _, where, params = self._call(1, "public")
            assert "owner_id IS NULL" in where
            assert "status = 'approved'" in where
            # from JOIN 参数（position_id）+ 无 where 参数
            assert params == [1]

    def test_mine_filter_includes_own_private_and_pending_contribution(self):
        with pytest.MonkeyPatch.context() as mp:
            from app.db import queries

            mp.setattr(queries, "get_user_job_position", lambda uid: (1, "后端"))
            _, where, params = self._call(7, "mine")
            # 自己的私有题
            assert "owner_id = ?" in where
            # 自己的待审核贡献（submitted_by）
            assert "submitted_by" in where
            assert "status = 'pending'" in where
            assert 7 in params

    def test_all_filter_includes_public_and_own_private(self):
        with pytest.MonkeyPatch.context() as mp:
            from app.db import queries

            mp.setattr(queries, "get_user_job_position", lambda uid: (1, "后端"))
            _, where, params = self._call(3, "all")
            assert "owner_id IS NULL" in where
            assert "status = 'approved'" in where
            assert "owner_id = ?" in where
            assert 3 in params
            # all 不包含别人的私有题（无其他 owner 条件）
            assert "duplicate_of" not in where

    def test_invalid_filter_raises(self):
        with pytest.raises(ValueError):
            self._call(1, "unknown")

    def test_table_alias_used(self):
        with pytest.MonkeyPatch.context() as mp:
            from app.db import queries

            mp.setattr(queries, "get_user_job_position", lambda uid: (1, "后端"))
            _, where, _ = self._call(1, "public", table_alias="b")
            assert "b.owner_id" in where


class TestQuestionPermission:
    """权限矩阵 helper：公共题仅 admin / 个人题仅本人"""

    def test_public_question_admin_allowed(self):
        from app.db.queries import can_edit_question

        assert can_edit_question(owner_id=None, user_id=1, is_admin=True) is True

    def test_public_question_normal_user_denied(self):
        from app.db.queries import can_edit_question

        assert can_edit_question(owner_id=None, user_id=1, is_admin=False) is False

    def test_own_private_question_allowed(self):
        from app.db.queries import can_edit_question

        assert can_edit_question(owner_id=5, user_id=5, is_admin=False) is True

    def test_others_private_question_denied_even_admin(self):
        from app.db.queries import can_edit_question

        # admin 也不能编辑他人私有题（数据所有权边界）
        assert can_edit_question(owner_id=5, user_id=1, is_admin=True) is False

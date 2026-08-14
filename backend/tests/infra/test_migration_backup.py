"""Tests for run_migrations safety: pre-destructive backup + FK toggle around table rebuilds.

Covers D9 findings: run_migrations had no backup logic despite CLAUDE.md claiming
"破坏性操作前自动备份"; destructive rebuilds must not fire ON DELETE CASCADE
while foreign_keys=ON (implicit DELETE of parent tables).
"""

from __future__ import annotations

import os
import sqlite3

import pytest


def _file_conn(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _memory_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class TestBackupBeforeDestructive:
    def test_backup_file_created_with_content(self, tmp_path, monkeypatch):
        """备份文件存在且包含源库数据（不破坏源数据）。"""
        db_path = tmp_path / "src.db"
        conn = _file_conn(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'keep')")
        conn.commit()
        conn.close()

        import app.db.migrations as mig

        backup_path = mig._backup_before_destructive(str(db_path), 81, "cleanup")

        assert backup_path is not None
        assert os.path.exists(backup_path)
        assert backup_path != str(db_path)
        b = _file_conn(backup_path)
        assert b.execute("SELECT v FROM t WHERE id=1").fetchone()["v"] == "keep"
        b.close()

    def test_backup_skipped_for_missing_db(self, tmp_path):
        """源库文件不存在时（全新部署）不报错、不生成备份。"""
        import app.db.migrations as mig

        backup_path = mig._backup_before_destructive(
            str(tmp_path / "nope.db"), 81, "cleanup"
        )
        assert backup_path is None

    def test_runner_backs_up_before_destructive_version(self, tmp_path, monkeypatch):
        """run_migrations 在 destructive 版本执行前生成备份文件。"""
        db_path = tmp_path / "app.db"
        conn = _file_conn(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'before')")
        conn.commit()

        import app.db.migrations as mig

        calls = []

        def _fake_migration(conn):
            calls.append(conn.execute("SELECT v FROM t").fetchone()["v"])
            conn.execute("UPDATE t SET v = 'after'")

        monkeypatch.setattr(mig, "_MIGRATIONS", [(1, "fake", _fake_migration)])
        monkeypatch.setattr(mig, "DESTRUCTIVE_VERSIONS", {1})
        monkeypatch.setattr(mig, "DB_PATH", str(db_path))

        mig.run_migrations(conn)

        assert calls == ["before"]
        backups = list((tmp_path / "backups").glob("pre_migration_v001_*.db"))
        assert len(backups) == 1
        b = _file_conn(str(backups[0]))
        assert b.execute("SELECT v FROM t").fetchone()["v"] == "before"
        b.close()
        conn.close()

    def test_runner_skips_backup_for_memory_db(self, monkeypatch):
        """内存库（测试环境）不触发对生产文件的备份。"""
        conn = _memory_conn()
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

        import app.db.migrations as mig

        def _fake_migration(conn):
            pass

        monkeypatch.setattr(mig, "_MIGRATIONS", [(1, "fake", _fake_migration)])
        monkeypatch.setattr(mig, "DESTRUCTIVE_VERSIONS", {1})

        # DB_PATH 指向不存在的路径；内存连接不应触发备份
        monkeypatch.setattr(mig, "DB_PATH", "/nonexistent/prod.db")
        mig.run_migrations(conn)
        conn.close()


class TestFKToggleAroundDestructive:
    def test_drop_parent_does_not_cascade_when_fk_on(self, tmp_path, monkeypatch):
        """destructive 迁移期间 foreign_keys 被临时关闭：DROP 父表不再级联清子表。"""
        db_path = tmp_path / "fk.db"
        conn = _file_conn(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        conn.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER "
            "REFERENCES parent(id) ON DELETE CASCADE)"
        )
        conn.execute("INSERT INTO parent VALUES (1)")
        conn.execute("INSERT INTO child VALUES (10, 1)")
        conn.commit()

        import app.db.migrations as mig

        def _destructive(conn):
            # 重建父表：DROP + RENAME（FK ON 时隐式 DELETE 会级联清空 child）
            conn.execute("CREATE TABLE parent_new (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO parent_new SELECT id FROM parent")
            conn.execute("DROP TABLE parent")
            conn.execute("ALTER TABLE parent_new RENAME TO parent")

        monkeypatch.setattr(mig, "_MIGRATIONS", [(1, "rebuild", _destructive)])
        monkeypatch.setattr(mig, "DESTRUCTIVE_VERSIONS", {1})
        monkeypatch.setattr(mig, "DB_PATH", str(db_path))

        mig.run_migrations(conn)

        assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 1
        # 迁移完成后 FK 恢复
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        conn.close()

    def test_fk_toggle_restores_previous_state(self, tmp_path, monkeypatch):
        """FK 原本关闭的连接，destructive 迁移后保持关闭。"""
        db_path = tmp_path / "fkoff.db"
        conn = _file_conn(str(db_path))
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.commit()

        import app.db.migrations as mig

        def _destructive(conn):
            pass

        monkeypatch.setattr(mig, "_MIGRATIONS", [(1, "rebuild", _destructive)])
        monkeypatch.setattr(mig, "DESTRUCTIVE_VERSIONS", {1})
        monkeypatch.setattr(mig, "DB_PATH", str(db_path))

        mig.run_migrations(conn)

        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        conn.close()

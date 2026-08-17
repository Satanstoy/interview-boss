"""Test FK CASCADE behavior for analysis_queue.interview_id."""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations


@pytest.fixture
def cascade_db():
    """内存库：全量迁移应用，FK 开启。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # 预建 migration 依赖的表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, company TEXT,
            season TEXT DEFAULT '', owner_id INTEGER, status TEXT DEFAULT 'approved',
            url_signature TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            job_position TEXT DEFAULT '', deleted_at TIMESTAMP, tech_stack TEXT,
            source TEXT DEFAULT '', position TEXT DEFAULT '', salary TEXT DEFAULT '',
            job_title TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT, interview_id INTEGER,
            question TEXT, cat1 TEXT, cat2 TEXT, tags TEXT, difficulty TEXT,
            diff_tag TEXT, answer TEXT, url TEXT, source TEXT DEFAULT '',
            owner_id INTEGER, status TEXT DEFAULT 'approved', deleted_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, company TEXT DEFAULT '',
            round TEXT DEFAULT '', job_position TEXT DEFAULT ''
        )
    """)
    conn.commit()

    run_migrations(conn)
    yield conn
    conn.close()


def _seed_user(conn, username="u1") -> int:
    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, 'hash')", (username,)
    )
    return cur.lastrowid


def test_analysis_queue_cascades_on_interview_delete(cascade_db):
    """删除 interview 后 analysis_queue 对应行自动清理。"""
    conn = cascade_db
    user_id = _seed_user(conn)
    cur = conn.execute(
        "INSERT INTO interview (owner_id, status) VALUES (?, 'approved')", (user_id,)
    )
    interview_id = cur.lastrowid
    conn.execute(
        "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
        (interview_id,),
    )
    conn.commit()

    # 验证数据存在
    count = conn.execute("SELECT COUNT(*) FROM analysis_queue").fetchone()[0]
    assert count == 1

    # 删除 interview
    conn.execute("DELETE FROM interview WHERE id = ?", (interview_id,))
    conn.commit()

    # 验证 analysis_queue 被级联删除
    count = conn.execute("SELECT COUNT(*) FROM analysis_queue").fetchone()[0]
    assert count == 0


def test_analysis_queue_no_cascade_without_fk_on(cascade_db):
    """FK 关闭时级联不生效（对照组）。"""
    conn = cascade_db
    conn.execute("PRAGMA foreign_keys=OFF")
    user_id = _seed_user(conn, "u2")
    cur = conn.execute(
        "INSERT INTO interview (owner_id, status) VALUES (?, 'approved')", (user_id,)
    )
    interview_id = cur.lastrowid
    conn.execute(
        "INSERT INTO analysis_queue (interview_id, status) VALUES (?, 'pending')",
        (interview_id,),
    )
    conn.commit()

    conn.execute("DELETE FROM interview WHERE id = ?", (interview_id,))
    conn.commit()

    # FK 关闭，行不会被清理
    count = conn.execute("SELECT COUNT(*) FROM analysis_queue").fetchone()[0]
    assert count == 1


def test_fk_declaration_present(cascade_db):
    """analysis_queue.interview_id 的 FK 声明包含 ON DELETE CASCADE。"""
    conn = cascade_db
    fk_list = conn.execute("PRAGMA foreign_key_list('analysis_queue')").fetchall()
    interview_fk = [fk for fk in fk_list if fk[2] == "interview"]
    assert len(interview_fk) >= 1, "缺少 interview FK 声明"
    # fk[0] = id, fk[1] = seq, fk[2] = table, fk[3] = from, fk[4] = to, fk[5] = on_update, fk[6] = on_delete
    assert interview_fk[0][6] == "CASCADE", (
        f"期望 ON DELETE CASCADE，实际为 {interview_fk[0][6]}"
    )

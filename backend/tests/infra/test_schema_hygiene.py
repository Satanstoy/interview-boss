"""Tests for schema hygiene migrations 081-086.

Fixture: 全量迁移链（1-80）在内存库构建当前 schema，再直接调用 081-086
（预置 schema_version 81-86 使 run_migrations 跳过它们）。
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

import pytest

from app.db.migrations import run_migrations
from app.db.migrations.schema_hygiene import (
    _migration_081_cleanup_fk_orphans,
    _migration_082_fts_rebuild_triggers,
    _migration_083_index_housekeeping,
    _migration_084_normalize_timestamps_jobs,
    _migration_085_add_fk_declarations,
    _migration_086_drop_dead_columns_indexes,
)


@pytest.fixture
def full_db():
    """内存库：迁移 1-80 全量应用（081-086 预置跳过），FK 开启。"""
    os.environ.setdefault("ADMIN_PASSWORD", "TEST_PASSWORD_PLACEHOLDER")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # 早期迁移依赖的预建表（与 conftest 一致）
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
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    for v in range(81, 87):
        conn.execute("INSERT INTO schema_version (version, name) VALUES (?, 'preseed')", (v,))
    conn.commit()
    run_migrations(conn)
    yield conn
    conn.close()


def _seed_user(conn, username="u1") -> int:
    cur = conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, 'hash')", (username,)
    )
    return cur.lastrowid


def _seed_question(conn, question="测试题") -> int:
    cur = conn.execute("INSERT INTO question_bank (question) VALUES (?)", (question,))
    return cur.lastrowid


def _fk_count(conn, table) -> int:
    return len(conn.execute(f"PRAGMA foreign_key_list('{table}')").fetchall())


def _apply(conn, *versions: int):
    """经 run_migrations 应用指定迁移（含备份/FK 切换安全机制，与生产路径一致）。"""
    for v in versions:
        conn.execute("DELETE FROM schema_version WHERE version = ?", (v,))
    conn.commit()
    run_migrations(conn)


@contextmanager
def _orphan_inserts(conn):
    """在事务外临时关闭 FK 以注入孤儿数据（PRAGMA 在事务内是 no-op）。"""
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        yield
    finally:
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")


# ── 081 ─────────────────────────────────────────────────────────────────────


class Test081CleanupFkOrphans:
    def test_removes_chat_and_asked_orphans_preserves_valid(self, full_db):
        uid = _seed_user(full_db)
        full_db.execute("INSERT INTO chat_conversations (id, user_id, mode) VALUES ('c1', ?, 'interview')", (uid,))
        qid = _seed_question(full_db)
        with _orphan_inserts(full_db):
            full_db.execute("INSERT INTO chat_messages (conversation_id, role, content) VALUES ('gone', 'user', 'orphan')")
            full_db.execute("INSERT INTO chat_messages (conversation_id, role, content) VALUES ('c1', 'assistant', 'valid')")
            full_db.execute("INSERT INTO interview_asked_questions (user_id, conversation_id, question_id) VALUES (?, 'gone', ?)", (uid, qid))
            full_db.execute("INSERT INTO interview_asked_questions (user_id, conversation_id, question_id) VALUES (?, 'c1', ?)", (uid, qid))

        _apply(full_db, 81)

        msgs = full_db.execute("SELECT content FROM chat_messages").fetchall()
        assert [m["content"] for m in msgs] == ["valid"]
        asked = full_db.execute("SELECT count(*) FROM interview_asked_questions").fetchone()[0]
        assert asked == 1
        assert full_db.execute("PRAGMA foreign_key_check").fetchall() == []

    def test_removes_bank_quality_analysis_orphans(self, full_db):
        qid = _seed_question(full_db)
        uid = _seed_user(full_db)
        full_db.execute("INSERT INTO interview (url) VALUES ('http://x')")
        iid = full_db.execute("SELECT id FROM interview").fetchone()["id"]
        with _orphan_inserts(full_db):
            full_db.execute("INSERT INTO question_sources (question_bank_id, url) VALUES (999999, 'http://orphan')")
            cur = full_db.execute("INSERT INTO question_original_items (question_bank_id, question_text) VALUES (999999, 'x')")
            oi_id = cur.lastrowid
            full_db.execute("INSERT INTO question_original_item_sources (original_item_id, url) VALUES (?, 'http://child')", (oi_id,))
            full_db.execute("INSERT INTO quality_issue (qb_id, issue_type, suggested_action) VALUES (999999, 'mismerge', 'split')")
            full_db.execute("INSERT INTO analysis_queue (interview_id, question_detail_id) VALUES (?, 999999)", (iid,))
            full_db.execute("INSERT INTO question_position (question_id, position_id) VALUES (999999, 1)")

        _apply(full_db, 81)

        assert full_db.execute("SELECT count(*) FROM question_sources").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM question_original_items").fetchone()[0] == 0
        # 迁移期 FK 关闭：孤儿 qoi 的子表 qois 必须被 081 手动清理
        assert full_db.execute("SELECT count(*) FROM question_original_item_sources").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM quality_issue").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM question_position").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM analysis_queue").fetchone()[0] == 0
        assert full_db.execute("PRAGMA foreign_key_check").fetchall() == []

    def test_no_orphans_is_noop(self, full_db):
        _apply(full_db, 81)
        assert full_db.execute("PRAGMA foreign_key_check").fetchall() == []


# ── 082 ─────────────────────────────────────────────────────────────────────


class Test082FtsRebuildAndTriggers:
    def test_rebuilds_fts_and_triggers_sync(self, full_db):
        qid = _seed_question(full_db, "FTS触发同步题")
        _apply(full_db, 82)
        row = full_db.execute("SELECT question FROM question_fts WHERE rowid = ?", (qid,)).fetchone()
        assert row and row["question"] == "FTS触发同步题"

        # INSERT 触发器
        cur = full_db.execute("INSERT INTO question_bank (question) VALUES ('新增题')")
        new_id = cur.lastrowid
        assert full_db.execute("SELECT question FROM question_fts WHERE rowid = ?", (new_id,)).fetchone()["question"] == "新增题"

        # UPDATE 触发器
        full_db.execute("UPDATE question_bank SET question = '改题后', cat2 = '算法' WHERE id = ?", (new_id,))
        row = full_db.execute("SELECT question, cat2 FROM question_fts WHERE rowid = ?", (new_id,)).fetchone()
        assert row["question"] == "改题后" and row["cat2"] == "算法"

        # DELETE 触发器
        full_db.execute("DELETE FROM question_bank WHERE id = ?", (new_id,))
        assert full_db.execute("SELECT count(*) FROM question_fts WHERE rowid = ?", (new_id,)).fetchone()[0] == 0

    def test_fts_row_count_matches_question_bank(self, full_db):
        _seed_question(full_db, "a")
        _seed_question(full_db, "b")
        _apply(full_db, 82)
        n_qb = full_db.execute("SELECT count(*) FROM question_bank").fetchone()[0]
        n_fts = full_db.execute("SELECT count(*) FROM question_fts").fetchone()[0]
        assert n_fts == n_qb


# ── 083 ─────────────────────────────────────────────────────────────────────


class Test083IndexHousekeeping:
    def test_drops_redundant_unique_indexes(self, full_db):
        assert full_db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='idx_practice_deck_key'").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='idx_uqr_user_question'").fetchone()[0] == 1
        _apply(full_db, 83)
        assert full_db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='idx_practice_deck_key'").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='idx_uqr_user_question'").fetchone()[0] == 0
        # 表级/列级 UNIQUE 自动索引仍在
        assert full_db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='sqlite_autoindex_practice_decks_1'").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM sqlite_master WHERE type='index' AND name='sqlite_autoindex_user_question_review_1'").fetchone()[0] == 1


# ── 084 ─────────────────────────────────────────────────────────────────────


class Test084NormalizeTimestampsJobs:
    def test_jobs_rebuilt_error_dropped_available_at_backfilled(self, full_db):
        full_db.execute("INSERT INTO jobs (job_type, status, available_at) VALUES ('import', 'completed', '')")
        full_db.execute("INSERT INTO jobs (job_type, status, available_at) VALUES ('import', 'pending', '2026-01-01 00:00:00')")
        _apply(full_db, 84)

        cols = {r[1] for r in full_db.execute("PRAGMA table_info('jobs')")}
        assert "error" not in cols
        assert "last_error" in cols
        rows = full_db.execute("SELECT status, available_at FROM jobs ORDER BY status").fetchall()
        by_status = {r["status"]: r["available_at"] for r in rows}
        assert by_status["completed"] != ""
        assert by_status["pending"] == "2026-01-01 00:00:00"
        # 新插入不带 available_at → 默认 CURRENT_TIMESTAMP（非空串）
        full_db.execute("INSERT INTO jobs (job_type) VALUES ('import')")
        latest = full_db.execute("SELECT available_at FROM jobs ORDER BY id DESC LIMIT 1").fetchone()["available_at"]
        assert latest and latest != ""

    def test_login_failures_epoch_converted_to_text(self, full_db):
        full_db.execute("INSERT INTO login_failures (username, failure_count, locked_until) VALUES ('locked', 5, 1750000000.0)")
        full_db.execute("INSERT INTO login_failures (username, failure_count, locked_until) VALUES ('free', 0, 0)")
        _apply(full_db, 84)

        assert "REAL" not in full_db.execute("PRAGMA table_info('login_failures')").fetchall()[0]
        typ = [r[2] for r in full_db.execute("PRAGMA table_info('login_failures')") if r[1] == "locked_until"][0]
        assert typ.upper() == "TEXT"
        locked = full_db.execute("SELECT locked_until FROM login_failures WHERE username='locked'").fetchone()["locked_until"]
        assert locked.startswith("2025-") and " " in locked  # datetime(unixepoch) 文本
        free = full_db.execute("SELECT locked_until FROM login_failures WHERE username='free'").fetchone()["locked_until"]
        assert free == ""

    def test_mcp_sessions_epoch_converted_to_text(self, full_db):
        # mcp_sessions 由 mcp_server/session.py 运行时懒建，测试先建旧结构
        full_db.execute(
            "CREATE TABLE IF NOT EXISTS mcp_sessions ("
            "session_id TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        full_db.execute("INSERT INTO mcp_sessions (session_id, data_json, updated_at) VALUES ('s1', '{}', 1750000000)")
        _apply(full_db, 84)
        typ = [r[2] for r in full_db.execute("PRAGMA table_info('mcp_sessions')") if r[1] == "updated_at"][0]
        assert typ.upper() == "TEXT"
        v = full_db.execute("SELECT updated_at FROM mcp_sessions WHERE session_id='s1'").fetchone()["updated_at"]
        assert v.startswith("2025-") and " " in v

    def test_mcp_sessions_iso_text_in_integer_column_preserved(self, full_db):
        """回归：旧结构 updated_at INTEGER NOT NULL 里已写入 ISO 文本（mcp_server/session
        曾在 INTEGER 列存 datetime 文本）——迁移 084 必须成功且原文本值不丢失、非 NULL。

        这是生产容器启动失败的根因场景：datetime(ISO文本, 'unixepoch') 返回 NULL
        会触发 NOT NULL constraint failed；必须等值保留原文本（不能用 NULL 覆盖）。
        """
        full_db.execute(
            "CREATE TABLE IF NOT EXISTS mcp_sessions ("
            "session_id TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        # 模拟历史遗留：INTEGER NOT NULL 列里实际存的是 ISO 文本
        iso_value = "2026-08-14 05:52:39"
        full_db.execute(
            "INSERT INTO mcp_sessions (session_id, data_json, updated_at) VALUES ('s_iso', '{}', ?)",
            (iso_value,),
        )
        # 混合：同一列再放一个真实 epoch 整数，验证两种格式同表共存都正常迁移
        full_db.execute(
            "INSERT INTO mcp_sessions (session_id, data_json, updated_at) VALUES ('s_epoch', '{}', 1750000000)"
        )
        _apply(full_db, 84)

        # 迁移成功：列类型变为 TEXT，schema_version 写入 84
        typ = [r[2] for r in full_db.execute("PRAGMA table_info('mcp_sessions')") if r[1] == "updated_at"][0]
        assert typ.upper() == "TEXT"
        assert full_db.execute("SELECT version FROM schema_version WHERE version=84").fetchone() is not None

        # ISO 文本值等值保留，不丢失、非 NULL
        iso_row = full_db.execute(
            "SELECT updated_at FROM mcp_sessions WHERE session_id='s_iso'"
        ).fetchone()
        assert iso_row is not None
        assert iso_row["updated_at"] == iso_value
        assert isinstance(iso_row["updated_at"], str)

        # 整数 epoch 场景仍正常转换成 ISO 文本（不被此修复破坏）
        epoch_row = full_db.execute(
            "SELECT updated_at FROM mcp_sessions WHERE session_id='s_epoch'"
        ).fetchone()
        assert epoch_row is not None
        assert epoch_row["updated_at"].startswith("2025-") and " " in epoch_row["updated_at"]

    def test_mcp_sessions_empty_and_null_updated_at_get_timestamp(self, full_db):
        """回归：旧结构 updated_at INTEGER NOT NULL 里出现空字符串 / NULL 值。

        空串既是合法 SQLite 值又满足 NOT NULL（数据库约束不拦），但若迁移把它当成
        合法时间原样保留，会留下语义无效的 ''。迁移须把 NULL/空串/纯空白统一回填为
        当前时间（datetime('now')），而不是保留空串。
        """
        full_db.execute(
            "CREATE TABLE IF NOT EXISTS mcp_sessions ("
            "session_id TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at INTEGER)"
        )
        # 历史遗留三类坏值：空串、纯空白、NULL（updated_at 声明 INTEGER 而非 NOT NULL，
        # 以便能插入 NULL——迁移 guard 只看声明类型 == INTEGER，仍会触发重建）
        full_db.execute("INSERT INTO mcp_sessions (session_id, data_json, updated_at) VALUES ('s_empty', '{}', '')")
        full_db.execute("INSERT INTO mcp_sessions (session_id, data_json, updated_at) VALUES ('s_blank', '{}', '   ')")
        full_db.execute("INSERT INTO mcp_sessions (session_id, data_json, updated_at) VALUES ('s_null', '{}', NULL)")
        _apply(full_db, 84)

        # 迁移成功 + updated_at 为 TEXT
        typ = [r[2] for r in full_db.execute("PRAGMA table_info('mcp_sessions')") if r[1] == "updated_at"][0]
        assert typ.upper() == "TEXT"

        # 每个坏值都被回填成真实 ISO 时间戳（非空、非纯空白、可被 SQLite 解析为时间）
        for sid in ("s_empty", "s_blank", "s_null"):
            row = full_db.execute(
                "SELECT updated_at FROM mcp_sessions WHERE session_id=?", (sid,)
            ).fetchone()
            assert row is not None
            v = row["updated_at"]
            assert isinstance(v, str) and v.strip() != ""
            assert " " in v  # 'YYYY-MM-DD HH:MM:SS'
            parsed = full_db.execute("SELECT datetime(?) IS NOT NULL", (v,)).fetchone()[0]
            assert parsed == 1, f"{sid} updated_at 不是合法 ISO 时间: {v!r}"

    def test_refresh_tokens_created_at_normalized_to_iso(self, full_db):
        uid = _seed_user(full_db)
        full_db.execute("INSERT INTO refresh_tokens (user_id, jti, expires_at) VALUES (?, 'j1', '2026-12-31T00:00:00+00:00')", (uid,))
        _apply(full_db, 84)
        v = full_db.execute("SELECT created_at FROM refresh_tokens WHERE jti='j1'").fetchone()["created_at"]
        assert "T" in v and v.endswith("+00:00")


# ── 085 ─────────────────────────────────────────────────────────────────────


class Test085FkDeclarations:
    def test_fks_declared_and_enforced(self, full_db):
        _apply(full_db, 85)
        assert _fk_count(full_db, "interview_asked_questions") == 3
        assert _fk_count(full_db, "chat_tool_traces") == 2
        assert _fk_count(full_db, "quality_issue") == 1
        assert _fk_count(full_db, "email_verification_codes") == 1
        assert _fk_count(full_db, "analysis_queue") == 3
        assert _fk_count(full_db, "chat_conversations") == 2
        assert _fk_count(full_db, "chat_memories") == 3
        assert _fk_count(full_db, "coding_problems") == 1
        assert _fk_count(full_db, "coding_submissions") == 3
        assert _fk_count(full_db, "users") == 1
        assert _fk_count(full_db, "practice_decks") == 1
        # 约束生效：无主会话的 asked_questions 插入必须失败
        with pytest.raises(sqlite3.IntegrityError):
            full_db.execute("INSERT INTO interview_asked_questions (user_id, conversation_id, question_id) VALUES (1, 'no-such-conv', 1)")
        full_db.rollback()

    def test_username_backfilled_lowercase(self, full_db):
        _seed_user(full_db, "MiXeDUser")
        _apply(full_db, 85)
        u = full_db.execute("SELECT username FROM users WHERE username='mixeduser'").fetchone()
        assert u is not None

    def test_rebuild_preserves_data(self, full_db):
        uid = _seed_user(full_db, "keepuser")
        full_db.execute("INSERT INTO chat_conversations (id, user_id, mode) VALUES ('c1', ?, 'interview')", (uid,))
        qid = _seed_question(full_db, "保持题")
        full_db.execute("INSERT INTO interview_asked_questions (user_id, conversation_id, question_id) VALUES (?, 'c1', ?)", (uid, qid))
        full_db.execute("INSERT INTO interview (url) VALUES ('http://keep')")
        iid = full_db.execute("SELECT id FROM interview").fetchone()["id"]
        full_db.execute("INSERT INTO questions_detail (question, interview_id) VALUES ('d1', ?)", (iid,))
        did = full_db.execute("SELECT id FROM questions_detail").fetchone()["id"]
        full_db.execute("INSERT INTO analysis_queue (interview_id, question_detail_id) VALUES (?, ?)", (iid, did))
        full_db.execute("INSERT INTO quality_issue (qb_id, issue_type, suggested_action) VALUES (?, 'dup', 'dedupe')", (qid,))
        full_db.execute(
            "INSERT INTO email_verification_codes (email, code, purpose, user_id, expires_at) "
            "VALUES ('a@b.c', '123456', 'register', ?, datetime('now', '+1 hour'))", (uid,)
        )
        full_db.execute("INSERT INTO chat_memories (user_id, memory_type, content) VALUES (?, 'fact', '内容')", (uid,))
        full_db.execute("INSERT INTO coding_problems (title, description, owner_id) VALUES ('题', '描述', ?)", (uid,))
        full_db.execute("INSERT INTO practice_decks (deck_key, name, owner_id) VALUES ('dk1', '清单', ?)", (uid,))

        _apply(full_db, 85)

        assert full_db.execute("SELECT count(*) FROM interview_asked_questions").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM analysis_queue").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM quality_issue").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM email_verification_codes").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM chat_memories").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM coding_problems WHERE title='题'").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM practice_decks WHERE deck_key='dk1'").fetchone()[0] == 1
        assert full_db.execute("SELECT count(*) FROM chat_conversations").fetchone()[0] == 1
        mem = full_db.execute("SELECT content FROM chat_memories").fetchone()["content"]
        assert mem == "内容"
        q = full_db.execute("SELECT question FROM question_bank WHERE id=?", (qid,)).fetchone()["question"]
        assert q == "保持题"
        assert full_db.execute("PRAGMA foreign_key_check").fetchall() == []

    def test_idempotent(self, full_db):
        _apply(full_db, 85)
        _apply(full_db, 85)
        assert _fk_count(full_db, "interview_asked_questions") == 3


# ── 086 ─────────────────────────────────────────────────────────────────────


class Test086DeadColumnsAndIndexes:
    def test_drops_dead_columns_and_adds_indexes(self, full_db):
        _apply(full_db, 86)
        qb_cols = {r[1] for r in full_db.execute("PRAGMA table_info('question_bank')")}
        assert "vector" not in qb_cols
        assert "duplicate_of" not in qb_cols
        idx = {r[0] for r in full_db.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert "idx_email_codes_expires" in idx
        assert "idx_rt_expires" in idx
        assert "idx_qb_duplicate_of" not in idx


# ── 全链 ────────────────────────────────────────────────────────────────────


class TestFullChain:
    def test_081_to_086_chain_on_seeded_db(self, full_db):
        uid = _seed_user(full_db, "ChainUser")
        full_db.execute("INSERT INTO chat_conversations (id, user_id, mode) VALUES ('c1', ?, 'interview')", (uid,))
        qid = _seed_question(full_db, "链上题")
        with _orphan_inserts(full_db):
            full_db.execute("INSERT INTO chat_messages (conversation_id, role, content) VALUES ('gone', 'user', 'orphan')")
            full_db.execute("INSERT INTO quality_issue (qb_id, issue_type, suggested_action) VALUES (999999, 'mismerge', 'split')")
            full_db.execute("INSERT INTO interview_asked_questions (user_id, conversation_id, question_id) VALUES (?, 'gone', ?)", (uid, qid))

        _apply(full_db, 81, 82, 83, 84, 85, 86)

        assert full_db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert full_db.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM interview_asked_questions").fetchone()[0] == 0
        assert full_db.execute("SELECT count(*) FROM quality_issue").fetchone()[0] == 0
        n_fts = full_db.execute("SELECT count(*) FROM question_fts").fetchone()[0]
        n_qb = full_db.execute("SELECT count(*) FROM question_bank").fetchone()[0]
        assert n_fts == n_qb
        # 触发同步仍生效
        full_db.execute("INSERT INTO question_bank (question) VALUES ('链后新题')")
        assert full_db.execute("SELECT count(*) FROM question_fts").fetchone()[0] == n_qb + 1

"""UR-004 / AC-013：配额预留的事务性与旧 wrapper 兼容。

契约（contracts.md §1.7）：

- 提供**不自行 commit** 的预留接口，供外层业务事务原子写入；
- 旧 `check_and_record` 保持原有 commit 语义，不能让其它调用方回归；
- 重试是新的 call_key（物理尝试），不是复用旧键。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services import llm_quota
from app.services.upload_credentials import reserve_llm_call


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k1', 'h1', 'private', 'interview', 'v1')"
    )
    conn.commit()
    return conn


def test_reserve_call_does_not_commit_inside_transaction():
    conn = _db()
    conn.execute("BEGIN IMMEDIATE")
    allowed = llm_quota.reserve_call(conn, user_id=101, day="2026-09-29", tokens=0, limit=5)
    assert allowed is True
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0
    conn.close()


def test_old_wrapper_still_commits_and_respects_limit(monkeypatch):
    conn = _db()
    monkeypatch.setattr(llm_quota, "get_db_connection", lambda: conn)
    monkeypatch.setattr(llm_quota, "_today", lambda: "2026-09-29")

    assert llm_quota._increment_usage(conn, 101, "2026-09-29", 0, limit=1) is True
    # wrapper 内部 commit：即使外层没有事务，计数也必须落库
    assert conn.execute("SELECT call_count FROM llm_usage").fetchone()[0] == 1
    assert llm_quota._increment_usage(conn, 101, "2026-09-29", 0, limit=1) is False
    conn.close()


def test_retries_use_distinct_call_keys():
    conn = _db()
    for attempt in (1, 2, 3):
        reserve_llm_call(
            conn,
            root_import_id="imp-1",
            stage="extract",
            unit_key="document",
            call_key=f"imp-1:extract:document:{attempt}",
            credential_scope="user",
            payer_type="user",
            payer_user_id=101,
        )
    assert conn.execute("SELECT COUNT(*) FROM upload_llm_calls").fetchone()[0] == 3
    rows = conn.execute("SELECT COUNT(*) FROM llm_usage WHERE user_id = 101").fetchone()[0]
    assert rows == 1  # 同一天同一用户一行，call_count=3
    assert conn.execute("SELECT call_count FROM llm_usage").fetchone()[0] == 3
    conn.close()

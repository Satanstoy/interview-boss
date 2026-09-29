"""阶段B：upload recovery 存储增量（AC-023 迁移幂等、AC-021 幂等键）。

测试全部使用内存库：空库迁移、旧 schema 升级、重复运行、唯一约束、repository 契约。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_repository import (
    IdempotencyConflict,
    create_attempt,
    create_or_get_import,
    get_import_by_key,
    save_stage_result,
)

NEW_TABLES = (
    "upload_imports",
    "upload_attempts",
    "upload_stage_results",
    "question_resolutions",
    "upload_llm_calls",
    "upload_scope_leases",
)


def _fresh():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    for user_id in (101, 102, 201):
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            (user_id, f"u{user_id}", "x"),
        )
    conn.commit()
    return conn


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _make_import(conn, **overrides):
    payload = {
        "requester_id": 101,
        "idempotency_key": "key-1",
        "request_hash": "hash-1",
        "target_intent": "private",
        "source_type": "interview",
        "resolved_type": None,
        "position_id": None,
        "position_name": "后端",
        "pipeline_version": "upload-pipeline-v1",
        "policy_json": "{}",
        "payload_json": "{}",
    }
    payload.update(overrides)
    return create_or_get_import(conn, **payload)


# ── 迁移 ─────────────────────────────────────────────────────


def test_migrations_create_new_tables_on_empty_database():
    conn = _fresh()
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = set(NEW_TABLES) - tables
    assert not missing, f"缺少新表: {missing}"
    conn.close()


def test_jobs_gain_v2_columns_that_stay_nullable():
    conn = _fresh()
    cols = _columns(conn, "jobs")
    assert {"root_import_id", "upload_attempt_id", "work_key", "lease_generation"} <= cols
    # 旧行必须可以存在且新列为空
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by) "
        "VALUES ('submit_import','completed',101)"
    )
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["root_import_id"] is None
    assert row["upload_attempt_id"] is None
    assert row["work_key"] is None
    assert row["lease_generation"] == 0
    conn.close()


def test_questions_detail_gains_import_ordinal_with_unique_constraint():
    conn = _fresh()
    cols = _columns(conn, "questions_detail")
    assert {"import_id", "source_ordinal"} <= cols
    conn.close()


def test_public_contribution_gains_revision_and_projection():
    conn = _fresh()
    cols = _columns(conn, "public_contribution_requests")
    assert "revision" in cols and "review_projection_json" in cols
    conn.close()


def test_analysis_queue_gains_scope_lease_columns():
    conn = _fresh()
    cols = _columns(conn, "analysis_queue")
    assert {"root_import_id", "lease_generation", "locked_until", "claimed_at"} <= cols
    conn.close()


def test_running_migrations_twice_changes_nothing():
    conn = _fresh()
    before = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    schema_before = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    run_migrations(conn)
    after = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    schema_after = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    assert before == after
    assert schema_before == schema_after
    conn.close()


def test_legacy_database_upgrade_keeps_old_rows_readable():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)  # 先到新 schema，再模拟旧行（新列留空）
    conn.execute(
        "INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, result) "
        "VALUES ('submit_import','completed',101,'{\"interview_id\": 1}')"
    )
    conn.execute(
        "INSERT INTO question_bank (question, cat1, cat2, owner_id, status) "
        "VALUES ('旧题','计算机','数据库',NULL,'approved')"
    )
    conn.commit()
    row = conn.execute("SELECT * FROM jobs").fetchone()
    assert row["result"] == '{"interview_id": 1}'
    assert row["root_import_id"] is None
    assert row["lease_generation"] == 0
    # 旧公共数据可见性口径不变
    visible = conn.execute(
        "SELECT COUNT(*) FROM question_bank WHERE owner_id IS NULL AND status='approved' "
        "AND deleted_at IS NULL"
    ).fetchone()[0]
    assert visible == 1
    conn.close()


# ── 约束 ─────────────────────────────────────────────────────


def test_upload_imports_unique_per_requester_and_key():
    conn = _fresh()
    _make_import(conn)
    # 数据库层面兜底：同用户同键重复插入必须失败
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO upload_imports (id, requester_id, idempotency_key, "
            "request_hash, target_intent, source_type, pipeline_version) "
            "VALUES ('raw-1', 101, 'key-1', 'hash-2', 'private', 'interview', 'v1')"
        )
    # 不同用户同键互不干扰
    _make_import(conn, requester_id=102)
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 2
    conn.close()


def test_upload_attempts_allow_one_active_per_import():
    conn = _fresh()
    import_id, _ = _make_import(conn)
    create_attempt(conn, import_id=import_id, requested_by=101)
    with pytest.raises(sqlite3.IntegrityError):
        create_attempt(conn, import_id=import_id, requested_by=101)
    conn.close()


def test_upload_stage_results_keyed_by_stage_unit_and_input_version():
    conn = _fresh()
    import_id, _ = _make_import(conn)
    save_stage_result(
        conn,
        import_id=import_id,
        stage="extract",
        unit_key="document",
        input_version=1,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json='{"questions": []}',
    )
    with pytest.raises(sqlite3.IntegrityError):
        save_stage_result(
            conn,
            import_id=import_id,
            stage="extract",
            unit_key="document",
            input_version=1,
            pipeline_version="upload-pipeline-v1",
            status="succeeded",
            result_json='{"questions": []}',
        )
    # 不同 input_version 允许并存
    save_stage_result(
        conn,
        import_id=import_id,
        stage="extract",
        unit_key="document",
        input_version=2,
        pipeline_version="upload-pipeline-v1",
        status="succeeded",
        result_json='{"questions": []}',
    )
    conn.close()


def test_question_resolutions_allow_one_current_per_detail():
    conn = _fresh()
    cols = _columns(conn, "question_resolutions")
    assert {
        "detail_id",
        "occurrence_scope",
        "occurrence_owner_id",
        "canonical_id",
        "status",
        "invalidated_at",
    } <= cols
    conn.close()


def test_upload_llm_calls_unique_call_key():
    conn = _fresh()
    cols = _columns(conn, "upload_llm_calls")
    assert {"call_key", "credential_scope", "payer_type", "payer_user_id"} <= cols
    conn.close()


def test_upload_scope_leases_have_generation_and_lock():
    conn = _fresh()
    cols = _columns(conn, "upload_scope_leases")
    assert {"scope_key", "holder_token", "generation", "locked_until"} <= cols
    conn.close()


# ── repository 契约 ─────────────────────────────────────────


def test_create_or_get_import_reuses_same_key_and_hash():
    conn = _fresh()
    import_id, created = _make_import(conn)
    assert created is True
    same_id, created_again = _make_import(conn)
    assert created_again is False
    assert same_id == import_id
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1
    conn.close()


def test_create_or_get_import_conflicts_on_same_key_different_hash():
    conn = _fresh()
    _make_import(conn)
    with pytest.raises(IdempotencyConflict):
        _make_import(conn, request_hash="other-hash")
    conn.close()


def test_create_or_get_import_isolated_between_users():
    conn = _fresh()
    mine, _ = _make_import(conn, requester_id=101)
    other, _ = _make_import(conn, requester_id=102)
    assert mine != other
    conn.close()


def test_get_import_by_key_only_returns_own():
    conn = _fresh()
    import_id, _ = _make_import(conn, requester_id=101)
    assert get_import_by_key(conn, requester_id=101, idempotency_key="key-1")[0] == import_id
    assert get_import_by_key(conn, requester_id=102, idempotency_key="key-1") is None
    conn.close()


def test_create_import_does_not_commit_caller_transaction():
    """repository 不能内部 commit：外层回滚必须带走根任务。"""

    conn = _fresh()
    conn.execute("BEGIN IMMEDIATE")
    _make_import(conn)
    conn.execute("ROLLBACK")
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0
    conn.close()

"""AC-026 / UR-026：历史与保留清理 —— 恢复资料不得被 90 天策略误删。

契约（contracts §5.8）：

- 活跃、needs_action、partial_failed、failed 的恢复任务及其 payload 一律保留；
- completed 超 90 天只清大 payload/checkpoint 正文，保留 import 摘要与结果引用；
- 历史恢复材料缺失时返回 ``SOURCE_EXPIRED``，不能空跑。
"""

from __future__ import annotations

import sqlite3

from app.db.migrations import run_migrations
from app.worker_scheduled import run_db_retention


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.commit()
    return conn


def _import(conn, import_id, *, status="completed", age_days=120):
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status, payload_json, updated_at, "
        "payload_expires_at) VALUES (?, 101, ?, 'h', 'private', 'interview', 'v1', ?, ?, ?, NULL)",
        (
            import_id,
            f"k-{import_id}",
            status,
            f"SECRET-PAYLOAD-{import_id}",
            f"datetime('now', '-{age_days} days')",
        ),
    )
    conn.execute(
        "UPDATE upload_imports SET updated_at = datetime('now', ?), "
        "created_at = datetime('now', ?) WHERE id = ?",
        (f"-{age_days} days", f"-{age_days} days", import_id),
    )


def _job(conn, import_id, *, status="completed", age_days=120):
    cur = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, result, "
        "completed_at) VALUES ('submit_import', ?, 101, ?, ?, datetime('now', ?))",
        (status, import_id, '{"interview_id": 1}', f"-{age_days} days"),
    )
    job_id = cur.lastrowid
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, f"SECRET-JOB-PAYLOAD-{import_id}"),
    )
    conn.execute(
        "INSERT INTO upload_stage_results (import_id, stage, unit_key, pipeline_version, "
        "status, result_json) VALUES (?, 'extract', 'document', 'v1', 'succeeded', ?)",
        (import_id, f"SECRET-CHECKPOINT-{import_id}"),
    )
    return job_id


def test_active_and_failed_roots_keep_everything():
    conn = _db()
    for import_id, status in (
        ("imp-run", "queued"),
        ("imp-fail", "failed"),
        ("imp-partial", "partial_failed"),
        ("imp-action", "needs_action"),
    ):
        _import(conn, import_id, status=status)
        _job(conn, import_id, status="running" if status == "queued" else "failed")

    run_db_retention(conn)

    for import_id in ("imp-run", "imp-fail", "imp-partial", "imp-action"):
        row = conn.execute(
            "SELECT payload_json FROM upload_imports WHERE id = ?", (import_id,)
        ).fetchone()
        assert row is not None, f"{import_id} 的 import 摘要不得删除"
        assert f"SECRET-PAYLOAD-{import_id}" in row["payload_json"]
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM job_payloads WHERE payload LIKE 'SECRET-JOB-PAYLOAD-%'"
        ).fetchone()[0]
        == 4
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM upload_stage_results WHERE result_json LIKE 'SECRET-CHECKPOINT-%'"
        ).fetchone()[0]
        == 4
    )
    conn.close()


def test_completed_root_clears_payload_but_keeps_summary_and_result():
    conn = _db()
    _import(conn, "imp-done")
    job_id = _job(conn, "imp-done")

    run_db_retention(conn)

    row = conn.execute("SELECT * FROM upload_imports WHERE id = 'imp-done'").fetchone()
    assert row is not None, "import 摘要必须保留"
    assert "SECRET-PAYLOAD" not in (row["payload_json"] or "")
    assert row["payload_expires_at"] is not None

    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert job is not None, "结果引用所在 job 行必须保留"
    assert job["result"], "结果引用不得清空"
    payload = conn.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
    ).fetchone()
    assert "SECRET-JOB-PAYLOAD" not in (payload["payload"] or "")
    checkpoint = conn.execute(
        "SELECT result_json FROM upload_stage_results WHERE import_id = 'imp-done'"
    ).fetchone()
    assert "SECRET-CHECKPOINT" not in (checkpoint["result_json"] or "")
    conn.close()


def test_legacy_completed_jobs_still_cleaned_up():
    conn = _db()
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, completed_at) "
        "VALUES ('submit_import', 'completed', 101, datetime('now', '-120 days'))"
    )
    run_db_retention(conn)
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    conn.close()


def test_completed_payload_retention_starts_after_90_day_boundary():
    conn = _db()
    for import_id in ("imp-before-boundary", "imp-after-boundary"):
        _import(conn, import_id)
        _job(conn, import_id)
    conn.execute(
        "UPDATE upload_imports SET updated_at = datetime('now', '-90 days', '+1 minute') "
        "WHERE id = 'imp-before-boundary'"
    )
    conn.execute(
        "UPDATE upload_imports SET updated_at = datetime('now', '-90 days', '-1 minute') "
        "WHERE id = 'imp-after-boundary'"
    )
    conn.commit()

    run_db_retention(conn)

    before = conn.execute(
        "SELECT payload_json FROM upload_imports WHERE id = 'imp-before-boundary'"
    ).fetchone()
    after = conn.execute(
        "SELECT payload_json, payload_expires_at FROM upload_imports "
        "WHERE id = 'imp-after-boundary'"
    ).fetchone()
    assert "SECRET-PAYLOAD-imp-before-boundary" in before["payload_json"]
    assert after["payload_json"] == "{}"
    assert after["payload_expires_at"] is not None
    assert conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE root_import_id IN "
        "('imp-before-boundary', 'imp-after-boundary')"
    ).fetchone()[0] == 2
    conn.close()

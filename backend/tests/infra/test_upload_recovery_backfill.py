"""AC-023：历史迁移 dry-run、幂等 apply 与歧义报告。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_backfill import (
    ManifestMismatch,
    apply_backfill,
    plan_backfill,
)


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (1, 'https://a.example.com/1', 'A', '一面', '1.x', 101, 'approved', '后端')"
    )
    conn.commit()
    return conn


def _legacy_job(conn, *, job_id, parent=None, status="failed", result=None):
    conn.execute(
        "INSERT INTO jobs (id, job_type, status, created_by, parent_job_id, result) "
        "VALUES (?, 'submit_import', ?, 101, ?, ?)",
        (job_id, status, parent, result),
    )


def test_dry_run_reports_counts_and_creates_nothing():
    conn = _db()
    _legacy_job(conn, job_id=10, status="failed")
    _legacy_job(conn, job_id=11, parent=10, status="failed")
    _legacy_job(conn, job_id=12, parent=11, status="running")
    conn.commit()

    report = plan_backfill(conn)
    assert report["chains_scanned"] == 1
    assert report["imports_created"] == 1
    assert report["jobs_linked"] == 3
    assert report["manifest_hash"]
    # dry-run 不写库
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0
    assert (
        conn.execute("SELECT COUNT(*) FROM jobs WHERE root_import_id IS NOT NULL").fetchone()[0]
        == 0
    )
    conn.close()


def test_apply_twice_adds_nothing():
    conn = _db()
    _legacy_job(conn, job_id=10, status="failed")
    _legacy_job(conn, job_id=11, parent=10, status="failed")
    conn.commit()

    plan = plan_backfill(conn)
    first = apply_backfill(conn, manifest=plan, expected_manifest_hash=plan["manifest_hash"])
    assert first["imports_created"] == 1
    assert first["jobs_linked"] == 2

    second_plan = plan_backfill(conn)
    second = apply_backfill(
        conn, manifest=second_plan, expected_manifest_hash=second_plan["manifest_hash"]
    )
    assert second["imports_created"] == 0
    assert second["attempts_created"] == 0
    assert second["jobs_linked"] == 0
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()


def test_cycle_in_parent_chain_is_reported_not_resolved():
    conn = _db()
    _legacy_job(conn, job_id=10, status="failed")
    _legacy_job(conn, job_id=11, parent=10, status="failed")
    conn.execute("UPDATE jobs SET parent_job_id = 11 WHERE id = 10")  # 造出环
    conn.commit()

    report = plan_backfill(conn)
    reasons = {item["reason"] for item in report["ambiguous"]}
    assert "cycle_in_parent_chain" in reasons
    assert report["imports_created"] == 0
    # 不猜测：不创建任何 import
    apply_backfill(conn, manifest=report, expected_manifest_hash=report["manifest_hash"])
    assert conn.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0
    conn.close()


def test_completed_without_interview_is_ambiguous():
    conn = _db()
    _legacy_job(conn, job_id=10, status="completed", result=None)
    conn.commit()

    report = plan_backfill(conn)
    assert any(item["reason"] == "completed_without_interview" for item in report["ambiguous"])
    conn.close()


def test_completed_with_missing_interview_is_ambiguous():
    conn = _db()
    _legacy_job(
        conn,
        job_id=10,
        status="completed",
        result=json.dumps({"interview_id": 999}),
    )
    conn.commit()
    report = plan_backfill(conn)
    assert any(item["reason"] == "result_interview_missing" for item in report["ambiguous"])
    conn.close()


def test_manifest_mismatch_is_rejected():
    conn = _db()
    _legacy_job(conn, job_id=10, status="failed")
    conn.commit()
    plan = plan_backfill(conn)
    # 规划后又插入新链 → manifest 变化
    _legacy_job(conn, job_id=20, status="failed")
    conn.commit()
    with pytest.raises(ManifestMismatch):
        apply_backfill(conn, manifest=plan, expected_manifest_hash=plan["manifest_hash"])
    conn.close()


def test_report_never_leaks_payload_or_questions():
    conn = _db()
    _legacy_job(conn, job_id=10, status="failed")
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (10, ?)",
        (json.dumps({"raw_text": "SECRET-RAW-TEXT", "image_data": ["SECRET-IMAGE"]}),),
    )
    conn.commit()
    report = plan_backfill(conn)
    dumped = json.dumps(report, ensure_ascii=False, default=str)
    assert "SECRET-RAW-TEXT" not in dumped
    assert "SECRET-IMAGE" not in dumped
    conn.close()

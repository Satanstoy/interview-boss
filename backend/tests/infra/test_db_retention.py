"""DB 保留期清理任务测试（worker 每日执行）。

覆盖 D9 findings：email_verification_codes / analysis_queue / login_failures / jobs
均无按龄清理机制（941 行中 936 过期、593 行全 done、302 行常驻）。
"""

from __future__ import annotations

import sqlite3

import pytest


def _insert_email_code(conn, email: str, expires_sql: str, used: int = 0, created_sql: str = "CURRENT_TIMESTAMP"):
    conn.execute(
        "INSERT INTO email_verification_codes (email, code, purpose, user_id, expires_at, used, created_at) "
        f"VALUES (?, '123456', 'register', NULL, {expires_sql}, ?, {created_sql})",
        (email, used),
    )


class TestDbRetention:
    def test_email_codes_cleanup(self, test_db):
        _insert_email_code(test_db, "expired@x.com", "datetime('now', '-1 day')")
        _insert_email_code(test_db, "fresh@x.com", "datetime('now', '+1 day')")
        _insert_email_code(test_db, "usedold@x.com", "datetime('now', '+1 day')", used=1, created_sql="datetime('now', '-31 days')")
        _insert_email_code(test_db, "usedrecent@x.com", "datetime('now', '+1 day')", used=1, created_sql="datetime('now', '-5 days')")
        test_db.commit()

        from app.worker import run_db_retention

        run_db_retention(test_db)

        remaining = [r[0] for r in test_db.execute("SELECT email FROM email_verification_codes ORDER BY email")]
        assert remaining == ["fresh@x.com", "usedrecent@x.com"]

    def test_analysis_queue_cleanup(self, test_db):
        test_db.execute("INSERT INTO interview (url) VALUES ('http://a')")
        iid = test_db.execute("SELECT id FROM interview").fetchone()["id"]
        test_db.execute(
            "INSERT INTO analysis_queue (interview_id, status, created_at) "
            "VALUES (?, 'done', datetime('now', '-40 days'))", (iid,)
        )
        test_db.execute(
            "INSERT INTO analysis_queue (interview_id, status, created_at) "
            "VALUES (?, 'pending', CURRENT_TIMESTAMP)", (iid,)
        )
        test_db.commit()

        from app.worker import run_db_retention

        run_db_retention(test_db)

        statuses = [r[0] for r in test_db.execute("SELECT status FROM analysis_queue")]
        assert statuses == ["pending"]

    def test_login_failures_cleanup(self, test_db):
        test_db.execute(
            "INSERT INTO login_failures (username, failure_count, locked_until, updated_at) "
            "VALUES ('unlocked-old', 1, '', datetime('now', '-40 days'))"
        )
        test_db.execute(
            "INSERT INTO login_failures (username, failure_count, locked_until, updated_at) "
            "VALUES ('locked', 5, datetime('now', '+1 hour'), CURRENT_TIMESTAMP)"
        )
        test_db.execute(
            "INSERT INTO login_failures (username, failure_count, locked_until, updated_at) "
            "VALUES ('unlocked-recent', 2, '', CURRENT_TIMESTAMP)"
        )
        test_db.commit()

        from app.worker import run_db_retention

        run_db_retention(test_db)

        names = [r[0] for r in test_db.execute("SELECT username FROM login_failures ORDER BY username")]
        assert names == ["locked", "unlocked-recent"]

    def test_jobs_cleanup_keeps_lineage(self, test_db):
        test_db.execute(
            "INSERT INTO jobs (job_type, status, completed_at) "
            "VALUES ('import', 'completed', datetime('now', '-100 days'))"
        )
        test_db.execute(
            "INSERT INTO jobs (job_type, status, completed_at) "
            "VALUES ('import', 'completed', datetime('now', '-10 days'))"
        )
        cur = test_db.execute(
            "INSERT INTO jobs (job_type, status, completed_at) "
            "VALUES ('import', 'completed', datetime('now', '-100 days'))"
        )
        parent_id = cur.lastrowid
        test_db.execute(
            "INSERT INTO jobs (job_type, status, completed_at, parent_job_id) "
            "VALUES ('answer', 'completed', datetime('now', '-100 days'), ?)", (parent_id,)
        )
        test_db.execute(
            "INSERT INTO jobs (job_type, status, completed_at) "
            "VALUES ('import', 'running', NULL)"
        )
        test_db.commit()

        from app.worker import run_db_retention

        run_db_retention(test_db)

        rows = test_db.execute("SELECT id, status FROM jobs ORDER BY id").fetchall()
        # 老 completed 叶子任务（含子任务链上的叶子）被删；有子任务的父任务保留；
        # 近期 completed 保留；running 保留
        assert len(rows) == 3
        assert rows[0]["status"] == "completed"  # 近期
        assert rows[1]["status"] == "completed"  # 有子任务的老任务（parent，血缘保护）
        assert rows[2]["status"] == "running"

    def test_cleanup_is_safe_on_empty_db(self, test_db):
        from app.worker import run_db_retention

        run_db_retention(test_db)  # 不抛异常

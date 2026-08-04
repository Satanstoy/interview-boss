"""Tests for migration 049 (analysis_queue.owner_id) and 050 (pipeline_metrics)."""

from __future__ import annotations

import sqlite3
import pytest


def _new_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn


class TestMigration049AnalysisQueueOwner:
    def test_adds_owner_id_column(self):
        conn = _new_conn()
        conn.execute("""
            CREATE TABLE analysis_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                question_detail_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP,
                processed_at TIMESTAMP
            )
        """)
        conn.commit()

        from app.db.migrations.jobs import _migration_049_analysis_queue_owner

        _migration_049_analysis_queue_owner(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info('analysis_queue')")}
        assert "owner_id" in cols

    def test_is_idempotent(self):
        conn = _new_conn()
        conn.execute("CREATE TABLE analysis_queue (id INTEGER PRIMARY KEY)")
        conn.commit()

        from app.db.migrations.jobs import _migration_049_analysis_queue_owner

        _migration_049_analysis_queue_owner(conn)
        _migration_049_analysis_queue_owner(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info('analysis_queue')")}
        assert "owner_id" in cols

    def test_existing_rows_get_null_owner(self):
        conn = _new_conn()
        conn.execute("""
            CREATE TABLE analysis_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending'
            )
        """)
        conn.execute("INSERT INTO analysis_queue (interview_id) VALUES (1), (2)")
        conn.commit()

        from app.db.migrations.jobs import _migration_049_analysis_queue_owner

        _migration_049_analysis_queue_owner(conn)

        rows = conn.execute("SELECT owner_id FROM analysis_queue").fetchall()
        assert all(r["owner_id"] is None for r in rows)

    def test_registered_after_048(self):
        from app.db.migrations import _MIGRATIONS

        versions = [v for v, _, _ in _MIGRATIONS]
        assert 49 in versions
        assert versions.index(49) == versions.index(48) + 1


class TestMigration050PipelineMetrics:
    def test_creates_table(self):
        conn = _new_conn()

        from app.db.migrations.jobs import _migration_050_pipeline_metrics

        _migration_050_pipeline_metrics(conn)

        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "pipeline_metrics" in tables

    def test_table_has_expected_columns(self):
        conn = _new_conn()

        from app.db.migrations.jobs import _migration_050_pipeline_metrics

        _migration_050_pipeline_metrics(conn)

        cols = {r[1] for r in conn.execute("PRAGMA table_info('pipeline_metrics')")}
        for expected in (
            "operation",
            "job_position",
            "owner_id",
            "questions_in",
            "matched",
            "new_clusters",
            "merged",
            "llm_calls",
            "elapsed_seconds",
            "error",
            "created_at",
        ):
            assert expected in cols, f"Missing column: {expected}"

    def test_is_idempotent(self):
        conn = _new_conn()

        from app.db.migrations.jobs import _migration_050_pipeline_metrics

        _migration_050_pipeline_metrics(conn)
        _migration_050_pipeline_metrics(conn)

        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "pipeline_metrics" in tables

    def test_registered_after_049(self):
        from app.db.migrations import _MIGRATIONS

        versions = [v for v, _, _ in _MIGRATIONS]
        assert 50 in versions
        assert versions.index(50) == versions.index(49) + 1

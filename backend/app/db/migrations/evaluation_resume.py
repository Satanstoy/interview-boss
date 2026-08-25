"""Resume lineage for immutable evaluation Runs (migration 116)."""

from __future__ import annotations


def _migration_116_evaluation_resume(conn):
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(eval_runs)").fetchall()
    }
    if "resume_of_run_id" not in columns:
        conn.execute(
            "ALTER TABLE eval_runs ADD COLUMN resume_of_run_id INTEGER "
            "REFERENCES eval_runs(id) ON DELETE SET NULL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_eval_runs_resume_of "
        "ON eval_runs(resume_of_run_id)"
    )

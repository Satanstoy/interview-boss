"""Database guard for one active continuation per source Run."""


def _migration_117_evaluation_resume_idempotency(conn):
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_eval_runs_active_resume_of
        ON eval_runs(resume_of_run_id)
        WHERE resume_of_run_id IS NOT NULL
          AND status IN ('created', 'queued', 'running')
        """
    )

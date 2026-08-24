"""Safe lifecycle columns for administrator-managed job positions."""

import logging

logger = logging.getLogger("interview-boss")


def _migration_105_position_retirement(conn):
    """Add a durable soft-retirement flag without touching business rows."""
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'job_positions'"
    ).fetchone()
    if not table_exists:
        return

    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('job_positions')").fetchall()
    }
    if "is_deleted" not in columns:
        conn.execute(
            "ALTER TABLE job_positions ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0"
        )
    conn.execute("UPDATE job_positions SET is_deleted = 0 WHERE is_deleted IS NULL")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_positions_active "
        "ON job_positions(is_deleted, name)"
    )
    logger.info("migration_105: job position retirement is ready")

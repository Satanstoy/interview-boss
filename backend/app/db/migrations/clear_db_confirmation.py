"""Migration for durable, single-use clear-db confirmations."""


def _migration_120_clear_db_confirmations(conn):
    """Store consumed confirmation digests outside the business cleanup set."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clear_db_confirmations (
            token_hash TEXT PRIMARY KEY,
            admin_id INTEGER NOT NULL,
            consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_clear_db_confirmation_admin "
        "ON clear_db_confirmations(admin_id, consumed_at)"
    )

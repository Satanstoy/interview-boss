"""Durable administrative audit records."""


def _migration_119_admin_audit_log(conn):
    """Create an audit table intentionally excluded from clear-db cleanup."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            status TEXT NOT NULL,
            actor_id INTEGER,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_audit_event ON admin_audit_log(event_type, created_at)"
    )

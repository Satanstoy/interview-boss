"""Recruitment preference migration."""


def _migration_062_user_recruitment_pref(conn):
    """Create per-user recruitment preference table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_recruitment_pref (
            user_id INTEGER PRIMARY KEY,
            graduation_year INTEGER,
            batch TEXT DEFAULT '',
            daily_capacity INTEGER DEFAULT 30,
            updated_at TEXT
        )
        """
    )

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
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _migration_064_user_recruitment_pace(conn):
    """Add pace column to user_recruitment_pref.

    Existing databases already ran migration 062, so guard with PRAGMA
    before ALTER. Fresh databases run 062 (no pace) then this ALTER.
    """
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(user_recruitment_pref)").fetchall()]
    if "pace" not in cols:
        conn.execute(
            "ALTER TABLE user_recruitment_pref ADD COLUMN pace TEXT NOT NULL DEFAULT 'standard'"
        )

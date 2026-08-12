"""Review-event snapshots used for safe rating corrections."""


def _migration_078_practice_review_corrections(conn):
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(practice_review_events)")
    }
    if "before_state_json" not in columns:
        conn.execute(
            "ALTER TABLE practice_review_events ADD COLUMN before_state_json TEXT"
        )
    if "corrected_at" not in columns:
        conn.execute(
            "ALTER TABLE practice_review_events ADD COLUMN corrected_at TIMESTAMP"
        )

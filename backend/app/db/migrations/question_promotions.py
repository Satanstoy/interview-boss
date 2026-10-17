"""Explicit immutable promotion records for the compatible single-question API."""


def _migration_126_question_promotions(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_promotion_requests (
            pending_question_id INTEGER PRIMARY KEY,
            source_question_id INTEGER REFERENCES question_bank(id) ON DELETE SET NULL,
            requester_id INTEGER REFERENCES users(id),
            snapshot_json TEXT NOT NULL,
            review_projection_json TEXT,
            target_question_id INTEGER REFERENCES question_bank(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','withdrawn')),
            reviewer_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_at TEXT
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_pending_question_promotion "
        "ON question_promotion_requests(source_question_id) "
        "WHERE status='pending' AND source_question_id IS NOT NULL"
    )
    # Historical pending rows have no reliable private source identity. They
    # remain reviewable, but approval must not guess which private row to retire.

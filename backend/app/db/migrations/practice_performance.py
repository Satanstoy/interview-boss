"""Indexes for the flashcard queue query path."""


def _migration_059_practice_queue_indexes(conn):
    """Cover the joins and fallback filters used when switching practice decks."""

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qp_position_question "
        "ON question_position(position_id, question_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qb_job_position_visibility "
        "ON question_bank(job_position, deleted_at, owner_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interview_url_owner_deleted "
        "ON interview(url, owner_id, deleted_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_deck_items_queue "
        "ON practice_deck_items(deck_id, sort_order, id, question_bank_id)"
    )

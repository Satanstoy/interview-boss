"""Custom practice deck membership migration."""


def _migration_056_custom_practice_decks(conn):
    """Allow users to create private named decks backed by question items."""

    columns = {row[1] for row in conn.execute("PRAGMA table_info('practice_decks')").fetchall()}
    if "owner_id" not in columns:
        conn.execute("ALTER TABLE practice_decks ADD COLUMN owner_id INTEGER")
    if "visibility" not in columns:
        conn.execute("ALTER TABLE practice_decks ADD COLUMN visibility TEXT NOT NULL DEFAULT 'private'")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_deck_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (deck_id) REFERENCES practice_decks(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            UNIQUE (deck_id, question_bank_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_decks_owner "
        "ON practice_decks(owner_id, sort_order)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_deck_items_order "
        "ON practice_deck_items(deck_id, sort_order, id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_practice_deck_items_question "
        "ON practice_deck_items(question_bank_id)"
    )

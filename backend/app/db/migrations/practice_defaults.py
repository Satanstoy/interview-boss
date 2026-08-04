"""Remove legacy system practice categories after the deck model was simplified."""


def _migration_057_practice_default_decks(conn):
    """Keep only the two built-in decks; user-created decks are untouched."""

    conn.execute(
        "DELETE FROM practice_decks "
        "WHERE owner_id IS NULL AND deck_key IN ('due', 'high-frequency', 'unpracticed')"
    )
    conn.execute(
        """
        UPDATE practice_decks
        SET name = '我的收藏',
            description = '把收藏题集中起来反复背',
            sort_order = 2,
            updated_at = CURRENT_TIMESTAMP
        WHERE owner_id IS NULL AND deck_key = 'starred'
        """
    )
    conn.execute(
        """
        UPDATE practice_decks
        SET name = '全部题',
            description = '按复习状态和面试频率安排顺序',
            sort_order = 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE owner_id IS NULL AND deck_key = 'all'
        """
    )

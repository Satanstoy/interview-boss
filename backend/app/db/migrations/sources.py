"""Sources domain migrations: 016, 023."""

import logging

logger = logging.getLogger("interview-boss")


def ensure_public_url_signature_unique_indexes(conn) -> dict:
    """Install race-proof public-source uniqueness when legacy data is clean.

    Existing dirty databases are deliberately left bootable: the index is
    skipped with a warning until ``fix_question_data_quality.py`` removes the
    duplicates. The repair command calls this again after its transaction.
    """

    result = {"interview": False, "jd": False, "skipped": []}
    for table in ("interview", "jd"):
        duplicate = conn.execute(
            f"SELECT 1 FROM {table} WHERE owner_id IS NULL "
            "AND deleted_at IS NULL AND url_signature != '' "
            "GROUP BY url_signature HAVING COUNT(*) > 1 LIMIT 1"
        ).fetchone()
        if duplicate:
            result["skipped"].append(table)
            logger.warning(
                "public %s has duplicate url_signature; unique index deferred until data repair",
                table,
            )
            continue
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_public_url_signature "
            f"ON {table}(url_signature) WHERE owner_id IS NULL "
            "AND deleted_at IS NULL AND url_signature != ''"
        )
        result[table] = True
    return result


def _migration_016_normalized_source_tables(conn):
    """Create normalized tables to replace JSON TEXT columns in question_bank."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_bank_id, url)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qs_qb ON question_sources(question_bank_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qs_url ON question_sources(url)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_original_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_bank_id, question_text)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qoi_qb ON question_original_items(question_bank_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qoi_text ON question_original_items(question_text)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_original_item_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_item_id INTEGER NOT NULL REFERENCES question_original_items(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(original_item_id, url)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qois_oi ON question_original_item_sources(original_item_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qois_url ON question_original_item_sources(url)"
    )


def _migration_023_duplicate_of(conn):
    """Add duplicate_of column to question_bank for cross-bank dedup."""
    conn.execute(
        "ALTER TABLE question_bank ADD COLUMN duplicate_of INTEGER DEFAULT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qb_duplicate_of ON question_bank(duplicate_of)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(job_type)")


def _migration_047_soft_delete_sources(conn):
    """Add deleted_at columns to question_sources and question_original_item_sources for soft delete support."""
    # Add deleted_at to question_sources
    conn.execute(
        "ALTER TABLE question_sources ADD COLUMN deleted_at TIMESTAMP DEFAULT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qs_deleted_at ON question_sources(deleted_at)"
    )

    # Add deleted_at to question_original_item_sources
    conn.execute(
        "ALTER TABLE question_original_item_sources ADD COLUMN deleted_at TIMESTAMP DEFAULT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qois_deleted_at ON question_original_item_sources(deleted_at)"
    )

    # Add deleted_at to question_original_items
    conn.execute(
        "ALTER TABLE question_original_items ADD COLUMN deleted_at TIMESTAMP DEFAULT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qoi_deleted_at ON question_original_items(deleted_at)"
    )

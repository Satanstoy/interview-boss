"""Sources domain migrations: 016, 023."""

import logging

logger = logging.getLogger("interview-boss")


def _migration_016_normalized_source_tables(conn):
    """Create normalized tables to replace JSON TEXT columns in question_bank."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_bank_id, url)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qs_qb ON question_sources(question_bank_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qs_url ON question_sources(url)")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_original_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_bank_id, question_text)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qoi_qb ON question_original_items(question_bank_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qoi_text ON question_original_items(question_text)")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_original_item_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_item_id INTEGER NOT NULL REFERENCES question_original_items(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(original_item_id, url)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qois_oi ON question_original_item_sources(original_item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qois_url ON question_original_item_sources(url)")


def _migration_023_duplicate_of(conn):
    """Add duplicate_of column to question_bank for cross-bank dedup."""
    conn.execute("ALTER TABLE question_bank ADD COLUMN duplicate_of INTEGER DEFAULT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_duplicate_of ON question_bank(duplicate_of)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(job_type)")

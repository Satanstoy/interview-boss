"""Resume domain migrations: 061."""

import logging

logger = logging.getLogger("interview-boss")


def _migration_061_resume_optimization(conn):
    """Add optimization columns to user_resumes table."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(user_resumes)")
    columns = [row[1] for row in cursor.fetchall()]
    added = False
    if "optimized_text" not in columns:
        conn.execute("ALTER TABLE user_resumes ADD COLUMN optimized_text TEXT")
        added = True
    if "optimization_points" not in columns:
        conn.execute("ALTER TABLE user_resumes ADD COLUMN optimization_points TEXT")
        added = True
    if "optimized_position" not in columns:
        conn.execute("ALTER TABLE user_resumes ADD COLUMN optimized_position TEXT")
        added = True
    if "optimized_at" not in columns:
        conn.execute("ALTER TABLE user_resumes ADD COLUMN optimized_at TIMESTAMP")
        added = True
    if added:
        logger.info("已为 user_resumes 添加简历优化列")

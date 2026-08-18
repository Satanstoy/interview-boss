"""Resume domain migrations: 061, 097."""

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


def _migration_097_resume_user_unique(conn):
    """Enforce one-resume-per-user at the schema level.

    audit D9 / spec Task G1 M45：save_resume 的 DELETE+INSERT 单事务内是竞态
    安全的，但「每用户一份简历」仅在应用层维护；加唯一索引作为 schema 级不变量，
    防止未来改成 upsert/跳删时静默产生重复行（get_resume 会取任意一行）。
    """
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_resume_user_unique "
        "ON user_resumes(user_id)"
    )
    logger.info("已为 user_resumes 添加 user_id 唯一索引")

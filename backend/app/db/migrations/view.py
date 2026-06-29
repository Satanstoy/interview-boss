"""View domain migrations: 008, 013."""

import os
import logging

logger = logging.getLogger("interview-boss")


def _migration_008_user_question_view(conn):
    """Create user_question_view table + indexes."""
    cursor = conn.cursor()

    # ── user_question_view 表（用户个人标注：收藏/标签/笔记/个人答案）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_question_view (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            is_starred INTEGER DEFAULT 0,
            personal_tags TEXT DEFAULT '',
            note TEXT DEFAULT '',
            user_answer TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute("PRAGMA index_list('user_question_view')")
    uqv_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_uqv_user_question" not in uqv_indexes:
        conn.execute("CREATE UNIQUE INDEX idx_uqv_user_question ON user_question_view(user_id, question_bank_id)")
    if "idx_uqv_user_starred" not in uqv_indexes:
        conn.execute("CREATE INDEX idx_uqv_user_starred ON user_question_view(user_id, is_starred)")


def _migration_013_user_question_view_user_answer(conn):
    """user_question_view.user_answer column.
    Migrate question_bank.is_starred -> user_question_view."""
    cursor = conn.cursor()

    # ── 迁移：user_question_view 新增 user_answer 列 ──
    uqv_columns = [row[1] for row in cursor.execute("PRAGMA table_info(user_question_view)").fetchall()]
    if "user_answer" not in uqv_columns:
        conn.execute("ALTER TABLE user_question_view ADD COLUMN user_answer TEXT DEFAULT ''")
        logger.info("已为 user_question_view 表添加 user_answer 列")

    # ── 迁移：question_bank.is_starred → user_question_view ──
    uqv_count = conn.execute("SELECT COUNT(*) FROM user_question_view").fetchone()[0]
    starred_count = conn.execute("SELECT COUNT(*) FROM question_bank WHERE is_starred = 1").fetchone()[0]
    if uqv_count == 0 and starred_count > 0:
        admin_username = os.getenv("ADMIN_USERNAME", "sj")
        admin_row = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()
        if admin_row:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) "
                "SELECT ?, id, 1 FROM question_bank WHERE is_starred = 1",
                (admin_row[0],)
            )
            logger.info(f"已迁移 {starred_count} 条收藏记录到 user_question_view（归属管理员）")

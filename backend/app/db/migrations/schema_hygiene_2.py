"""Schema hygiene migration 090: Fix FK ON DELETE strategy."""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn, table: str, column: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")}
    return column in cols


def _fk_on_delete(conn, table: str, column: str) -> str | None:
    """返回该列 FK 的 ON DELETE 动作。"""
    for r in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
        if r[3] == column:
            return r[6]  # on_delete 列
    return None


def migration_090_analysis_queue_fk(conn):
    """Add ON DELETE CASCADE to analysis_queue.interview_id."""
    if not _table_exists(conn, "analysis_queue"):
        return

    if not _column_exists(conn, "analysis_queue", "interview_id"):
        return

    # 检查是否已经是 CASCADE
    current_action = _fk_on_delete(conn, "analysis_queue", "interview_id")
    if current_action == "CASCADE":
        logger.info("migration_090: analysis_queue.interview_id 已是 CASCADE，跳过")
        return

    # 获取当前列信息
    columns = [row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')")]
    cols = ", ".join(columns)

    # 创建新表（与 085 结构一致，仅修改 FK 策略）
    conn.execute("DROP TABLE IF EXISTS analysis_queue_new")
    conn.execute("""
        CREATE TABLE analysis_queue_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            question_detail_id INTEGER,
            owner_id INTEGER DEFAULT NULL,
            FOREIGN KEY (interview_id) REFERENCES interview(id) ON DELETE CASCADE,
            FOREIGN KEY (question_detail_id) REFERENCES questions_detail(id) ON DELETE CASCADE,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # 复制数据
    conn.execute(f"INSERT INTO analysis_queue_new ({cols}) SELECT {cols} FROM analysis_queue")

    # 删除旧表
    conn.execute("DROP TABLE analysis_queue")

    # 重命名新表
    conn.execute("ALTER TABLE analysis_queue_new RENAME TO analysis_queue")

    # 重建索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_interview ON analysis_queue(interview_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_owner ON analysis_queue(owner_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_question_detail ON analysis_queue(question_detail_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_status ON analysis_queue(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_status_created ON analysis_queue(status, created_at)")

    logger.info("migration_090: analysis_queue.interview_id 已添加 ON DELETE CASCADE")

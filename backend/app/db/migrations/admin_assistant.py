"""Admin assistant migrations: 069.

管理员 AI 助手（聚合质量审查）的对话与操作审计日志。
"""

import logging

logger = logging.getLogger("interview-boss")


def _migration_069_admin_assistant_log(conn):
    """admin_assistant_log 表：管理员 AI 助手对话与操作审计日志。

    role: user（提问）/ assistant（助手回复，含 tool_trace）/ action（管理员确认执行的写操作回执）。
    session 按 session_id + admin_id 隔离，一个管理员不能读他人会话。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS admin_assistant_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "session_id TEXT NOT NULL,"
        "admin_id INTEGER NOT NULL,"
        "role TEXT NOT NULL CHECK (role IN ('user','assistant','action')),"
        "content TEXT NOT NULL DEFAULT '',"
        "tool_trace TEXT,"
        "created_at TEXT DEFAULT (datetime('now'))"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_assistant_log_session "
        "ON admin_assistant_log(session_id, admin_id, id)"
    )
    logger.info("migration_069: admin_assistant_log 表已就绪")


def _migration_070_quality_issue_target(conn):
    """quality_issue 表新增 target_qb_id：误合并「并入到其他题」的目标题 ID。

    split（拆成独立题）/ refine_representative（换成规范题面）时为空；
    merge（并入到其他题）时指向目标题。供卡片「目标题」对照与并入执行使用。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info('quality_issue')")
    columns = [info[1] for info in cursor.fetchall()]
    if "target_qb_id" not in columns:
        conn.execute(
            "ALTER TABLE quality_issue ADD COLUMN target_qb_id INTEGER DEFAULT NULL"
        )
    logger.info("migration_070: quality_issue.target_qb_id 已就绪")


def _migration_071_quality_issue_new_cat2(conn):
    """quality_issue 表新增 new_cat2：拆出/并入后新题的分类。

    拆成独立题时 LLM 重写代表题并重新判定分类（不继承原题 cat2）；
    并入时跟随目标题分类。供卡片「分类变化」展示与 split_variant 执行使用。
    """
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info('quality_issue')")
    columns = [info[1] for info in cursor.fetchall()]
    if "new_cat2" not in columns:
        conn.execute(
            "ALTER TABLE quality_issue ADD COLUMN new_cat2 TEXT DEFAULT NULL"
        )
    logger.info("migration_071: quality_issue.new_cat2 已就绪")


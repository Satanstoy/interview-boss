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

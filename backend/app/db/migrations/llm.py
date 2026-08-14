"""LLM usage quota migrations: 089.

per-user daily LLM call quota（audit D5）。
"""

import logging

logger = logging.getLogger("interview-boss")


def _migration_089_llm_usage(conn):
    """llm_usage 表：按 (user_id, day) 记录每日 LLM 调用次数与 token 消耗。

    call_count：当日累计 LLM 调用次数（作者用次数计配额，不强制 token）。
    total_tokens：当日累计 token 消耗（仅统计，供后续分析，不参与限流）。
    主键 (user_id, day)：每个用户每天一行，天然跨天重置。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_usage ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "day TEXT NOT NULL,"
        "call_count INTEGER NOT NULL DEFAULT 0,"
        "total_tokens INTEGER NOT NULL DEFAULT 0,"
        "updated_at TEXT DEFAULT (datetime('now')),"
        "UNIQUE (user_id, day)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_llm_usage_user_day "
        "ON llm_usage(user_id, day)"
    )
    logger.info("migration_089: llm_usage 表已就绪")

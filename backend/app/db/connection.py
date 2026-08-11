"""
数据库连接管理 — 线程级 SQLite 连接 + async 桥接

迁移函数已拆分至 db/migrations/ 包
业务查询函数已拆分至 db/queries.py
"""
import sqlite3
import asyncio
import threading
import logging

from app.core.config import DB_PATH

logger = logging.getLogger("interview-boss")

_local = threading.local()


def get_db_connection():
    """获取线程本地数据库连接，避免每次请求重复建立连接和设置 PRAGMA"""
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    _local.conn = conn
    return conn


def init_db():
    """初始化数据库：运行所有迁移"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        from app.db.migrations import run_migrations
        run_migrations(conn)
        from app.db.migrations.sources import ensure_public_url_signature_unique_indexes

        ensure_public_url_signature_unique_indexes(conn)


async def run_db(func):
    """在线程池中执行同步数据库操作，避免阻塞事件循环"""
    return await asyncio.to_thread(func)


# ---------------------------------------------------------------------------
# 向后兼容 re-export（现有 from app.db.connection import xxx 无需改动）
# ---------------------------------------------------------------------------
from app.db.queries import (  # noqa: E402, F401
    get_current_job_position,
    get_user_job_position,
    get_dynamic_frequency_sql,
    get_taxonomy_for_position,
    save_taxonomy_for_position,
    filter_sources_by_mode,
    filter_original_question_sources_by_mode,
)

"""
数据库连接管理 — 线程级 SQLite 连接 + async 桥接

迁移函数已拆分至 db/migrations/ 包
业务查询函数已拆分至 db/queries.py
"""
import sqlite3
import asyncio
import logging
from contextvars import ContextVar

from app.core.config import DB_PATH

logger = logging.getLogger("interview-boss")

# 使用 ContextVar 替代 threading.local，确保 asyncio.to_thread() 能访问连接
_db_conn_var: ContextVar[sqlite3.Connection | None] = ContextVar(
    "_db_conn_var", default=None
)


def get_db_connection():
    """获取当前上下文的数据库连接，避免每次请求重复建立连接和设置 PRAGMA
    
    使用 ContextVar 替代 threading.local，确保 asyncio.to_thread() 
    创建的子线程能访问到主线程设置的连接。
    """
    conn = _db_conn_var.get()
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
    _db_conn_var.set(conn)
    return conn


def prepare_migration_connection(conn):
    """Configure a migration connection before any schema/data operation."""
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库：运行所有迁移"""
    from app.core.config import validate_runtime_secrets

    validate_runtime_secrets()
    with sqlite3.connect(DB_PATH) as conn:
        prepare_migration_connection(conn)
        from app.db.migrations import run_migrations
        run_migrations(conn)
        from app.db.migrations.sources import ensure_public_url_signature_unique_indexes

        ensure_public_url_signature_unique_indexes(conn)
        from app.evaluation.benchmark_catalog import sync_builtin_benchmarks

        sync_builtin_benchmarks(conn)
        conn.commit()


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

import sqlite3
import asyncio
import threading
from app.core.config import DB_PATH

_local = threading.local()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS master_question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT UNIQUE,
                cat1 TEXT,
                cat2 TEXT,
                tags TEXT,
                difficulty TEXT,
                frequency INTEGER DEFAULT 1,
                ai_answer TEXT,
                vector TEXT,
                sources TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(master_question_bank)")
        columns = [info[1] for info in cursor.fetchall()]
        if "vector" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN vector TEXT")
        if "sources" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN sources TEXT DEFAULT '[]'")
        if "is_starred" not in columns:
            conn.execute("ALTER TABLE master_question_bank ADD COLUMN is_starred INTEGER DEFAULT 0")


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


async def run_db(func):
    """在线程池中执行同步数据库操作，避免阻塞事件循环"""
    return await asyncio.to_thread(func)

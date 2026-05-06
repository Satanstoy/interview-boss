import sqlite3
import asyncio
import threading
import logging
from app.core.config import DB_PATH

logger = logging.getLogger("interview-boss")

_local = threading.local()


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # ── 保留旧表兼容 ──
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

        conn.execute('''
            CREATE TABLE IF NOT EXISTS interview (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                company TEXT,
                round TEXT,
                focus TEXT,
                questions_list TEXT,
                difficulty TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute("PRAGMA table_info(interview)")
        interview_cols = [info[1] for info in cursor.fetchall()]
        if "season" not in interview_cols:
            conn.execute("ALTER TABLE interview ADD COLUMN season TEXT DEFAULT ''")

        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_profile (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        for k, v in [("active_season", ""), ("llm_model", ""),
                     ("llm_api_key", ""), ("llm_base_url", ""), ("llm_timeout", "")]:
            conn.execute("INSERT OR IGNORE INTO user_profile (key, value) VALUES (?, ?)", (k, v))

        # seed 默认分类体系（仅首次）
        import json as _json
        from app.core.prompts import DEFAULT_TAXONOMY
        conn.execute(
            "INSERT OR IGNORE INTO user_profile (key, value) VALUES (?, ?)",
            ("taxonomy_config", _json.dumps(DEFAULT_TAXONOMY, ensure_ascii=False))
        )

        conn.execute('''
            CREATE TABLE IF NOT EXISTS practice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                user_answer TEXT,
                evaluation_result TEXT,
                score INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute("PRAGMA index_list('practice_history')")
        indexes = [row[1] for row in cursor.fetchall()]
        if "idx_practice_question" not in indexes:
            conn.execute("CREATE INDEX idx_practice_question ON practice_history(question_id)")

        # ── users 表 ──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                bank_mode TEXT DEFAULT 'public',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── question_bank 表（统一题库，取代 master_question_bank）──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS question_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                cat1 TEXT,
                cat2 TEXT,
                tags TEXT,
                difficulty TEXT,
                frequency INTEGER DEFAULT 1,
                ai_answer TEXT,
                vector TEXT,
                sources TEXT DEFAULT '[]',
                original_questions TEXT DEFAULT '[]',
                original_question_sources TEXT DEFAULT '[]',
                is_starred INTEGER DEFAULT 0,
                owner_id INTEGER,
                submitted_by INTEGER,
                status TEXT DEFAULT 'approved',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (owner_id) REFERENCES users(id),
                FOREIGN KEY (submitted_by) REFERENCES users(id)
            )
        ''')

        # ── user_practice_history 表 ──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_practice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_bank_id INTEGER NOT NULL,
                user_answer TEXT,
                evaluation_result TEXT,
                score INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (question_bank_id) REFERENCES question_bank(id)
            )
        ''')
        cursor.execute("PRAGMA index_list('user_practice_history')")
        uph_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_uph_user" not in uph_indexes:
            conn.execute("CREATE INDEX idx_uph_user ON user_practice_history(user_id)")
        if "idx_uph_question" not in uph_indexes:
            conn.execute("CREATE INDEX idx_uph_question ON user_practice_history(question_bank_id)")

        # ── refresh_tokens 表（用于双 token 机制的服务端校验）──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                jti TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        cursor.execute("PRAGMA index_list('refresh_tokens')")
        rt_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_rt_jti" not in rt_indexes:
            conn.execute("CREATE INDEX idx_rt_jti ON refresh_tokens(jti)")
        if "idx_rt_user" not in rt_indexes:
            conn.execute("CREATE INDEX idx_rt_user ON refresh_tokens(user_id)")

        # ── login_failures 表（持久化登录锁定，替代内存字典）──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS login_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                failure_count INTEGER DEFAULT 0,
                locked_until REAL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── 性能索引 ──
        cursor.execute("PRAGMA index_list('jd')")
        jd_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_jd_url" not in jd_indexes:
            conn.execute("CREATE INDEX idx_jd_url ON jd(url)")

        cursor.execute("PRAGMA index_list('interview')")
        iv_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_interview_url" not in iv_indexes:
            conn.execute("CREATE INDEX idx_interview_url ON interview(url)")

        cursor.execute("PRAGMA index_list('questions_detail')")
        qd_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_qd_url" not in qd_indexes:
            conn.execute("CREATE INDEX idx_qd_url ON questions_detail(url)")

        cursor.execute("PRAGMA index_list('question_bank')")
        qb_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_qb_owner_status" not in qb_indexes:
            conn.execute("CREATE INDEX idx_qb_owner_status ON question_bank(owner_id, status)")

        # 迁移：添加 remember 列（标记是否为 remember-me 登录）
        rt_columns = {row[1] for row in cursor.execute("PRAGMA table_info('refresh_tokens')").fetchall()}
        if "remember" not in rt_columns:
            conn.execute("ALTER TABLE refresh_tokens ADD COLUMN remember INTEGER DEFAULT 0")

        # ── 迁移：添加 original_questions 和 original_question_sources 列 ──
        qb_columns = {row[1] for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()}
        if "original_questions" not in qb_columns:
            conn.execute("ALTER TABLE question_bank ADD COLUMN original_questions TEXT DEFAULT '[]'")
        if "original_question_sources" not in qb_columns:
            conn.execute("ALTER TABLE question_bank ADD COLUMN original_question_sources TEXT DEFAULT '[]'")

        # ── 迁移：清理 embedding 相关数据 ──
        conn.execute("UPDATE question_bank SET vector = NULL WHERE vector IS NOT NULL")
        conn.execute("DELETE FROM user_profile WHERE key IN ('embedding_model', 'similarity_threshold', 'embedding_api_key', 'embedding_base_url')")

        # ── 种子管理员 ──
        from passlib.context import CryptContext
        import os
        pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin_username = os.getenv("ADMIN_USERNAME", "sj")
        admin_password = os.getenv("ADMIN_PASSWORD")
        admin_row = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()
        if not admin_row:
            if not admin_password:
                raise RuntimeError(
                    "首次启动需要设置管理员密码，请在 .env 中配置 ADMIN_PASSWORD 环境变量"
                )
            admin_hash = pwd_ctx.hash(admin_password)
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, 1, 'public')",
                (admin_username, admin_hash)
            )
            logger.info(f"种子管理员账户已创建: {admin_username}")

        # ── 数据迁移: master_question_bank → question_bank ──
        qb_count = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
        if qb_count == 0:
            old_count = conn.execute("SELECT COUNT(*) FROM master_question_bank").fetchone()[0]
            if old_count > 0:
                admin_id = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()[0]
                conn.execute("""
                    INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, ai_answer, vector, sources, is_starred, owner_id, submitted_by, status, created_at, updated_at)
                    SELECT question, cat1, cat2, tags, difficulty, frequency, ai_answer, vector, sources, is_starred, NULL, ?, 'approved', created_at, updated_at
                    FROM master_question_bank
                """, (admin_id,))
                logger.info(f"已迁移 {old_count} 条题目到 question_bank 表")

        # ── 数据迁移: practice_history → user_practice_history ──
        uph_count = conn.execute("SELECT COUNT(*) FROM user_practice_history").fetchone()[0]
        if uph_count == 0:
            ph_count = conn.execute("SELECT COUNT(*) FROM practice_history").fetchone()[0]
            if ph_count > 0:
                admin_id = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()[0]
                # 需要将旧 question_id 映射到新 question_bank id
                # 通过 question 文本匹配
                conn.execute("""
                    INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, evaluation_result, score, created_at)
                    SELECT ?, qb.id, ph.user_answer, ph.evaluation_result, ph.score, ph.created_at
                    FROM practice_history ph
                    JOIN master_question_bank mqb ON ph.question_id = mqb.id
                    JOIN question_bank qb ON qb.question = mqb.question AND qb.owner_id IS NULL
                """, (admin_id,))
                migrated = conn.execute("SELECT changes()").fetchone()[0]
                logger.info(f"已迁移 {migrated} 条练习记录到 user_practice_history 表")

        conn.commit()


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

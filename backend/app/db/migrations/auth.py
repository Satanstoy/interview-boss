"""Auth domain migrations: 003, 010, 012, 015, 052."""

import os
import logging

from passlib.context import CryptContext

logger = logging.getLogger("interview-boss")


def _migration_003_auth_tables(conn):
    """Create refresh_tokens, login_failures, user_llm_config tables."""
    cursor = conn.cursor()

    # ── refresh_tokens 表（用于双 token 机制的服务端校验）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            jti TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    cursor.execute("PRAGMA index_list('refresh_tokens')")
    rt_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_rt_jti" not in rt_indexes:
        conn.execute("CREATE INDEX idx_rt_jti ON refresh_tokens(jti)")
    if "idx_rt_user" not in rt_indexes:
        conn.execute("CREATE INDEX idx_rt_user ON refresh_tokens(user_id)")

    # ── login_failures 表（持久化登录锁定，替代内存字典）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS login_failures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            failure_count INTEGER DEFAULT 0,
            locked_until REAL DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ── user_llm_config 表（per-user LLM 配置，与 .env 解耦）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_llm_config (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            api_key TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT 'gpt-4o',
            timeout INTEGER NOT NULL DEFAULT 120,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _migration_010_users_extra_columns(conn):
    """users table: current_position_id, personal_position, email columns.
    Create email_verification_codes table."""
    cursor = conn.cursor()

    # ── users 表增加 current_position_id 列 ──
    users_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info('users')").fetchall()
    }
    if "current_position_id" not in users_columns:
        conn.execute(
            "ALTER TABLE users ADD COLUMN current_position_id INTEGER REFERENCES job_positions(id)"
        )
    if "personal_position" not in users_columns:
        conn.execute("ALTER TABLE users ADD COLUMN personal_position TEXT")
    if "email" not in users_columns:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT")

    # ── 邮箱验证码表 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS email_verification_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            purpose TEXT NOT NULL,
            user_id INTEGER,
            expires_at TIMESTAMP NOT NULL,
            used INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_codes_email ON email_verification_codes(email, purpose, used)"
    )


def _migration_012_admin_seed(conn):
    """Seed admin user.  Migrate master_question_bank -> question_bank,
    practice_history -> user_practice_history.  Drop old tables."""
    cursor = conn.cursor()

    # ── 种子管理员 ──
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin_username = os.getenv("ADMIN_USERNAME", "sj")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_row = conn.execute(
        "SELECT id FROM users WHERE username = ?", (admin_username,)
    ).fetchone()
    if not admin_row:
        if not admin_password:
            raise RuntimeError(
                "首次启动需要设置管理员密码，请在 .env 中配置 ADMIN_PASSWORD 环境变量"
            )
        admin_hash = pwd_ctx.hash(admin_password)
        conn.execute(
            "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, 1, 'public')",
            (admin_username, admin_hash),
        )
        logger.info(f"种子管理员账户已创建: {admin_username}")

    # ── 数据迁移: master_question_bank → question_bank ──
    qb_count = conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
    if qb_count == 0:
        old_count = conn.execute(
            "SELECT COUNT(*) FROM master_question_bank"
        ).fetchone()[0]
        if old_count > 0:
            admin_id = conn.execute(
                "SELECT id FROM users WHERE username = ?", (admin_username,)
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, ai_answer, vector, sources, is_starred, owner_id, submitted_by, status, created_at, updated_at)
                SELECT question, cat1, cat2, tags, difficulty, frequency, ai_answer, vector, sources, is_starred, NULL, ?, 'approved', created_at, updated_at
                FROM master_question_bank
            """,
                (admin_id,),
            )
            logger.info(f"已迁移 {old_count} 条题目到 question_bank 表")

    # ── 数据迁移: practice_history → user_practice_history ──
    uph_count = conn.execute("SELECT COUNT(*) FROM user_practice_history").fetchone()[0]
    if uph_count == 0:
        ph_count = conn.execute("SELECT COUNT(*) FROM practice_history").fetchone()[0]
        if ph_count > 0:
            admin_id = conn.execute(
                "SELECT id FROM users WHERE username = ?", (admin_username,)
            ).fetchone()[0]
            # 需要将旧 question_id 映射到新 question_bank id
            # 通过 question 文本匹配
            conn.execute(
                """
                INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, evaluation_result, score, created_at)
                SELECT ?, qb.id, ph.user_answer, ph.evaluation_result, ph.score, ph.created_at
                FROM practice_history ph
                JOIN master_question_bank mqb ON ph.question_id = mqb.id
                JOIN question_bank qb ON qb.question = mqb.question AND qb.owner_id IS NULL
            """,
                (admin_id,),
            )
            migrated = conn.execute("SELECT changes()").fetchone()[0]
            logger.info(f"已迁移 {migrated} 条练习记录到 user_practice_history 表")

    # ── 清理遗留旧表（数据已迁移到 question_bank / user_practice_history）──
    conn.execute("DROP TABLE IF EXISTS master_question_bank")
    conn.execute("DROP TABLE IF EXISTS practice_history")


def _migration_015_refresh_tokens_extra(conn):
    """refresh_tokens extra columns (remember, ip_address, user_agent, family_id)
    and invalidated_families table."""
    cursor = conn.cursor()

    # 迁移：添加 remember 列（标记是否为 remember-me 登录）
    rt_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('refresh_tokens')").fetchall()
    }
    if "remember" not in rt_columns:
        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN remember INTEGER DEFAULT 0")
    # Bug #9: refresh_tokens 添加客户端指纹列
    if "ip_address" not in rt_columns:
        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN ip_address TEXT DEFAULT ''")
    if "user_agent" not in rt_columns:
        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN user_agent TEXT DEFAULT ''")
    # Bug #1: refresh_tokens 添加 family_id 列（token 重放检测）
    if "family_id" not in rt_columns:
        conn.execute("ALTER TABLE refresh_tokens ADD COLUMN family_id TEXT")
    cursor.execute("PRAGMA index_list('refresh_tokens')")
    rt_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_rt_family" not in rt_indexes:
        conn.execute("CREATE INDEX idx_rt_family ON refresh_tokens(family_id)")

    # ── invalidated_families 表（记录被撤销的 token family）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invalidated_families (
            family_id TEXT PRIMARY KEY,
            invalidated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def _migration_051_share_default(conn):
    """Add users.share_default column for the share model.

    Replaces the deprecated bank_mode three-state switch. Default is
    'private' (安全优先：防止误分享). Values: 'share' | 'private'.
    """
    cols = {row[1] for row in conn.execute("PRAGMA table_info('users')").fetchall()}
    if "share_default" not in cols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN share_default TEXT DEFAULT 'private'"
        )
    # 存量行显式回填为 private（ALTER 默认值不影响已有行）
    conn.execute(
        "UPDATE users SET share_default = 'private' WHERE share_default IS NULL"
    )
    import logging

    logging.getLogger("interview-boss").info(
        "migration_051: users.share_default 列已就绪"
    )


def _migration_052_mcp_tokens(conn):
    """Create one rotatable opaque MCP token per user.

    The raw token is never persisted.  MCP clients only need the token as a
    bearer credential, so a SHA-256 digest is sufficient for lookup and keeps
    a database leak from immediately exposing every MCP connection.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mcp_tokens (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT UNIQUE NOT NULL,
            token_hint TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            rotated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mcp_tokens_hash ON mcp_tokens(token_hash)"
    )

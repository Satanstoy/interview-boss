import sqlite3
import json
import os
import logging

from app.core.prompts import DEFAULT_TAXONOMY
from passlib.context import CryptContext

logger = logging.getLogger("interview-boss")

# ---------------------------------------------------------------------------
# Migration functions — each is self-contained and idempotent
# ---------------------------------------------------------------------------


def _migration_001_base_tables(conn):
    """Create core tables: master_question_bank, interview, user_profile,
    practice_history, users.  Seed default user_profile values."""
    cursor = conn.cursor()

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
    # ── 迁移：interview 表添加 owner_id 和 status 列（个人/公共管理）──
    interview_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()}
    if "owner_id" not in interview_col_set:
        conn.execute("ALTER TABLE interview ADD COLUMN owner_id INTEGER REFERENCES users(id)")
    if "status" not in interview_col_set:
        conn.execute("ALTER TABLE interview ADD COLUMN status TEXT DEFAULT 'approved'")
    if "job_position" not in interview_col_set:
        conn.execute("ALTER TABLE interview ADD COLUMN job_position TEXT DEFAULT ''")

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
    conn.execute(
        "INSERT OR IGNORE INTO user_profile (key, value) VALUES (?, ?)",
        ("taxonomy_config", json.dumps(DEFAULT_TAXONOMY, ensure_ascii=False))
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
    users_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('users')").fetchall()}
    if "updated_at" not in users_col_set:
        conn.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP")
        conn.execute("UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")


def _migration_002_question_bank(conn):
    """Create question_bank and user_practice_history tables."""
    cursor = conn.cursor()

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
    uph_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('user_practice_history')").fetchall()}
    if "updated_at" not in uph_col_set:
        conn.execute("ALTER TABLE user_practice_history ADD COLUMN updated_at TIMESTAMP")
        conn.execute("UPDATE user_practice_history SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")


def _migration_003_auth_tables(conn):
    """Create refresh_tokens, login_failures, user_llm_config tables."""
    cursor = conn.cursor()

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

    # ── user_llm_config 表（per-user LLM 配置，与 .env 解耦）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_llm_config (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            api_key TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT 'gpt-4o',
            timeout INTEGER NOT NULL DEFAULT 120,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


def _migration_004_jd_interview_qd_columns(conn):
    """Column/index migrations for jd, interview, questions_detail tables."""
    cursor = conn.cursor()

    # ── 迁移：jd 表添加 season 列 ──
    jd_columns = {row[1] for row in cursor.execute("PRAGMA table_info('jd')").fetchall()}
    if "season" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN season TEXT DEFAULT ''")
        conn.execute("UPDATE jd SET season = '2027届暑期实习', updated_at = CURRENT_TIMESTAMP WHERE season IS NULL OR season = ''")
        logger.info("已为 jd 表添加 season 列并回填默认招聘季")
    # ── 迁移：jd 表添加 owner_id 和 status 列（个人/公共管理）──
    if "owner_id" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN owner_id INTEGER REFERENCES users(id)")
    if "status" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN status TEXT DEFAULT 'approved'")

    cursor.execute("PRAGMA index_list('jd')")
    jd_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_jd_url" not in jd_indexes:
        conn.execute("CREATE INDEX idx_jd_url ON jd(url)")
    if "idx_jd_url_unique" not in jd_indexes:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_jd_url_unique ON jd(url, owner_id) WHERE url IS NOT NULL AND url != ''")
    if "idx_jd_owner_status" not in jd_indexes:
        conn.execute("CREATE INDEX idx_jd_owner_status ON jd(owner_id, status)")
    # Bug #11: jd 表添加 url_signature 列用于高效去重
    if "url_signature" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN url_signature TEXT DEFAULT ''")
    if "idx_jd_url_sig" not in jd_indexes:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jd_url_sig ON jd(url_signature)")
    if "updated_at" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN updated_at TIMESTAMP")
        conn.execute("UPDATE jd SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    if "deleted_at" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN deleted_at TIMESTAMP")
    # ── 迁移：jd 表添加 job_position 列（岗位隔离）──
    jd_columns = {row[1] for row in cursor.execute("PRAGMA table_info('jd')").fetchall()}
    if "job_position" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN job_position TEXT DEFAULT ''")
        # 回填已有 JD 记录的 job_position 为当前全局岗位
        try:
            current_pos = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
            if current_pos and current_pos[0]:
                conn.execute("UPDATE jd SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''", (current_pos[0],))
                logger.info(f"已为 jd 表添加 job_position 列并回填为 {current_pos[0]}")
        except Exception:
            pass
    # ── 迁移：修复 interview 表中空 job_position 的历史数据 ──
    empty_pos_count = conn.execute("SELECT COUNT(*) FROM interview WHERE job_position IS NULL OR job_position = ''").fetchone()[0]
    if empty_pos_count > 0:
        try:
            current_pos = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
            if current_pos and current_pos[0]:
                conn.execute("UPDATE interview SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''", (current_pos[0],))
                logger.info(f"已将 {empty_pos_count} 条面经记录的 job_position 回填为 {current_pos[0]}")
        except Exception:
            pass

    cursor.execute("PRAGMA index_list('interview')")
    iv_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_interview_url" not in iv_indexes:
        conn.execute("CREATE INDEX idx_interview_url ON interview(url)")
    if "idx_interview_url_unique" not in iv_indexes:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_url_unique ON interview(url, owner_id) WHERE url IS NOT NULL AND url != ''")
    if "idx_interview_owner_status" not in iv_indexes:
        conn.execute("CREATE INDEX idx_interview_owner_status ON interview(owner_id, status)")
    # Bug #11: interview 表添加 url_signature 列用于高效去重
    iv_columns = {row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()}
    if "url_signature" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN url_signature TEXT DEFAULT ''")
    if "idx_interview_url_sig" not in iv_indexes:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_interview_url_sig ON interview(url_signature)")
    if "updated_at" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN updated_at TIMESTAMP")
        conn.execute("UPDATE interview SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    if "deleted_at" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN deleted_at TIMESTAMP")

    cursor.execute("PRAGMA index_list('questions_detail')")
    qd_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_qd_url" not in qd_indexes:
        conn.execute("CREATE INDEX idx_qd_url ON questions_detail(url)")
    qd_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('questions_detail')").fetchall()}
    if "updated_at" not in qd_col_set:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN updated_at TIMESTAMP")
        conn.execute("UPDATE questions_detail SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
    if "deleted_at" not in qd_col_set:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN deleted_at TIMESTAMP")
    # 刷新列集合
    qd_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('questions_detail')").fetchall()}
    if "job_position" not in qd_col_set:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN job_position TEXT DEFAULT ''")
        # 回填：通过 question_bank 中已有的匹配题目获取 job_position
        # 注意：question_bank.job_position 在 migration 005 才添加，此处需检查
        qb_col_check = {row[1] for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()}
        if "job_position" in qb_col_check:
            conn.execute("""
                UPDATE questions_detail SET job_position = (
                    SELECT qb.job_position FROM question_bank qb
                    WHERE qb.original_questions LIKE '%' || questions_detail.question || '%'
                    AND qb.job_position IS NOT NULL AND qb.job_position != ''
                    LIMIT 1
                ) WHERE job_position IS NULL OR job_position = ''
            """)
        _default_pos = DEFAULT_TAXONOMY["job_position"]
        _pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'taxonomy_config'").fetchone()
        if _pos_row and _pos_row[0]:
            try:
                _tc = json.loads(_pos_row[0])
                _default_pos = _tc.get("job_position", _default_pos)
            except Exception:
                pass
        conn.execute(
            "UPDATE questions_detail SET job_position = ? WHERE job_position IS NULL OR job_position = ''",
            (_default_pos,)
        )
        logger.info(f"已为 questions_detail 表添加 job_position 列并回填为 {_default_pos}")

    cursor.execute("PRAGMA index_list('question_bank')")
    qb_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_qb_owner_status" not in qb_indexes:
        conn.execute("CREATE INDEX idx_qb_owner_status ON question_bank(owner_id, status)")


def _migration_005_question_bank_extra_columns(conn):
    """question_bank extra columns: original_questions, original_question_sources,
    deleted_at, job_position + backfill, question_manually_edited,
    current_job_position initialization.  Also clean invalid positions/categories."""
    cursor = conn.cursor()

    # ── 迁移：添加 original_questions 和 original_question_sources 列 ──
    qb_columns = {row[1] for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()}
    if "original_questions" not in qb_columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN original_questions TEXT DEFAULT '[]'")
    if "original_question_sources" not in qb_columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN original_question_sources TEXT DEFAULT '[]'")

    # ── 迁移：添加 deleted_at 列（软删除支持）──
    qb_columns = {row[1] for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()}
    if "deleted_at" not in qb_columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN deleted_at TIMESTAMP")
        logger.info("已为 question_bank 表添加 deleted_at 列（软删除支持）")

    # ── 清理脏数据：job_positions 表中的无效岗位（表在 migration 006 创建）──
    jp_exists = cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='job_positions'").fetchone()
    if jp_exists:
        invalid_positions = conn.execute(
            "SELECT id, name FROM job_positions WHERE name LIKE '%test%' OR name LIKE '%测试%' OR LENGTH(name) > 30 OR name LIKE '%!@#$%' OR name LIKE '%AAAA%'"
        ).fetchall()
        if invalid_positions:
            for pos in invalid_positions:
                conn.execute("DELETE FROM question_position WHERE position_id = ?", (pos[0],))
                conn.execute("DELETE FROM taxonomy WHERE position_name = ?", (pos[1],))
                conn.execute("DELETE FROM job_positions WHERE id = ?", (pos[0],))
            logger.info(f"已清理 {len(invalid_positions)} 个无效岗位数据")

    # ── 清理脏数据：question_bank 表中的无效分类 ──
    conn.execute("UPDATE question_bank SET cat1 = '' WHERE cat1 = 'test' AND deleted_at IS NULL")
    logger.info("已清理 question_bank 表中的无效分类数据")

    # ── 迁移：添加 job_position 列（多岗位隔离）──
    if "job_position" not in qb_columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN job_position TEXT DEFAULT ''")
        # 回填现有数据为当前岗位
        current_pos = DEFAULT_TAXONOMY["job_position"]
        pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'taxonomy_config'").fetchone()
        if pos_row and pos_row[0]:
            try:
                tc = json.loads(pos_row[0])
                current_pos = tc.get("job_position", current_pos)
            except Exception:
                pass
        conn.execute("UPDATE question_bank SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''", (current_pos,))
        logger.info(f"已为 question_bank 表添加 job_position 列并回填为 {current_pos}")
    cursor.execute("PRAGMA index_list('question_bank')")
    qb_idx = [row[1] for row in cursor.fetchall()]
    if "idx_qb_job_position" not in qb_idx:
        conn.execute("CREATE INDEX idx_qb_job_position ON question_bank(job_position)")

    # ── 迁移：添加 question_manually_edited 标记（防止手动编辑被覆盖）──
    qb_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()}
    if "question_manually_edited" not in qb_col_set:
        conn.execute("ALTER TABLE question_bank ADD COLUMN question_manually_edited INTEGER DEFAULT 0")

    # ── 初始化 current_job_position ──
    pos_exists = conn.execute("SELECT 1 FROM user_profile WHERE key = 'current_job_position'").fetchone()
    if not pos_exists:
        conn.execute(
            "INSERT INTO user_profile (key, value) VALUES (?, ?)",
            ("current_job_position", DEFAULT_TAXONOMY["job_position"])
        )


def _migration_006_job_positions(conn):
    """Create job_positions and question_position tables."""
    cursor = conn.cursor()

    # ── job_positions 表（岗位实体）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    jp_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('job_positions')").fetchall()}
    if "updated_at" not in jp_col_set:
        conn.execute("ALTER TABLE job_positions ADD COLUMN updated_at TIMESTAMP")
        conn.execute("UPDATE job_positions SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

    # ── question_position 关联表（题目-岗位多对多）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_position (
            question_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id),
            FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute("PRAGMA index_list('question_position')")
    qp_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_qp_position" not in qp_indexes:
        conn.execute("CREATE INDEX idx_qp_position ON question_position(position_id)")


def _migration_007_taxonomy(conn):
    """Create taxonomy table + source/owner_id/is_public columns + unique index."""
    cursor = conn.cursor()

    # ── taxonomy 表（岗位分类体系，取代 user_profile 中的 taxonomy_config JSON）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS taxonomy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # 迁移：taxonomy 表增加权限相关字段
    tx_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('taxonomy')").fetchall()}
    if "source" not in tx_col_set:
        conn.execute("ALTER TABLE taxonomy ADD COLUMN source TEXT DEFAULT 'system'")
    if "owner_id" not in tx_col_set:
        conn.execute("ALTER TABLE taxonomy ADD COLUMN owner_id INTEGER DEFAULT NULL")
    if "is_public" not in tx_col_set:
        conn.execute("ALTER TABLE taxonomy ADD COLUMN is_public INTEGER DEFAULT 0")

    # 更新现有数据的 source 字段
    conn.execute("UPDATE taxonomy SET source = 'system' WHERE source IS NULL")

    # 重建唯一索引：允许用户有自己的分类副本
    # 先删除旧索引（如果存在）
    try:
        conn.execute("DROP INDEX IF EXISTS idx_taxonomy_position")
    except Exception:
        pass
    # 创建新的复合唯一索引
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_taxonomy_position_owner
        ON taxonomy(position_name, source, owner_id)
    """)


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


def _migration_009_analysis_queue(conn):
    """Create analysis_queue table + question_detail_id column + indexes."""
    cursor = conn.cursor()

    # ── 两阶段流水线队列表（基本单位：单个问题） ──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            question_detail_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (interview_id) REFERENCES interview(id)
        )
    ''')
    # 迁移：为旧表添加 question_detail_id 列（必须在创建索引之前）
    aq_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('analysis_queue')").fetchall()}
    if "question_detail_id" not in aq_col_set:
        conn.execute("ALTER TABLE analysis_queue ADD COLUMN question_detail_id INTEGER")
    cursor.execute("PRAGMA index_list('analysis_queue')")
    aq_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_aq_status" not in aq_indexes:
        conn.execute("CREATE INDEX idx_aq_status ON analysis_queue(status)")
    if "idx_aq_interview" not in aq_indexes:
        conn.execute("CREATE INDEX idx_aq_interview ON analysis_queue(interview_id)")
    if "idx_aq_question_detail" not in aq_indexes:
        conn.execute("CREATE INDEX idx_aq_question_detail ON analysis_queue(question_detail_id)")


def _migration_010_users_extra_columns(conn):
    """users table: current_position_id, personal_position, email columns.
    Create email_verification_codes table."""
    cursor = conn.cursor()

    # ── users 表增加 current_position_id 列 ──
    users_columns = {row[1] for row in cursor.execute("PRAGMA table_info('users')").fetchall()}
    if "current_position_id" not in users_columns:
        conn.execute("ALTER TABLE users ADD COLUMN current_position_id INTEGER REFERENCES job_positions(id)")
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_codes_email ON email_verification_codes(email, purpose, used)")


def _migration_011_data_backfills(conn):
    """Data backfills: question_bank.job_position -> job_positions + question_position,
    user_profile.current_job_position -> users.current_position_id,
    embedding cleanup, empty season backfill,
    taxonomy from user_profile JSON -> taxonomy table."""
    cursor = conn.cursor()

    # ── 数据迁移：question_bank.job_position → job_positions + question_position ──
    jp_count = conn.execute("SELECT COUNT(*) FROM job_positions").fetchone()[0]
    if jp_count == 0:
        # 从 question_bank 提取所有不重复的岗位
        positions = conn.execute(
            "SELECT DISTINCT job_position FROM question_bank WHERE job_position IS NOT NULL AND job_position != ''"
        ).fetchall()
        for row in positions:
            pos_name = row[0]
            conn.execute("INSERT OR IGNORE INTO job_positions (name) VALUES (?)", (pos_name,))
            pos_id = conn.execute("SELECT id FROM job_positions WHERE name = ?", (pos_name,)).fetchone()[0]
            # 为属于该岗位的所有题目建立关联
            conn.execute(
                "INSERT OR IGNORE INTO question_position (question_id, position_id) "
                "SELECT id, ? FROM question_bank WHERE job_position = ?", (pos_id, pos_name)
            )
        migrated_count = conn.execute("SELECT COUNT(*) FROM question_position").fetchone()[0]
        logger.info(f"已迁移 {len(positions)} 个岗位、{migrated_count} 条题目-岗位关联到 job_positions/question_position 表")

    # ── 迁移：user_profile.current_job_position → users.current_position_id ──
    users_without_pos = conn.execute("SELECT id FROM users WHERE current_position_id IS NULL").fetchall()
    if users_without_pos:
        cur_pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
        if cur_pos_row and cur_pos_row[0]:
            pos_id_row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (cur_pos_row[0],)).fetchone()
            if pos_id_row:
                conn.execute("UPDATE users SET current_position_id = ?, updated_at = CURRENT_TIMESTAMP WHERE current_position_id IS NULL", (pos_id_row[0],))
                logger.info(f"已将 {len(users_without_pos)} 个用户的 current_position_id 迁移为 {cur_pos_row[0]}")

    # ── 迁移：清理 embedding 相关数据 ──
    conn.execute("UPDATE question_bank SET vector = NULL, updated_at = CURRENT_TIMESTAMP WHERE vector IS NOT NULL")
    conn.execute("DELETE FROM user_profile WHERE key IN ('embedding_model', 'similarity_threshold', 'embedding_api_key', 'embedding_base_url')")

    # ── 迁移：回填空 season 为默认招聘季 ──
    empty_season_count = conn.execute("SELECT COUNT(*) FROM interview WHERE season IS NULL OR season = ''").fetchone()[0]
    if empty_season_count > 0:
        conn.execute("UPDATE interview SET season = '2027届暑期实习', updated_at = CURRENT_TIMESTAMP WHERE season IS NULL OR season = ''")
        logger.info(f"已将 {empty_season_count} 条面经的招聘季回填为 2027届暑期实习")
        # 同步设置 active_season
        conn.execute(
            "INSERT INTO user_profile (key, value, updated_at) VALUES ('active_season', '2027届暑期实习', CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP"
        )

    # ── 迁移：taxonomy 从 user_profile JSON → taxonomy 表 ──
    tx_count = conn.execute("SELECT COUNT(*) FROM taxonomy").fetchone()[0]
    if tx_count == 0:
        # seed 默认 taxonomy
        conn.execute(
            "INSERT OR IGNORE INTO taxonomy (position_name, categories_json, is_default) VALUES (?, ?, 1)",
            (DEFAULT_TAXONOMY["job_position"], json.dumps(DEFAULT_TAXONOMY["categories"], ensure_ascii=False))
        )
        # 从 user_profile 迁移已有的 taxonomy 配置
        tx_rows = conn.execute("SELECT key, value FROM user_profile WHERE key LIKE 'taxonomy_config%'").fetchall()
        for tx_row in tx_rows:
            try:
                tc = json.loads(tx_row['value'])
                pos = tc.get('job_position', '')
                cats = tc.get('categories', [])
                if pos and cats:
                    conn.execute(
                        "INSERT OR REPLACE INTO taxonomy (position_name, categories_json) VALUES (?, ?)",
                        (pos, json.dumps(cats, ensure_ascii=False))
                    )
            except Exception:
                pass
        migrated_tx = conn.execute("SELECT COUNT(*) FROM taxonomy").fetchone()[0]
        logger.info(f"已迁移 {migrated_tx} 个岗位的 taxonomy 配置到 taxonomy 表")


def _migration_012_admin_seed(conn):
    """Seed admin user.  Migrate master_question_bank -> question_bank,
    practice_history -> user_practice_history.  Drop old tables."""
    cursor = conn.cursor()

    # ── 种子管理员 ──
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

    # ── 清理遗留旧表（数据已迁移到 question_bank / user_practice_history）──
    conn.execute("DROP TABLE IF EXISTS master_question_bank")
    conn.execute("DROP TABLE IF EXISTS practice_history")


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


def _migration_014_data_repairs(conn):
    """Data repairs: frequency vs original_questions, original_question_sources
    orphan URL fix, empty OQS backfill, empty sources sub-arrays fix,
    missing URL entries fix, analysis_status columns."""
    cursor = conn.cursor()

    # ── 修复: question_bank.frequency 应等于 original_questions 数组长度 ──
    _fix_rows = conn.execute("SELECT id, frequency, original_questions FROM question_bank").fetchall()
    _fix_count = 0
    for _r in _fix_rows:
        _qb_id, _freq, _oqs_raw = _r[0], _r[1], _r[2]
        try:
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            _oqs = []
        _actual = len(_oqs) if _oqs else _freq
        if _freq != _actual and _actual > 0:
            conn.execute("UPDATE question_bank SET frequency = ? WHERE id = ?", (_actual, _qb_id))
            _fix_count += 1
    if _fix_count > 0:
        logger.info(f"已修复 {_fix_count} 条 question_bank 记录的 frequency 字段（基于 original_questions 计数）")

    # ── 修复: original_question_sources 中包含 sources 中不存在的 URL ──
    _oqs_rows = conn.execute("SELECT id, sources, original_question_sources FROM question_bank WHERE original_question_sources != '[]' AND original_question_sources IS NOT NULL").fetchall()
    _oqs_fix = 0
    for _r in _oqs_rows:
        _qb_id, _src_raw, _oqs_raw = _r[0], _r[1], _r[2]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            continue
        _src_urls = {s.get('url') for s in _srcs if s.get('url')}
        _changed = False
        for _item in _oqs:
            _before = len(_item.get('sources', []))
            _item['sources'] = [s for s in _item.get('sources', []) if s.get('url') in _src_urls]
            if len(_item['sources']) != _before:
                _changed = True
        if _changed:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_oqs, ensure_ascii=False), _qb_id))
            _oqs_fix += 1
    if _oqs_fix > 0:
        logger.info(f"已修复 {_oqs_fix} 条 original_question_sources 中的孤立 URL")

    # ── 修复: original_question_sources 为空但 sources 非空的题目 ──
    _empty_oqs_rows = conn.execute(
        "SELECT id, question, sources FROM question_bank "
        "WHERE (original_question_sources IS NULL OR original_question_sources = '' OR original_question_sources = '[]') "
        "AND sources IS NOT NULL AND sources != '' AND sources != '[]' AND frequency > 0"
    ).fetchall()
    _backfill_count = 0
    # 预加载 questions_detail 的 url -> question 映射
    _qd_map = {}  # url -> [(question, company, round), ...]
    for _qd in conn.execute("SELECT question, url, company, round FROM questions_detail WHERE deleted_at IS NULL AND url IS NOT NULL AND url != ''"):
        _qd_map.setdefault(_qd[1], []).append((_qd[0], _qd[2], _qd[3]))
    for _r in _empty_oqs_rows:
        _qb_id, _qb_question, _src_raw = _r[0], _r[1], _r[2]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
        except Exception:
            continue
        _new_oqs = []
        for _s in _srcs:
            _url = _s.get('url', '')
            _company = _s.get('company', '')
            _round = _s.get('round', '')
            # 尝试从 questions_detail 找到原始题目文本
            _oq_text = _qb_question  # fallback
            if _url in _qd_map:
                for _qd_q, _qd_c, _qd_r in _qd_map[_url]:
                    if _qd_q and _qd_q != _qb_question:
                        _oq_text = _qd_q
                        break
            _new_oqs.append({"question": _oq_text, "sources": [{"url": _url, "company": _company, "round": _round}]})
        if _new_oqs:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_new_oqs, ensure_ascii=False), _qb_id))
            _backfill_count += 1
    if _backfill_count > 0:
        logger.info(f"已回填 {_backfill_count} 条题目的 original_question_sources")

    # ── 修复: original_question_sources 中 sources 为空数组的条目 ──
    _empty_src_oqs_rows = conn.execute(
        "SELECT id, sources, original_question_sources FROM question_bank "
        "WHERE original_question_sources LIKE '%\"sources\": []%' AND frequency > 0"
    ).fetchall()
    _fix_empty_src = 0
    for _r in _empty_src_oqs_rows:
        _qb_id, _src_raw, _oqs_raw = _r[0], _r[1], _r[2]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            continue
        _src_urls = {s.get('url') for s in _srcs if s.get('url')}
        _changed = False
        for _item in _oqs:
            if _item.get('sources'):
                continue  # 已有 sources，跳过
            _oq_text = _item.get('question', '')
            if not _oq_text:
                continue
            # 从 questions_detail 查找匹配的 URL
            for _url in _src_urls:
                if _url in _qd_map:
                    for _qd_q, _qd_c, _qd_r in _qd_map[_url]:
                        if _qd_q == _oq_text:
                            _item['sources'] = [{"url": _url, "company": _qd_c or '', "round": _qd_r or ''}]
                            _changed = True
                            break
                if _changed:
                    break
            # 仍然没有 sources 的条目，使用第一个 source URL 作为 fallback
            if not _item.get('sources') and _srcs:
                _s = _srcs[0]
                _item['sources'] = [{"url": _s.get('url', ''), "company": _s.get('company', ''), "round": _s.get('round', '')}]
                _changed = True
        if _changed:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_oqs, ensure_ascii=False), _qb_id))
            _fix_empty_src += 1
    if _fix_empty_src > 0:
        logger.info(f"已修复 {_fix_empty_src} 条 original_question_sources 中空 sources 条目")

    # ── 修复: sources 中有 URL 但 oqs 中缺失对应条目的题目 ──
    _gap_rows = conn.execute(
        "SELECT id, question, sources, original_question_sources FROM question_bank "
        "WHERE original_question_sources IS NOT NULL AND original_question_sources != '' AND original_question_sources != '[]' "
        "AND sources IS NOT NULL AND sources != '' AND sources != '[]' AND frequency > 0"
    ).fetchall()
    _gap_fix = 0
    for _r in _gap_rows:
        _qb_id, _qb_question, _src_raw, _oqs_raw = _r[0], _r[1], _r[2], _r[3]
        try:
            _srcs = json.loads(_src_raw) if _src_raw else []
            _oqs = json.loads(_oqs_raw) if _oqs_raw else []
        except Exception:
            continue
        _oqs_urls = {s.get('url') for item in _oqs for s in item.get('sources', []) if s.get('url')}
        _changed = False
        for _s in _srcs:
            _url = _s.get('url', '')
            if _url and _url not in _oqs_urls:
                # 从 questions_detail 查找原始题目文本
                _oq_text = _qb_question
                if _url in _qd_map:
                    for _qd_q, _qd_c, _qd_r in _qd_map[_url]:
                        if _qd_q and _qd_q != _qb_question:
                            _oq_text = _qd_q
                            break
                _oqs.append({"question": _oq_text, "sources": [{"url": _url, "company": _s.get('company', ''), "round": _s.get('round', '')}]})
                _oqs_urls.add(_url)
                _changed = True
        if _changed:
            conn.execute("UPDATE question_bank SET original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                         (json.dumps(_oqs, ensure_ascii=False), _qb_id))
            _gap_fix += 1
    if _gap_fix > 0:
        logger.info(f"已修复 {_gap_fix} 条 original_question_sources 中缺失的 URL 条目")

    # ── 迁移：interview 表添加分析状态追踪列（断点续传）──
    iv_columns = {row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()}
    if "analysis_status" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_status TEXT DEFAULT 'idle'")
    if "analysis_stage" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_stage TEXT")
    if "analysis_result" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_result TEXT")
    if "analysis_updated_at" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN analysis_updated_at TIMESTAMP")


def _migration_015_refresh_tokens_extra(conn):
    """refresh_tokens extra columns (remember, ip_address, user_agent, family_id)
    and invalidated_families table."""
    cursor = conn.cursor()

    # 迁移：添加 remember 列（标记是否为 remember-me 登录）
    rt_columns = {row[1] for row in cursor.execute("PRAGMA table_info('refresh_tokens')").fetchall()}
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
    conn.execute('''
        CREATE TABLE IF NOT EXISTS invalidated_families (
            family_id TEXT PRIMARY KEY,
            invalidated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------

def _migration_016_normalized_source_tables(conn):
    """Create normalized tables to replace JSON TEXT columns in question_bank."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_bank_id, url)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qs_qb ON question_sources(question_bank_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qs_url ON question_sources(url)")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_original_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_bank_id, question_text)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qoi_qb ON question_original_items(question_bank_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qoi_text ON question_original_items(question_text)")

    conn.execute('''
        CREATE TABLE IF NOT EXISTS question_original_item_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_item_id INTEGER NOT NULL REFERENCES question_original_items(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(original_item_id, url)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qois_oi ON question_original_item_sources(original_item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qois_url ON question_original_item_sources(url)")


def _migration_017_backfill_normalized_sources(conn):
    """Backfill normalized tables from existing JSON columns in question_bank."""
    cursor = conn.cursor()
    count = cursor.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0]
    if count > 0:
        logger.info("Normalized tables already populated, skipping backfill")
        return

    rows = cursor.execute(
        "SELECT id, sources, original_questions, original_question_sources FROM question_bank"
    ).fetchall()

    for row in rows:
        qb_id = row[0]

        # Backfill question_sources
        try:
            sources = json.loads(row[1]) if row[1] else []
        except Exception:
            sources = []
        for s in sources:
            if isinstance(s, dict):
                cursor.execute(
                    "INSERT OR IGNORE INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, ?, ?)",
                    (qb_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                )

        # Backfill question_original_items + question_original_item_sources
        try:
            oqs_src = json.loads(row[3]) if row[3] else []
        except Exception:
            oqs_src = []
        if not isinstance(oqs_src, list):
            continue

        for item in oqs_src:
            if not isinstance(item, dict):
                continue
            q_text = item.get('question', '')
            if not q_text:
                continue
            cursor.execute(
                "INSERT OR IGNORE INTO question_original_items (question_bank_id, question_text) VALUES (?, ?)",
                (qb_id, q_text)
            )
            item_id = cursor.execute(
                "SELECT id FROM question_original_items WHERE question_bank_id = ? AND question_text = ?",
                (qb_id, q_text)
            ).fetchone()[0]

            for s in item.get('sources', []):
                if isinstance(s, dict):
                    cursor.execute(
                        "INSERT OR IGNORE INTO question_original_item_sources (original_item_id, url, company, round) VALUES (?, ?, ?, ?)",
                        (item_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                    )

    qs_count = cursor.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0]
    qoi_count = cursor.execute("SELECT COUNT(*) FROM question_original_items").fetchone()[0]
    qois_count = cursor.execute("SELECT COUNT(*) FROM question_original_item_sources").fetchone()[0]
    logger.info(f"Backfilled normalized tables: {qs_count} sources, {qoi_count} original items, {qois_count} item sources from {len(rows)} QB records")


def _migration_018_composite_indexes(conn):
    """Add composite indexes for common query patterns."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_owner_status_position ON question_bank(owner_id, status, job_position)")


def _migration_019_fix_cascades(conn):
    """Fix missing ON DELETE CASCADE on user_practice_history.question_bank_id."""
    cursor = conn.cursor()
    # SQLite doesn't support ALTER TABLE to modify FK constraints.
    # Recreate the table with CASCADE.
    cursor.execute("ALTER TABLE user_practice_history RENAME TO user_practice_history_old")
    cursor.execute('''
        CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('''
        INSERT INTO user_practice_history (id, user_id, question_bank_id, user_answer, evaluation_result, score, created_at, updated_at)
        SELECT id, user_id, question_bank_id, user_answer, evaluation_result, score, created_at, updated_at
        FROM user_practice_history_old
    ''')
    cursor.execute("DROP TABLE user_practice_history_old")
    # Recreate indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_uph_user ON user_practice_history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_uph_question ON user_practice_history(question_bank_id)")


def _migration_020_drop_json_columns(conn):
    """Drop deprecated JSON TEXT columns and static frequency from question_bank.

    WARNING: Only run after all write paths have been updated to use normalized tables.
    Currently commented out in _MIGRATIONS — enable after production validation.
    """
    cursor = conn.cursor()
    # Safety check: ensure normalized tables are populated
    qs_count = cursor.execute("SELECT COUNT(*) FROM question_sources").fetchone()[0]
    qb_count = cursor.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]
    if qs_count == 0 and qb_count > 0:
        raise RuntimeError("Cannot drop JSON columns: normalized tables are empty")

    cursor.execute("ALTER TABLE question_bank DROP COLUMN sources")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN original_questions")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN original_question_sources")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN is_starred")
    cursor.execute("ALTER TABLE question_bank DROP COLUMN frequency")
    logger.info("Dropped JSON columns and static frequency from question_bank")


def _migration_021_performance_indexes(conn):
    """Add indexes for common query patterns identified in performance audit."""
    # question_bank: composite index for bank_mode filtering
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_deleted_owner_status ON question_bank(deleted_at, owner_id, status)")
    # questions_detail: index on question text for delete/edit operations
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qd_question ON questions_detail(question)")
    # user_practice_history: composite index for daily trend queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_uph_user_date ON user_practice_history(user_id, created_at)")
    # analysis_queue: index for dequeue operations
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_status_created ON analysis_queue(status, created_at)")


def _migration_022_jobs_table(conn):
    """Add jobs table for tracking async background tasks."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            progress_current INTEGER DEFAULT 0,
            progress_total INTEGER DEFAULT 0,
            progress_message TEXT DEFAULT '',
            result TEXT,
            error TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")


def _migration_023_duplicate_of(conn):
    """Add duplicate_of column to question_bank for cross-bank dedup."""
    conn.execute("ALTER TABLE question_bank ADD COLUMN duplicate_of INTEGER DEFAULT NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_duplicate_of ON question_bank(duplicate_of)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(job_type)")


def _migration_024_chat_tables(conn):
    """Create chat_conversations, chat_messages, chat_memories tables for interview chatbot."""
    cursor = conn.cursor()

    # ── chat_conversations（对话会话表）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            title TEXT,
            jd_id INTEGER,
            resume_text TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute("PRAGMA index_list('chat_conversations')")
    cc_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_cc_user_status" not in cc_indexes:
        conn.execute("CREATE INDEX idx_cc_user_status ON chat_conversations(user_id, status)")
    if "idx_cc_updated" not in cc_indexes:
        conn.execute("CREATE INDEX idx_cc_updated ON chat_conversations(updated_at)")

    # ── chat_messages（消息表）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            token_count INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute("PRAGMA index_list('chat_messages')")
    cm_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_cm_conversation" not in cm_indexes:
        conn.execute("CREATE INDEX idx_cm_conversation ON chat_messages(conversation_id, created_at)")

    # ── chat_memories（用户长期记忆表）──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'auto_extract',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')
    cursor.execute("PRAGMA index_list('chat_memories')")
    cmem_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_cmem_user_active" not in cmem_indexes:
        conn.execute("CREATE INDEX idx_cmem_user_active ON chat_memories(user_id, is_active)")

    logger.info("已创建 chat_conversations, chat_messages, chat_memories 表")


def _migration_025_question_fts(conn):
    """Create FTS5 virtual table for question bank full-text search."""
    cursor = conn.cursor()

    # 检查 FTS5 表是否已存在
    existing = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='question_fts'"
    ).fetchone()
    if existing:
        logger.info("question_fts 表已存在，跳过创建")
        return

    # 创建 FTS5 虚拟表（content sync 模式，自动与 question_bank 同步不可靠，手动管理）
    conn.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS question_fts USING fts5(
            question,
            cat1,
            cat2,
            tags,
            ai_answer,
            tokenize='unicode61'
        )
    ''')

    logger.info("已创建 question_fts FTS5 虚拟表")


def _migration_026_populate_fts(conn):
    """Populate question_fts with existing question_bank data."""
    cursor = conn.cursor()

    # 检查 FTS 表是否有数据
    fts_count = cursor.execute("SELECT COUNT(*) FROM question_fts").fetchone()[0]
    if fts_count > 0:
        logger.info(f"question_fts 已有 {fts_count} 条记录，跳过填充")
        return

    # 从 question_bank 填充
    rows = cursor.execute(
        "SELECT id, question, cat1, cat2, tags, ai_answer "
        "FROM question_bank WHERE deleted_at IS NULL AND status = 'approved'"
    ).fetchall()

    for row in rows:
        # FTS5 的 rowid 与 question_bank.id 对应
        conn.execute(
            "INSERT INTO question_fts(rowid, question, cat1, cat2, tags, ai_answer) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (row[0], row[1] or '', row[2] or '', row[3] or '', row[4] or '', row[5] or '')
        )

    logger.info(f"已填充 question_fts：{len(rows)} 条题目")


def _migration_027_memory_summary(conn):
    """Add summary column to chat_memories for lightweight prompt injection."""
    cursor = conn.cursor()
    col_set = {row[1] for row in cursor.execute("PRAGMA table_info('chat_memories')").fetchall()}
    if "summary" not in col_set:
        conn.execute("ALTER TABLE chat_memories ADD COLUMN summary TEXT DEFAULT ''")
    # Backfill existing records
    conn.execute(
        "UPDATE chat_memories SET summary = SUBSTR(content, 1, 80) "
        "|| CASE WHEN LENGTH(content) > 80 THEN '...' ELSE '' END "
        "WHERE summary IS NULL OR summary = ''"
    )
    logger.info("已添加 chat_memories.summary 列并回填数据")


def _migration_028_session_notes(conn):
    """Add session_notes column to chat_conversations for incremental context."""
    cursor = conn.cursor()
    col_set = {row[1] for row in cursor.execute("PRAGMA table_info('chat_conversations')").fetchall()}
    if "session_notes" not in col_set:
        conn.execute("ALTER TABLE chat_conversations ADD COLUMN session_notes TEXT DEFAULT ''")
    logger.info("已添加 chat_conversations.session_notes 列")


def _migration_029_user_resumes(conn):
    """Create user_resumes table for persistent resume storage."""
    cursor = conn.cursor()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute("PRAGMA index_list('user_resumes')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_resume_user" not in indexes:
        conn.execute("CREATE INDEX idx_resume_user ON user_resumes(user_id)")
    logger.info("已创建 user_resumes 表")


def _migration_030_coding_module(conn):
    """Create coding_problems and coding_submissions tables for the hand-tear code module."""
    cursor = conn.cursor()

    # ── coding_problems ──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS coding_problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'medium',
            tags TEXT DEFAULT '[]',
            expected_complexity TEXT DEFAULT '',
            source TEXT DEFAULT '',
            supported_languages TEXT DEFAULT '["python","c","java"]',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # ── coding_submissions ──
    conn.execute('''
        CREATE TABLE IF NOT EXISTS coding_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            problem_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            code TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'full_review',
            hint_round INTEGER DEFAULT 0,
            parent_submission_id INTEGER,
            ai_feedback TEXT DEFAULT '',
            error_categories TEXT DEFAULT '[]',
            is_passed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (problem_id) REFERENCES coding_problems(id),
            FOREIGN KEY (parent_submission_id) REFERENCES coding_submissions(id)
        )
    ''')

    # Indexes
    cursor.execute("PRAGMA index_list('coding_submissions')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_coding_sub_user" not in indexes:
        conn.execute("CREATE INDEX idx_coding_sub_user ON coding_submissions(user_id)")
    if "idx_coding_sub_problem" not in indexes:
        conn.execute("CREATE INDEX idx_coding_sub_problem ON coding_submissions(problem_id)")
    if "idx_coding_sub_parent" not in indexes:
        conn.execute("CREATE INDEX idx_coding_sub_parent ON coding_submissions(parent_submission_id)")

    # ── Seed 50 high-frequency interview coding problems ──
    problems = [
        # 数组/字符串
        ("两数之和", "给定一个整数数组 `nums` 和一个整数目标值 `target`，请你在该数组中找出和为目标值的两个整数，并返回它们的数组下标。\n\n**示例：**\n```\n输入：nums = [2,7,11,15], target = 9\n输出：[0,1]\n解释：因为 nums[0] + nums[1] == 9\n```", "easy", '["数组","哈希表"]', "O(n)", "LeetCode #1"),
        ("三数之和", "给你一个整数数组 `nums`，判断是否存在三元组 `[nums[i], nums[j], nums[k]]` 满足 `i != j != k` 且 `nums[i] + nums[j] + nums[k] == 0`。返回所有和为 0 的三元组。\n\n**示例：**\n```\n输入：nums = [-1,0,1,2,-1,-4]\n输出：[[-1,-1,2],[-1,0,1]]\n```", "medium", '["数组","双指针","排序"]', "O(n²)", "LeetCode #15"),
        ("盛最多水的容器", "给定一个长度为 n 的整数数组 `height`，其中 `height[i]` 表示第 i 条线的高度。找出其中的两条线，使得它们与 x 轴共同构成的容器可以容纳最多的水。返回最大面积。\n\n**示例：**\n```\n输入：height = [1,8,6,2,5,4,8,3,7]\n输出：49\n```", "medium", '["数组","双指针"]', "O(n)", "LeetCode #11"),
        ("无重复字符的最长子串", "给定一个字符串 `s`，请你找出其中不含有重复字符的最长子串的长度。\n\n**示例：**\n```\n输入：s = \"abcabcbb\"\n输出：3\n解释：最长子串为 \"abc\"\n```", "medium", '["字符串","滑动窗口"]', "O(n)", "LeetCode #3"),
        ("最长回文子串", "给你一个字符串 `s`，找到 `s` 中最长的回文子串。\n\n**示例：**\n```\n输入：s = \"babad\"\n输出：\"bab\" 或 \"aba\"\n```", "medium", '["字符串","动态规划"]', "O(n²)", "LeetCode #5"),
        ("合并两个有序数组", "给你两个按非递减顺序排列的整数数组 `nums1` 和 `nums2`，以及两个整数 `m` 和 `n`，分别表示 `nums1` 和 `nums2` 中的元素数量。将 `nums2` 合并到 `nums1` 中，使合并后的数组按非递减顺序排列。\n\n**示例：**\n```\n输入：nums1 = [1,2,3,0,0,0], m = 3, nums2 = [2,5,6], n = 3\n输出：[1,2,2,3,5,6]\n```", "easy", '["数组","双指针"]', "O(m+n)", "LeetCode #88"),
        ("寻找两个正序数组的中位数", "给定两个大小分别为 m 和 n 的正序数组 `nums1` 和 `nums2`，请你找出并返回这两个正序数组的中位数。算法的时间复杂度应该为 O(log(m+n))。\n\n**示例：**\n```\n输入：nums1 = [1,3], nums2 = [2]\n输出：2.0\n```", "hard", '["数组","二分查找"]', "O(log(m+n))", "LeetCode #4"),
        ("接雨水", "给定 n 个非负整数表示每个宽度为 1 的柱子的高度图，计算按此排列的柱子，下雨之后能接多少雨水。\n\n**示例：**\n```\n输入：height = [0,1,0,2,1,0,1,3,2,1,2,1]\n输出：6\n```", "hard", '["数组","双指针","栈"]', "O(n)", "LeetCode #42"),
        # 链表
        ("反转链表", "给你单链表的头节点 `head`，请你反转链表，并返回反转后的链表。\n\n**示例：**\n```\n输入：head = [1,2,3,4,5]\n输出：[5,4,3,2,1]\n```", "easy", '["链表"]', "O(n)", "LeetCode #206"),
        ("合并两个有序链表", "将两个升序链表合并为一个新的升序链表并返回。新链表是通过拼接给定的两个链表的所有节点组成的。\n\n**示例：**\n```\n输入：l1 = [1,2,4], l2 = [1,3,4]\n输出：[1,1,2,3,4,4]\n```", "easy", '["链表"]', "O(n+m)", "LeetCode #21"),
        ("环形链表", "给你一个链表的头节点 `head`，判断链表中是否有环。如果链表中存在环，则返回 true；否则返回 false。\n\n**示例：**\n```\n输入：head = [3,2,0,-4]（pos = 1，表示尾部连接到第二个节点）\n输出：true\n```", "easy", '["链表","双指针"]', "O(n)", "LeetCode #141"),
        ("相交链表", "给你两个单链表的头节点 `headA` 和 `headB`，请你找出并返回两个单链表相交的起始节点。如果不存在则返回 null。\n\n**示例：**\n```\n输入：intersectVal = 8, listA = [4,1,8,4,5], listB = [5,6,1,8,4,5]\n输出：节点值为 8 的节点\n```", "easy", '["链表","双指针"]', "O(m+n)", "LeetCode #160"),
        ("删除链表的倒数第 N 个结点", "给你一个链表，删除链表的倒数第 n 个结点，并且返回链表的头结点。\n\n**示例：**\n```\n输入：head = [1,2,3,4,5], n = 2\n输出：[1,2,3,5]\n```", "medium", '["链表","双指针"]', "O(L)", "LeetCode #19"),
        ("K 个一组翻转链表", "给你一个链表，每 k 个节点一组进行翻转，请你返回修改后的链表。如果节点总数不是 k 的整数倍，则最后剩余的节点保持原有顺序。\n\n**示例：**\n```\n输入：head = [1,2,3,4,5], k = 2\n输出：[2,1,4,3,5]\n```", "hard", '["链表","递归"]', "O(n)", "LeetCode #25"),
        # 树
        ("二叉树的中序遍历", "给定一个二叉树的根节点 `root`，返回它的中序遍历结果。\n\n**示例：**\n```\n输入：root = [1,null,2,3]\n输出：[1,3,2]\n```", "easy", '["树","栈","递归"]', "O(n)", "LeetCode #94"),
        ("二叉树的最大深度", "给定一个二叉树 `root`，返回其最大深度。最大深度是从根节点到最远叶子节点的最长路径上的节点数。\n\n**示例：**\n```\n输入：root = [3,9,20,null,null,15,7]\n输出：3\n```", "easy", '["树","DFS","BFS"]', "O(n)", "LeetCode #104"),
        ("翻转二叉树", "给你一棵二叉树的根节点 `root`，翻转这棵二叉树，并返回其根节点。\n\n**示例：**\n```\n输入：root = [4,2,7,1,3,6,9]\n输出：[4,7,2,9,6,3,1]\n```", "easy", '["树","递归"]', "O(n)", "LeetCode #226"),
        ("验证二叉搜索树", "给你一个二叉树的根节点 `root`，判断其是否是一个有效的二叉搜索树（BST）。\n\n**示例：**\n```\n输入：root = [2,1,3]\n输出：true\n```", "medium", '["树","BST","递归"]', "O(n)", "LeetCode #98"),
        ("二叉树的层序遍历", "给你二叉树的根节点 `root`，返回其节点值的层序遍历（逐层，从左到右）。\n\n**示例：**\n```\n输入：root = [3,9,20,null,null,15,7]\n输出：[[3],[9,20],[15,7]]\n```", "medium", '["树","BFS"]', "O(n)", "LeetCode #102"),
        ("从前序与中序遍历序列构造二叉树", "给定两个整数数组 `preorder` 和 `inorder`，其中 `preorder` 是二叉树的前序遍历，`inorder` 是同一棵树的中序遍历，请构造二叉树并返回其根节点。\n\n**示例：**\n```\n输入：preorder = [3,9,20,15,7], inorder = [9,3,15,20,7]\n输出：[3,9,20,null,null,15,7]\n```", "medium", '["树","递归","分治"]', "O(n)", "LeetCode #105"),
        ("二叉树的最近公共祖先", "给定一个二叉树, 找到该树中两个指定节点的最近公共祖先（LCA）。\n\n**示例：**\n```\n输入：root = [3,5,1,6,2,0,8,null,null,7,4], p = 5, q = 1\n输出：3\n```", "medium", '["树","递归"]', "O(n)", "LeetCode #236"),
        ("二叉树中的最大路径和", "给你一个二叉树的根节点 `root`，返回其最大路径和。路径被定义为一条从树中任意节点出发，沿父节点-子节点连接，达到任意节点的序列。\n\n**示例：**\n```\n输入：root = [-10,9,20,null,null,15,7]\n输出：42（15→20→7）\n```", "hard", '["树","DFS","递归"]', "O(n)", "LeetCode #124"),
        # 排序与搜索
        ("快速排序", "实现快速排序算法。给定一个整数数组 `nums`，将数组升序排列。\n\n**要求：**\n- 实现 `partition` 过程\n- 平均时间复杂度 O(nlogn)\n\n**示例：**\n```\n输入：nums = [5,2,3,1]\n输出：[1,2,3,5]\n```", "medium", '["排序","分治"]', "O(nlogn)", "经典算法"),
        ("归并排序", "实现归并排序算法。给定一个整数数组 `nums`，将数组升序排列。\n\n**要求：**\n- 实现分治+合并过程\n- 时间复杂度稳定 O(nlogn)\n\n**示例：**\n```\n输入：nums = [5,2,3,1]\n输出：[1,2,3,5]\n```", "medium", '["排序","分治"]', "O(nlogn)", "经典算法"),
        ("二分查找", "给定一个升序排列的整数数组 `nums` 和一个目标值 `target`。如果目标值存在于数组中，返回其下标，否则返回 -1。\n\n**示例：**\n```\n输入：nums = [-1,0,3,5,9,12], target = 9\n输出：4\n```", "easy", '["数组","二分查找"]', "O(logn)", "LeetCode #704"),
        ("搜索旋转排序数组", "整数数组 `nums` 按升序排列，数组中的值互不相同。在传递给函数之前，`nums` 在预先未知的某个下标上进行了旋转。给你旋转后的数组 `nums` 和一个整数 `target`，如果 `nums` 中存在这个目标值，则返回它的下标，否则返回 -1。\n\n**示例：**\n```\n输入：nums = [4,5,6,7,0,1,2], target = 0\n输出：4\n```", "medium", '["数组","二分查找"]', "O(logn)", "LeetCode #33"),
        ("在排序数组中查找元素的第一个和最后一个位置", "给你一个按非递减顺序排列的整数数组 `nums`，和一个目标值 `target`。请你找出给定目标值在数组中的开始位置和结束位置。如果不存在则返回 [-1, -1]。\n\n**示例：**\n```\n输入：nums = [5,7,7,8,8,10], target = 8\n输出：[3,4]\n```", "medium", '["数组","二分查找"]', "O(logn)", "LeetCode #34"),
        # 动态规划
        ("爬楼梯", "假设你正在爬楼梯。需要 n 阶你才能到达楼顶。每次你可以爬 1 或 2 个台阶。你有多少种不同的方法可以爬到楼顶？\n\n**示例：**\n```\n输入：n = 3\n输出：3\n解释：1+1+1, 1+2, 2+1\n```", "easy", '["动态规划"]', "O(n)", "LeetCode #70"),
        ("最大子数组和", "给你一个整数数组 `nums`，请你找出一个具有最大和的连续子数组（子数组最少包含一个元素），返回其最大和。\n\n**示例：**\n```\n输入：nums = [-2,1,-3,4,-1,2,1,-5,4]\n输出：6\n解释：连续子数组 [4,-1,2,1] 的和最大\n```", "medium", '["动态规划","分治"]', "O(n)", "LeetCode #53"),
        ("零钱兑换", "给你一个整数数组 `coins` 表示不同面额的硬币和一个整数 `amount` 表示总金额。计算并返回可以凑成总金额所需的最少硬币个数。如果无法凑成，返回 -1。\n\n**示例：**\n```\n输入：coins = [1,2,5], amount = 11\n输出：3\n解释：11 = 5 + 5 + 1\n```", "medium", '["动态规划","BFS"]', "O(n*amount)", "LeetCode #322"),
        ("最长递增子序列", "给你一个整数数组 `nums`，找到其中最长严格递增子序列的长度。\n\n**示例：**\n```\n输入：nums = [10,9,2,5,3,7,101,18]\n输出：4\n解释：最长递增子序列为 [2,3,7,101]\n```", "medium", '["动态规划","二分查找"]', "O(nlogn)", "LeetCode #300"),
        ("编辑距离", "给你两个单词 `word1` 和 `word2`，请返回将 `word1` 转换成 `word2` 所使用的最少操作数。你可以进行插入、删除、替换一个字符的操作。\n\n**示例：**\n```\n输入：word1 = \"horse\", word2 = \"ros\"\n输出：3\n```", "hard", '["动态规划","字符串"]', "O(mn)", "LeetCode #72"),
        ("最长公共子序列", "给定两个字符串 `text1` 和 `text2`，返回这两个字符串的最长公共子序列的长度。\n\n**示例：**\n```\n输入：text1 = \"abcde\", text2 = \"ace\"\n输出：3\n解释：最长公共子序列是 \"ace\"\n```", "medium", '["动态规划","字符串"]', "O(mn)", "LeetCode #1143"),
        ("不同路径", "一个机器人位于 `m x n` 网格的左上角，每次只能向下或向右移动一步。机器人试图达到网格的右下角。问总共有多少条不同的路径？\n\n**示例：**\n```\n输入：m = 3, n = 7\n输出：28\n```", "medium", '["动态规划","数学"]', "O(mn)", "LeetCode #62"),
        ("最小路径和", "给定一个包含非负整数的 `m x n` 网格 `grid`，请找出一条从左上角到右下角的路径，使得路径上的数字总和为最小。每次只能向下或者向右移动一步。\n\n**示例：**\n```\n输入：grid = [[1,3,1],[1,5,1],[4,2,1]]\n输出：7\n解释：路径 1→3→1→1→1 的总和最小\n```", "medium", '["动态规划","矩阵"]', "O(mn)", "LeetCode #64"),
        # 栈/队列
        ("有效的括号", "给定一个只包括 `(`，`)`，`{`，`}`，`[`，`]` 的字符串 `s`，判断字符串是否有效。有效字符串需满足：左括号必须用相同类型的右括号闭合，按正确顺序闭合。\n\n**示例：**\n```\n输入：s = \"()[]{}\"\n输出：true\n```", "easy", '["栈","字符串"]', "O(n)", "LeetCode #20"),
        ("最小栈", "设计一个支持 `push`、`pop`、`top` 操作，并能在常数时间内检索到最小元素的栈。\n\n**示例：**\n```\nMinStack minStack = new MinStack();\nminStack.push(-2);\nminStack.push(0);\nminStack.push(-3);\nminStack.getMin(); // 返回 -3\nminStack.pop();\nminStack.top();    // 返回 0\nminStack.getMin(); // 返回 -2\n```", "easy", '["栈","设计"]', "O(1)", "LeetCode #155"),
        ("用栈实现队列", "使用两个栈实现先入先出队列。队列应当支持一般队列支持的所有操作（push、pop、peek、empty）。\n\n**示例：**\n```\nMyQueue queue = new MyQueue();\nqueue.push(1);\nqueue.push(2);\nqueue.peek();  // 返回 1\nqueue.pop();   // 返回 1\nqueue.empty(); // 返回 false\n```", "easy", '["栈","队列","设计"]', "均摊 O(1)", "LeetCode #232"),
        ("每日温度", "给定一个整数数组 `temperatures` 表示每天的温度，返回一个数组 `answer`，其中 `answer[i]` 表示第 i 天之后需要等几天才能等到更暖和的气温。如果之后都不会更暖和，则 `answer[i] = 0`。\n\n**示例：**\n```\n输入：temperatures = [73,74,75,71,69,72,76,73]\n输出：[1,1,4,2,1,1,0,0]\n```", "medium", '["栈","单调栈"]', "O(n)", "LeetCode #739"),
        # 字符串
        ("反转字符串", "编写一个函数，将输入的字符串反转过来。\n\n**示例：**\n```\n输入：[\"h\",\"e\",\"l\",\"l\",\"o\"]\n输出：[\"o\",\"l\",\"l\",\"e\",\"h\"]\n```", "easy", '["字符串","双指针"]', "O(n)", "LeetCode #344"),
        ("字符串转换整数 (atoi)", "实现 `myAtoi(string s)` 函数，将字符串转换成一个 32 位有符号整数。\n\n**示例：**\n```\n输入：s = \"42\"\n输出：42\n\n输入：s = \"   -42\"\n输出：-42\n```", "medium", '["字符串","有限状态机"]', "O(n)", "LeetCode #8"),
        # 回溯
        ("全排列", "给定一个不含重复数字的数组 `nums`，返回其所有可能的全排列。\n\n**示例：**\n```\n输入：nums = [1,2,3]\n输出：[[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]]\n```", "medium", '["回溯","递归"]', "O(n!×n)", "LeetCode #46"),
        ("子集", "给你一个整数数组 `nums`，数组中的元素互不相同。返回该数组所有可能的子集。\n\n**示例：**\n```\n输入：nums = [1,2,3]\n输出：[[],[1],[2],[1,2],[3],[1,3],[2,3],[1,2,3]]\n```", "medium", '["回溯","位运算"]', "O(n×2ⁿ)", "LeetCode #78"),
        ("电话号码的字母组合", "给定一个仅包含数字 2-9 的字符串，返回所有它能表示的字母组合。数字到字母的映射与电话按键相同。\n\n**示例：**\n```\n输入：digits = \"23\"\n输出：[\"ad\",\"ae\",\"af\",\"bd\",\"be\",\"bf\",\"cd\",\"ce\",\"cf\"]\n```", "medium", '["回溯","字符串"]', "O(4ⁿ×n)", "LeetCode #17"),
        ("括号生成", "数字 n 代表生成括号的对数，请你设计一个函数，用于能够生成所有可能的并且有效的括号组合。\n\n**示例：**\n```\n输入：n = 3\n输出：[\"((()))\",\"(()())\",\"(())()\",\"()(())\",\"()()()\"]\n```", "medium", '["回溯","递归"]', "O(4ⁿ/√n)", "LeetCode #22"),
        # 图
        ("岛屿数量", "给你一个由 `'1'`（陆地）和 `'0'`（水）组成的二维网格，请你计算网格中岛屿的数量。\n\n**示例：**\n```\n输入：grid = [\n  [\"1\",\"1\",\"0\",\"0\",\"0\"],\n  [\"1\",\"1\",\"0\",\"0\",\"0\"],\n  [\"0\",\"0\",\"1\",\"0\",\"0\"],\n  [\"0\",\"0\",\"0\",\"1\",\"1\"]\n]\n输出：3\n```", "medium", '["图","DFS","BFS"]', "O(mn)", "LeetCode #200"),
        ("课程表", "你这个学期必须选修 `numCourses` 门课程，记为 0 到 numCourses-1。在选修某些课程之前需要一些先修课程。判断是否可能完成所有课程的学习？\n\n**示例：**\n```\n输入：numCourses = 2, prerequisites = [[1,0]]\n输出：true\n解释：先修课程 0，再修课程 1\n```", "medium", '["图","拓扑排序","BFS"]', "O(V+E)", "LeetCode #207"),
        # 堆
        ("前 K 个高频元素", "给你一个整数数组 `nums` 和一个整数 `k`，请你返回其中出现频率前 k 高的元素。可以按任意顺序返回答案。\n\n**示例：**\n```\n输入：nums = [1,1,1,2,2,3], k = 2\n输出：[1,2]\n```", "medium", '["堆","哈希表","排序"]', "O(nlogk)", "LeetCode #347"),
        ("数据流的中位数", "中位数是有序整数列表中间的数。设计一个支持以下两种操作的数据结构：`addNum(num)` 从数据流中添加一个整数到数据结构中；`findMedian()` 返回目前所有元素的中位数。\n\n**示例：**\n```\naddNum(1)\naddNum(2)\nfindMedian() -> 1.5\naddNum(3)\nfindMedian() -> 2\n```", "hard", '["堆","设计"]', "O(logn)", "LeetCode #295"),
        ("合并区间", "以数组 `intervals` 表示若干个区间的集合，其中单个区间为 `intervals[i] = [starti, endi]`。请你合并所有重叠的区间，并返回一个不重叠的区间数组。\n\n**示例：**\n```\n输入：intervals = [[1,3],[2,6],[8,10],[15,18]]\n输出：[[1,6],[8,10],[15,18]]\n解释：区间 [1,3] 和 [2,6] 重叠，合并为 [1,6]\n```", "medium", '["数组","排序"]', "O(nlogn)", "LeetCode #56"),
    ]

    for title, desc, diff, tags, complexity, source in problems:
        cursor.execute("SELECT id FROM coding_problems WHERE title = ?", (title,))
        if not cursor.fetchone():
            conn.execute(
                "INSERT INTO coding_problems (title, description, difficulty, tags, expected_complexity, source) VALUES (?, ?, ?, ?, ?, ?)",
                (title, desc, diff, tags, complexity, source)
            )

    logger.info("已创建 coding_problems / coding_submissions 表，插入 50 道初始题目")


def _migration_031_coding_scores(conn):
    """Add scores, reference_answer, total_score columns to coding_submissions."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(coding_submissions)")
    columns = {row[1] for row in cursor.fetchall()}

    if "scores" not in columns:
        conn.execute("ALTER TABLE coding_submissions ADD COLUMN scores TEXT DEFAULT '{}'")
    if "reference_answer" not in columns:
        conn.execute("ALTER TABLE coding_submissions ADD COLUMN reference_answer TEXT DEFAULT ''")
    if "total_score" not in columns:
        conn.execute("ALTER TABLE coding_submissions ADD COLUMN total_score REAL DEFAULT 0")

    logger.info("已为 coding_submissions 添加 scores/reference_answer/total_score 列")


def _migration_032_embedding_column(conn):
    """Add embedding BLOB column to question_bank for vector pre-filtering."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info('question_bank')")
    columns = [info[1] for info in cursor.fetchall()]
    if "embedding" not in columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN embedding BLOB")
    logger.info("已为 question_bank 添加 embedding BLOB 列")


def _migration_033_cluster_id(conn):
    """Add cluster_id column to question_bank for explicit cluster identification."""
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info('question_bank')")
    columns = [info[1] for info in cursor.fetchall()]
    if "cluster_id" not in columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN cluster_id INTEGER DEFAULT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_qb_cluster_id ON question_bank(cluster_id)")
    # 回填: 每条存活记录的 cluster_id = 自身 id（即自己就是聚类代表）
    conn.execute(
        "UPDATE question_bank SET cluster_id = id "
        "WHERE cluster_id IS NULL AND deleted_at IS NULL"
    )
    logger.info("已为 question_bank 添加 cluster_id 列并回填")


def _migration_034_backfill_confidence(conn):
    """回填充 merge_history 中 confidence=0 的记录。

    使用 embedding 相似度估算置信度:
    - 从 survivor 的 embedding 和 merged_questions 文本编码计算相似度
    - 如果没有 embedding 可用，使用文本精确匹配规则
    """
    import numpy as np

    # 检查 merge_history 表是否存在
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if 'merge_history' not in tables:
        logger.info("migration_034: merge_history 表不存在，跳过回填")
        return

    zero_rows = conn.execute(
        "SELECT id, survivor_id, merged_questions, confidence "
        "FROM merge_history WHERE confidence = 0 AND is_rolled_back = 0"
    ).fetchall()

    if not zero_rows:
        logger.info("migration_034: 没有 confidence=0 的记录需要回填")
        return

    updated = 0
    for row in zero_rows:
        history_id = row[0]
        survivor_id = row[1]
        merged_q_text = row[2] or '[]'

        try:
            merged_qs = json.loads(merged_q_text)
        except Exception:
            merged_qs = []

        # 尝试通过 embedding 计算置信度
        survivor_emb = None
        survivor_row = conn.execute(
            "SELECT embedding, question, original_questions FROM question_bank WHERE id = ?",
            (survivor_id,)
        ).fetchone()

        new_confidence = 0.0

        if survivor_row and survivor_row[0]:
            survivor_emb = np.frombuffer(survivor_row[0], dtype=np.float32)
            # 对每个 merged question 编码并计算相似度
            try:
                from app.services.embedding_service import encode_texts, compute_confidence_from_embeddings
                if merged_qs:
                    merged_embs = encode_texts(merged_qs)
                    confidences = [
                        compute_confidence_from_embeddings(survivor_emb, merged_embs[i])
                        for i in range(len(merged_qs))
                    ]
                    new_confidence = max(confidences) if confidences else 0.0
            except Exception as e:
                logger.warning(f"migration_034: embedding 计算失败 (id={history_id}): {e}")
                new_confidence = 0.0

        # Fallback: 如果 embedding 不可用，用文本匹配估算
        if new_confidence == 0.0 and survivor_row:
            survivor_q = survivor_row[1] or ''
            survivor_oqs = []
            try:
                survivor_oqs = json.loads(survivor_row[2]) if survivor_row[2] else []
            except Exception:
                pass
            all_survivor_texts = set([survivor_q] + survivor_oqs)
            for mq in merged_qs:
                if mq in all_survivor_texts:
                    new_confidence = 0.90
                    break
                # 部分匹配
                for st in all_survivor_texts:
                    if mq and st and (mq in st or st in mq):
                        new_confidence = 0.80
                        break
            if new_confidence == 0.0:
                new_confidence = 0.70  # 无法确定时给一个保守值

        if new_confidence > 0:
            conn.execute(
                "UPDATE merge_history SET confidence = ? WHERE id = ?",
                (new_confidence, history_id)
            )
            updated += 1

    logger.info(f"migration_034: 回填了 {updated}/{len(zero_rows)} 条 confidence=0 的记录")


# E2.算法手撕 关键词（匹配到这些词的归入 E2）
_E2_KEYWORDS = [
    '算法', '手撕', '手写', '排序', '动态规划', '贪心', '回溯', '二分',
    '滑动窗口', '双指针', 'BFS', 'DFS', '遍历', '递归', '拓扑',
    '股票', '背包', '子序列', '子数组', '字符串匹配', '合并', '搜索',
    '解题', '思路', '口述', '环',
]

# E1.数据结构 关键词（匹配到这些词的归入 E1）
_E1_KEYWORDS = [
    '数据结构', 'LRU', 'LFU', '链表', '二叉树', '红黑树', 'B+树', 'B树',
    '堆', '栈', '队列', '哈希', '跳表', '并查集',
    'Trie', '前缀树', '线段树', '设计一个支持', '设计一个',
]


def _classify_e_question(question_text: str) -> str:
    """根据题目文本判断属于 E1.数据结构 还是 E2.算法手撕

    规则: E1 数据结构关键词权重更高（+2），因为"手撕 LRU"本质是数据结构题。
    只有纯粹的算法题（无数据结构关键词）才归入 E2。
    """
    text = question_text.lower()
    e1_score = sum(2 for kw in _E1_KEYWORDS if kw.lower() in text)
    e2_score = sum(1 for kw in _E2_KEYWORDS if kw.lower() in text)
    if e1_score > 0:
        return "E1.数据结构"
    if e2_score > 0:
        return "E2.算法手撕"
    # 无匹配时默认 E1
    return "E1.数据结构"


def _migration_035_split_e_category(conn):
    """将 E1.算法手撕与数据结构 和 E1.算法手撕 拆分为 E1.数据结构 + E2.算法手撕"""
    rows = conn.execute(
        "SELECT id, question, cat2 FROM question_bank "
        "WHERE cat2 IN ('E1.算法手撕与数据结构', 'E1.算法手撕') AND deleted_at IS NULL"
    ).fetchall()

    e1_count = 0
    e2_count = 0
    for row in rows:
        qb_id, question, old_cat2 = row[0], row[1], row[2]
        new_cat2 = _classify_e_question(question)
        if new_cat2 != old_cat2:
            conn.execute(
                "UPDATE question_bank SET cat2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_cat2, qb_id)
            )
        if new_cat2 == "E1.数据结构":
            e1_count += 1
        else:
            e2_count += 1

    # 同步更新 questions_detail 表
    detail_rows = conn.execute(
        "SELECT id, question FROM questions_detail "
        "WHERE cat2 IN ('E1.算法手撕与数据结构', 'E1.算法手撕')"
    ).fetchall()
    for dr in detail_rows:
        new_cat2 = _classify_e_question(dr[1] or '')
        conn.execute("UPDATE questions_detail SET cat2 = ? WHERE id = ?", (new_cat2, dr[0]))

    logger.info(f"migration_035: 拆分 E 分类完成 — E1.数据结构={e1_count}, E2.算法手撕={e2_count}")


def _migration_036_job_payloads(conn):
    """Create job_payloads table for storing submit import task payloads.
    Add composite index on jobs for active submit job queries."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS job_payloads (
            job_id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    ''')
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_creator_type_status ON jobs(created_by, job_type, status)")
    logger.info("已创建 job_payloads 表和 jobs 复合索引")


_MIGRATIONS = [
    (1,  'base_tables',                  _migration_001_base_tables),
    (2,  'question_bank',                _migration_002_question_bank),
    (3,  'auth_tables',                  _migration_003_auth_tables),
    (4,  'jd_interview_qd_columns',      _migration_004_jd_interview_qd_columns),
    (5,  'question_bank_extra_columns',  _migration_005_question_bank_extra_columns),
    (6,  'job_positions',                _migration_006_job_positions),
    (7,  'taxonomy',                     _migration_007_taxonomy),
    (8,  'user_question_view',           _migration_008_user_question_view),
    (9,  'analysis_queue',               _migration_009_analysis_queue),
    (10, 'users_extra_columns',          _migration_010_users_extra_columns),
    (11, 'data_backfills',               _migration_011_data_backfills),
    (12, 'admin_seed',                   _migration_012_admin_seed),
    (13, 'user_question_view_user_answer', _migration_013_user_question_view_user_answer),
    (14, 'data_repairs',                 _migration_014_data_repairs),
    (15, 'refresh_tokens_extra',         _migration_015_refresh_tokens_extra),
    (16, 'normalized_source_tables',     _migration_016_normalized_source_tables),
    (17, 'backfill_normalized_sources',  _migration_017_backfill_normalized_sources),
    (18, 'composite_indexes',            _migration_018_composite_indexes),
    (19, 'fix_cascades',                 _migration_019_fix_cascades),
    # (20, 'drop_json_columns',         _migration_020_drop_json_columns),  # TODO: 启用前需先移除写路径中的 JSON 列引用
    (21, 'performance_indexes',          _migration_021_performance_indexes),
    (22, 'jobs_table',                   _migration_022_jobs_table),
    (23, 'duplicate_of',                 _migration_023_duplicate_of),
    (24, 'chat_tables',                  _migration_024_chat_tables),
    (25, 'question_fts',                 _migration_025_question_fts),
    (26, 'populate_fts',                 _migration_026_populate_fts),
    (27, 'memory_summary',               _migration_027_memory_summary),
    (28, 'session_notes',                _migration_028_session_notes),
    (29, 'user_resumes',                 _migration_029_user_resumes),
    (30, 'coding_module',                _migration_030_coding_module),
    (31, 'coding_scores',                _migration_031_coding_scores),
    (32, 'embedding_column',             _migration_032_embedding_column),
    (33, 'cluster_id',                   _migration_033_cluster_id),
    (34, 'backfill_confidence',          _migration_034_backfill_confidence),
    (35, 'split_e_category',             _migration_035_split_e_category),
    (36, 'job_payloads',                 _migration_036_job_payloads),
]


def run_migrations(conn):
    """Apply all pending migrations in order."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    applied = {row[0] for row in cursor.execute("SELECT version FROM schema_version").fetchall()}
    for version, name, func in _MIGRATIONS:
        if version in applied:
            continue
        logger.info(f"Applying migration {version:03d}: {name}")
        cursor.execute("BEGIN")
        try:
            func(conn)
            cursor.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)", (version, name))
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

"""Question bank domain migrations: 001, 002, 004, 005, 006, 007."""

import json
import logging

from app.core.prompts import DEFAULT_TAXONOMY

logger = logging.getLogger("interview-boss")


def _migration_001_base_tables(conn):
    """Create core tables: master_question_bank, interview, user_profile,
    practice_history, users.  Seed default user_profile values."""
    cursor = conn.cursor()

    conn.execute("""
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
    """)
    cursor.execute("PRAGMA table_info(master_question_bank)")
    columns = [info[1] for info in cursor.fetchall()]
    if "vector" not in columns:
        conn.execute("ALTER TABLE master_question_bank ADD COLUMN vector TEXT")
    if "sources" not in columns:
        conn.execute(
            "ALTER TABLE master_question_bank ADD COLUMN sources TEXT DEFAULT '[]'"
        )
    if "is_starred" not in columns:
        conn.execute(
            "ALTER TABLE master_question_bank ADD COLUMN is_starred INTEGER DEFAULT 0"
        )

    conn.execute("""
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
    """)
    cursor.execute("PRAGMA table_info(interview)")
    interview_cols = [info[1] for info in cursor.fetchall()]
    if "season" not in interview_cols:
        conn.execute("ALTER TABLE interview ADD COLUMN season TEXT DEFAULT ''")
    # ── 迁移：interview 表添加 owner_id 和 status 列（个人/公共管理）──
    interview_col_set = {
        row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()
    }
    if "owner_id" not in interview_col_set:
        conn.execute(
            "ALTER TABLE interview ADD COLUMN owner_id INTEGER REFERENCES users(id)"
        )
    if "status" not in interview_col_set:
        conn.execute("ALTER TABLE interview ADD COLUMN status TEXT DEFAULT 'approved'")
    if "job_position" not in interview_col_set:
        conn.execute("ALTER TABLE interview ADD COLUMN job_position TEXT DEFAULT ''")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profile (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for k, v in [
        ("active_season", ""),
        ("llm_model", ""),
        ("llm_api_key", ""),
        ("llm_base_url", ""),
        ("llm_timeout", ""),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO user_profile (key, value) VALUES (?, ?)", (k, v)
        )

    # seed 默认分类体系（仅首次）
    conn.execute(
        "INSERT OR IGNORE INTO user_profile (key, value) VALUES (?, ?)",
        ("taxonomy_config", json.dumps(DEFAULT_TAXONOMY, ensure_ascii=False)),
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("PRAGMA index_list('practice_history')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_practice_question" not in indexes:
        conn.execute(
            "CREATE INDEX idx_practice_question ON practice_history(question_id)"
        )

    # ── users 表 ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            bank_mode TEXT DEFAULT 'public',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    users_col_set = {
        row[1] for row in cursor.execute("PRAGMA table_info('users')").fetchall()
    }
    if "updated_at" not in users_col_set:
        conn.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP")
        conn.execute(
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )


def _migration_002_question_bank(conn):
    """Create question_bank and user_practice_history tables."""
    cursor = conn.cursor()

    # ── question_bank 表（统一题库，取代 master_question_bank）──
    conn.execute("""
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
    """)

    # ── user_practice_history 表 ──
    conn.execute("""
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
    """)
    cursor.execute("PRAGMA index_list('user_practice_history')")
    uph_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_uph_user" not in uph_indexes:
        conn.execute("CREATE INDEX idx_uph_user ON user_practice_history(user_id)")
    if "idx_uph_question" not in uph_indexes:
        conn.execute(
            "CREATE INDEX idx_uph_question ON user_practice_history(question_bank_id)"
        )
    uph_col_set = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info('user_practice_history')"
        ).fetchall()
    }
    if "updated_at" not in uph_col_set:
        conn.execute(
            "ALTER TABLE user_practice_history ADD COLUMN updated_at TIMESTAMP"
        )
        conn.execute(
            "UPDATE user_practice_history SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )


def _migration_004_jd_interview_qd_columns(conn):
    """Column/index migrations for jd, interview, questions_detail tables."""
    cursor = conn.cursor()

    # ── 创建 jd 表（如果不存在）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            season TEXT DEFAULT '',
            owner_id INTEGER,
            status TEXT DEFAULT 'approved',
            url_signature TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            job_position TEXT DEFAULT '',
            deleted_at TIMESTAMP,
            tech_stack TEXT,
            source TEXT DEFAULT '',
            position TEXT DEFAULT '',
            salary TEXT DEFAULT '',
            job_title TEXT DEFAULT ''
        )
    """)

    # ── 迁移：jd 表添加 season 列 ──
    jd_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info('jd')").fetchall()
    }
    if "season" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN season TEXT DEFAULT ''")
        conn.execute(
            "UPDATE jd SET season = '2027届暑期实习', updated_at = CURRENT_TIMESTAMP WHERE season IS NULL OR season = ''"
        )
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
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_jd_url_unique ON jd(url, owner_id) WHERE url IS NOT NULL AND url != ''"
        )
    if "idx_jd_owner_status" not in jd_indexes:
        conn.execute("CREATE INDEX idx_jd_owner_status ON jd(owner_id, status)")
    # Bug #11: jd 表添加 url_signature 列用于高效去重
    if "url_signature" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN url_signature TEXT DEFAULT ''")
    if "idx_jd_url_sig" not in jd_indexes:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jd_url_sig ON jd(url_signature)")
    if "updated_at" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN updated_at TIMESTAMP")
        conn.execute(
            "UPDATE jd SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )
    if "deleted_at" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN deleted_at TIMESTAMP")
    # ── 迁移：jd 表添加 job_position 列（岗位隔离）──
    jd_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info('jd')").fetchall()
    }
    if "job_position" not in jd_columns:
        conn.execute("ALTER TABLE jd ADD COLUMN job_position TEXT DEFAULT ''")
        # 回填已有 JD 记录的 job_position 为当前全局岗位
        try:
            current_pos = conn.execute(
                "SELECT value FROM user_profile WHERE key = 'current_job_position'"
            ).fetchone()
            if current_pos and current_pos[0]:
                conn.execute(
                    "UPDATE jd SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''",
                    (current_pos[0],),
                )
                logger.info(f"已为 jd 表添加 job_position 列并回填为 {current_pos[0]}")
        except Exception:
            pass
    # ── 迁移：修复 interview 表中空 job_position 的历史数据 ──
    empty_pos_count = conn.execute(
        "SELECT COUNT(*) FROM interview WHERE job_position IS NULL OR job_position = ''"
    ).fetchone()[0]
    if empty_pos_count > 0:
        try:
            current_pos = conn.execute(
                "SELECT value FROM user_profile WHERE key = 'current_job_position'"
            ).fetchone()
            if current_pos and current_pos[0]:
                conn.execute(
                    "UPDATE interview SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''",
                    (current_pos[0],),
                )
                logger.info(
                    f"已将 {empty_pos_count} 条面经记录的 job_position 回填为 {current_pos[0]}"
                )
        except Exception:
            pass

    cursor.execute("PRAGMA index_list('interview')")
    iv_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_interview_url" not in iv_indexes:
        conn.execute("CREATE INDEX idx_interview_url ON interview(url)")
    if "idx_interview_url_unique" not in iv_indexes:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_interview_url_unique ON interview(url, owner_id) WHERE url IS NOT NULL AND url != ''"
        )
    if "idx_interview_owner_status" not in iv_indexes:
        conn.execute(
            "CREATE INDEX idx_interview_owner_status ON interview(owner_id, status)"
        )
    # Bug #11: interview 表添加 url_signature 列用于高效去重
    iv_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info('interview')").fetchall()
    }
    if "url_signature" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN url_signature TEXT DEFAULT ''")
    if "idx_interview_url_sig" not in iv_indexes:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_interview_url_sig ON interview(url_signature)"
        )
    if "updated_at" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN updated_at TIMESTAMP")
        conn.execute(
            "UPDATE interview SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )
    if "deleted_at" not in iv_columns:
        conn.execute("ALTER TABLE interview ADD COLUMN deleted_at TIMESTAMP")

    # ── 创建 questions_detail 表（如果不存在）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER,
            question TEXT,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            difficulty TEXT,
            diff_tag TEXT,
            answer TEXT,
            url TEXT,
            source TEXT DEFAULT '',
            owner_id INTEGER,
            status TEXT DEFAULT 'approved',
            deleted_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            job_position TEXT DEFAULT ''
        )
    """)

    cursor.execute("PRAGMA index_list('questions_detail')")
    qd_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_qd_url" not in qd_indexes:
        conn.execute("CREATE INDEX idx_qd_url ON questions_detail(url)")
    qd_col_set = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('questions_detail')").fetchall()
    }
    if "updated_at" not in qd_col_set:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN updated_at TIMESTAMP")
        conn.execute(
            "UPDATE questions_detail SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )
    if "deleted_at" not in qd_col_set:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN deleted_at TIMESTAMP")
    # 刷新列集合
    qd_col_set = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('questions_detail')").fetchall()
    }
    if "job_position" not in qd_col_set:
        conn.execute(
            "ALTER TABLE questions_detail ADD COLUMN job_position TEXT DEFAULT ''"
        )
        # 回填：通过 question_bank 中已有的匹配题目获取 job_position
        # 注意：question_bank.job_position 在 migration 005 才添加，此处需检查
        qb_col_check = {
            row[1]
            for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()
        }
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
        _pos_row = conn.execute(
            "SELECT value FROM user_profile WHERE key = 'taxonomy_config'"
        ).fetchone()
        if _pos_row and _pos_row[0]:
            try:
                _tc = json.loads(_pos_row[0])
                _default_pos = _tc.get("job_position", _default_pos)
            except Exception:
                pass
        conn.execute(
            "UPDATE questions_detail SET job_position = ? WHERE job_position IS NULL OR job_position = ''",
            (_default_pos,),
        )
        logger.info(
            f"已为 questions_detail 表添加 job_position 列并回填为 {_default_pos}"
        )

    cursor.execute("PRAGMA index_list('question_bank')")
    qb_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_qb_owner_status" not in qb_indexes:
        conn.execute(
            "CREATE INDEX idx_qb_owner_status ON question_bank(owner_id, status)"
        )


def _migration_005_question_bank_extra_columns(conn):
    """question_bank extra columns: original_questions, original_question_sources,
    deleted_at, job_position + backfill, question_manually_edited,
    current_job_position initialization.  Also clean invalid positions/categories."""
    cursor = conn.cursor()

    # ── 迁移：添加 original_questions 和 original_question_sources 列 ──
    qb_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    if "original_questions" not in qb_columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN original_questions TEXT DEFAULT '[]'"
        )
    if "original_question_sources" not in qb_columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN original_question_sources TEXT DEFAULT '[]'"
        )

    # ── 迁移：添加 deleted_at 列（软删除支持）──
    qb_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    if "deleted_at" not in qb_columns:
        conn.execute("ALTER TABLE question_bank ADD COLUMN deleted_at TIMESTAMP")
        logger.info("已为 question_bank 表添加 deleted_at 列（软删除支持）")

    # ── 清理脏数据：job_positions 表中的无效岗位（表在 migration 006 创建）──
    jp_exists = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='job_positions'"
    ).fetchone()
    if jp_exists:
        invalid_positions = conn.execute(
            "SELECT id, name FROM job_positions WHERE name LIKE '%test%' OR name LIKE '%测试%' OR LENGTH(name) > 30 OR name LIKE '%!@#$%' OR name LIKE '%AAAA%'"
        ).fetchall()
        if invalid_positions:
            for pos in invalid_positions:
                conn.execute(
                    "DELETE FROM question_position WHERE position_id = ?", (pos[0],)
                )
                conn.execute("DELETE FROM taxonomy WHERE position_name = ?", (pos[1],))
                conn.execute("DELETE FROM job_positions WHERE id = ?", (pos[0],))
            logger.info(f"已清理 {len(invalid_positions)} 个无效岗位数据")

    # ── 清理脏数据：question_bank 表中的无效分类 ──
    conn.execute(
        "UPDATE question_bank SET cat1 = '' WHERE cat1 = 'test' AND deleted_at IS NULL"
    )
    logger.info("已清理 question_bank 表中的无效分类数据")

    # ── 迁移：添加 job_position 列（多岗位隔离）──
    if "job_position" not in qb_columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN job_position TEXT DEFAULT ''"
        )
        # 回填现有数据为当前岗位
        current_pos = DEFAULT_TAXONOMY["job_position"]
        pos_row = conn.execute(
            "SELECT value FROM user_profile WHERE key = 'taxonomy_config'"
        ).fetchone()
        if pos_row and pos_row[0]:
            try:
                tc = json.loads(pos_row[0])
                current_pos = tc.get("job_position", current_pos)
            except Exception:
                pass
        conn.execute(
            "UPDATE question_bank SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''",
            (current_pos,),
        )
        logger.info(f"已为 question_bank 表添加 job_position 列并回填为 {current_pos}")
    cursor.execute("PRAGMA index_list('question_bank')")
    qb_idx = [row[1] for row in cursor.fetchall()]
    if "idx_qb_job_position" not in qb_idx:
        conn.execute("CREATE INDEX idx_qb_job_position ON question_bank(job_position)")

    # ── 迁移：添加 question_manually_edited 标记（防止手动编辑被覆盖）──
    qb_col_set = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    if "question_manually_edited" not in qb_col_set:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN question_manually_edited INTEGER DEFAULT 0"
        )

    # ── 初始化 current_job_position ──
    pos_exists = conn.execute(
        "SELECT 1 FROM user_profile WHERE key = 'current_job_position'"
    ).fetchone()
    if not pos_exists:
        conn.execute(
            "INSERT INTO user_profile (key, value) VALUES (?, ?)",
            ("current_job_position", DEFAULT_TAXONOMY["job_position"]),
        )


def _migration_006_job_positions(conn):
    """Create job_positions and question_position tables."""
    cursor = conn.cursor()

    # ── job_positions 表（岗位实体）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    jp_col_set = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('job_positions')").fetchall()
    }
    if "updated_at" not in jp_col_set:
        conn.execute("ALTER TABLE job_positions ADD COLUMN updated_at TIMESTAMP")
        conn.execute(
            "UPDATE job_positions SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )

    # ── question_position 关联表（题目-岗位多对多）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS question_position (
            question_id INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            PRIMARY KEY (question_id, position_id),
            FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("PRAGMA index_list('question_position')")
    qp_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_qp_position" not in qp_indexes:
        conn.execute("CREATE INDEX idx_qp_position ON question_position(position_id)")


def _migration_007_taxonomy(conn):
    """Create taxonomy table + source/owner_id/is_public columns + unique index."""
    cursor = conn.cursor()

    # ── taxonomy 表（岗位分类体系，取代 user_profile 中的 taxonomy_config JSON）──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taxonomy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_name TEXT NOT NULL,
            categories_json TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 迁移：taxonomy 表增加权限相关字段
    tx_col_set = {
        row[1] for row in cursor.execute("PRAGMA table_info('taxonomy')").fetchall()
    }
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

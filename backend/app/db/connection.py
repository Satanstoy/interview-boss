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
        users_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('users')").fetchall()}
        if "updated_at" not in users_col_set:
            conn.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP")
            conn.execute("UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")

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

        # ── 性能索引 ──
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
            conn.execute("""
                UPDATE questions_detail SET job_position = (
                    SELECT qb.job_position FROM question_bank qb
                    WHERE qb.original_questions LIKE '%' || questions_detail.question || '%'
                    AND qb.job_position IS NOT NULL AND qb.job_position != ''
                    LIMIT 1
                ) WHERE job_position IS NULL OR job_position = ''
            """)
            from app.core.prompts import DEFAULT_TAXONOMY
            _default_pos = DEFAULT_TAXONOMY["job_position"]
            _pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'taxonomy_config'").fetchone()
            if _pos_row and _pos_row[0]:
                try:
                    import json as _json
                    _tc = _json.loads(_pos_row[0])
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
        if "idx_rt_family" not in rt_indexes:
            conn.execute("CREATE INDEX idx_rt_family ON refresh_tokens(family_id)")

        # ── invalidated_families 表（记录被撤销的 token family）──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS invalidated_families (
                family_id TEXT PRIMARY KEY,
                invalidated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

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

        # ── 清理脏数据：job_positions 表中的无效岗位 ──
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
            from app.core.prompts import DEFAULT_TAXONOMY
            current_pos = DEFAULT_TAXONOMY["job_position"]
            pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'taxonomy_config'").fetchone()
            if pos_row and pos_row[0]:
                try:
                    import json as _json
                    tc = _json.loads(pos_row[0])
                    current_pos = tc.get("job_position", current_pos)
                except Exception:
                    pass
            conn.execute("UPDATE question_bank SET job_position = ?, updated_at = CURRENT_TIMESTAMP WHERE job_position IS NULL OR job_position = ''", (current_pos,))
            logger.info(f"已为 question_bank 表添加 job_position 列并回填为 {current_pos}")
        cursor.execute("PRAGMA index_list('question_bank')")
        qb_idx = [row[1] for row in cursor.fetchall()]
        if "idx_qb_job_position" not in qb_idx:
            conn.execute("CREATE INDEX idx_qb_job_position ON question_bank(job_position)")

        # ── 初始化 current_job_position ──
        pos_exists = conn.execute("SELECT 1 FROM user_profile WHERE key = 'current_job_position'").fetchone()
        if not pos_exists:
            from app.core.prompts import DEFAULT_TAXONOMY
            conn.execute(
                "INSERT INTO user_profile (key, value) VALUES (?, ?)",
                ("current_job_position", DEFAULT_TAXONOMY["job_position"])
            )

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
        cursor.execute("PRAGMA index_list('taxonomy')")
        tx_indexes = [row[1] for row in cursor.fetchall()]
        if "idx_taxonomy_position" not in tx_indexes:
            conn.execute("CREATE UNIQUE INDEX idx_taxonomy_position ON taxonomy(position_name)")

        # ── user_question_view 表（用户个人标注：收藏/标签/笔记）──
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_question_view (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_bank_id INTEGER NOT NULL,
                is_starred INTEGER DEFAULT 0,
                personal_tags TEXT DEFAULT '',
                note TEXT DEFAULT '',
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

        # ── users 表增加 current_position_id 列 ──
        users_columns = {row[1] for row in cursor.execute("PRAGMA table_info('users')").fetchall()}
        if "current_position_id" not in users_columns:
            conn.execute("ALTER TABLE users ADD COLUMN current_position_id INTEGER REFERENCES job_positions(id)")
        if "personal_position" not in users_columns:
            conn.execute("ALTER TABLE users ADD COLUMN personal_position TEXT")

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
        import json as _json
        from app.core.prompts import DEFAULT_TAXONOMY
        tx_count = conn.execute("SELECT COUNT(*) FROM taxonomy").fetchone()[0]
        if tx_count == 0:
            # seed 默认 taxonomy
            conn.execute(
                "INSERT OR IGNORE INTO taxonomy (position_name, categories_json, is_default) VALUES (?, ?, 1)",
                (DEFAULT_TAXONOMY["job_position"], _json.dumps(DEFAULT_TAXONOMY["categories"], ensure_ascii=False))
            )
            # 从 user_profile 迁移已有的 taxonomy 配置
            tx_rows = conn.execute("SELECT key, value FROM user_profile WHERE key LIKE 'taxonomy_config%'").fetchall()
            for tx_row in tx_rows:
                try:
                    tc = _json.loads(tx_row['value'])
                    pos = tc.get('job_position', '')
                    cats = tc.get('categories', [])
                    if pos and cats:
                        conn.execute(
                            "INSERT OR REPLACE INTO taxonomy (position_name, categories_json) VALUES (?, ?)",
                            (pos, _json.dumps(cats, ensure_ascii=False))
                        )
                except Exception:
                    pass
            migrated_tx = conn.execute("SELECT COUNT(*) FROM taxonomy").fetchone()[0]
            logger.info(f"已迁移 {migrated_tx} 个岗位的 taxonomy 配置到 taxonomy 表")

        # ── 迁移：question_bank.is_starred → user_question_view ──
        uqv_count = conn.execute("SELECT COUNT(*) FROM user_question_view").fetchone()[0]
        starred_count = conn.execute("SELECT COUNT(*) FROM question_bank WHERE is_starred = 1").fetchone()[0]
        if uqv_count == 0 and starred_count > 0:
            from passlib.context import CryptContext
            import os
            admin_username = os.getenv("ADMIN_USERNAME", "sj")
            admin_row = conn.execute("SELECT id FROM users WHERE username = ?", (admin_username,)).fetchone()
            if admin_row:
                conn.execute(
                    "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) "
                    "SELECT ?, id, 1 FROM question_bank WHERE is_starred = 1",
                    (admin_row[0],)
                )
                logger.info(f"已迁移 {starred_count} 条收藏记录到 user_question_view（归属管理员）")

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

        # ── 清理遗留旧表（数据已迁移到 question_bank / user_practice_history）──
        conn.execute("DROP TABLE IF EXISTS master_question_bank")
        conn.execute("DROP TABLE IF EXISTS practice_history")

        # ── 修复: question_bank.frequency 与 sources 数组长度不一致 ──
        import json as _fix_json
        _fix_rows = conn.execute("SELECT id, frequency, sources FROM question_bank").fetchall()
        _fix_count = 0
        for _r in _fix_rows:
            _qb_id, _freq, _sources_raw = _r[0], _r[1], _r[2]
            try:
                _srcs = _fix_json.loads(_sources_raw) if _sources_raw else []
            except Exception:
                _srcs = []
            _actual = len(_srcs)
            if _freq != _actual and _actual > 0:
                conn.execute("UPDATE question_bank SET frequency = ? WHERE id = ?", (_actual, _qb_id))
                _fix_count += 1
        if _fix_count > 0:
            logger.info(f"已修复 {_fix_count} 条 question_bank 记录的 frequency 字段")

        # ── 修复: original_question_sources 中包含 sources 中不存在的 URL ──
        _oqs_rows = conn.execute("SELECT id, sources, original_question_sources FROM question_bank WHERE original_question_sources != '[]' AND original_question_sources IS NOT NULL").fetchall()
        _oqs_fix = 0
        for _r in _oqs_rows:
            _qb_id, _src_raw, _oqs_raw = _r[0], _r[1], _r[2]
            try:
                _srcs = _fix_json.loads(_src_raw) if _src_raw else []
                _oqs = _fix_json.loads(_oqs_raw) if _oqs_raw else []
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
                             (_fix_json.dumps(_oqs, ensure_ascii=False), _qb_id))
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
                _srcs = _fix_json.loads(_src_raw) if _src_raw else []
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
                             (_fix_json.dumps(_new_oqs, ensure_ascii=False), _qb_id))
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
                _srcs = _fix_json.loads(_src_raw) if _src_raw else []
                _oqs = _fix_json.loads(_oqs_raw) if _oqs_raw else []
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
                             (_fix_json.dumps(_oqs, ensure_ascii=False), _qb_id))
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
                _srcs = _fix_json.loads(_src_raw) if _src_raw else []
                _oqs = _fix_json.loads(_oqs_raw) if _oqs_raw else []
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
                             (_fix_json.dumps(_oqs, ensure_ascii=False), _qb_id))
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


def get_current_job_position() -> str:
    """从 user_profile 读取当前岗位（全局 fallback），fallback 到默认值"""
    from app.core.prompts import DEFAULT_TAXONOMY
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
            if row and row['value']:
                return row['value']
    except Exception:
        pass
    return DEFAULT_TAXONOMY["job_position"]


def get_user_job_position(user_id: int) -> tuple[int | None, str]:
    """获取用户的当前岗位：返回 (position_id, position_name)

    优先级：users.personal_position → users.current_position_id → 全局 fallback
    """
    from app.core.prompts import DEFAULT_TAXONOMY
    default_name = DEFAULT_TAXONOMY["job_position"]
    try:
        with get_db_connection() as conn:
            # 最高优先：用户个人岗位（不关联 job_positions 表）
            row = conn.execute(
                "SELECT personal_position FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row and row['personal_position']:
                return None, row['personal_position']

            # 次优先：users.current_position_id → job_positions.name
            row = conn.execute(
                "SELECT u.current_position_id, jp.name FROM users u "
                "LEFT JOIN job_positions jp ON u.current_position_id = jp.id "
                "WHERE u.id = ?", (user_id,)
            ).fetchone()
            if row and row['current_position_id'] and row['name']:
                return row['current_position_id'], row['name']

            # fallback: 全局设置
            pos_row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
            if pos_row and pos_row[0]:
                jp_row = conn.execute("SELECT id FROM job_positions WHERE name = ?", (pos_row[0],)).fetchone()
                return (jp_row[0] if jp_row else None), pos_row[0]
    except Exception:
        pass
    return None, default_name


def set_user_job_position(user_id: int, position_id: int):
    """设置用户的当前岗位"""
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET current_position_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (position_id, user_id))
        conn.commit()


def get_dynamic_frequency_sql(bank_mode: str, user_id: int, table_alias: str = "qb") -> str:
    """根据 bank_mode 返回动态计算频率的 SQL 子查询片段。

    频率 = sources JSON 中匹配当前模式的面试记录数量。
    - public:  只统计 owner_id IS NULL 的面试
    - personal: 只统计 owner_id = user_id 的面试
    - mixed:   统计 owner_id IS NULL 或 owner_id = user_id 的面试
    """
    if bank_mode == 'personal':
        return (
            f"(SELECT COUNT(*) FROM json_each({table_alias}.sources) je "
            f"JOIN interview i ON json_extract(je.value, '$.url') = i.url "
            f"WHERE i.deleted_at IS NULL AND i.owner_id = {user_id})"
        )
    elif bank_mode == 'mixed':
        return (
            f"(SELECT COUNT(*) FROM json_each({table_alias}.sources) je "
            f"JOIN interview i ON json_extract(je.value, '$.url') = i.url "
            f"WHERE i.deleted_at IS NULL AND (i.owner_id IS NULL OR i.owner_id = {user_id}))"
        )
    else:  # public
        return (
            f"(SELECT COUNT(*) FROM json_each({table_alias}.sources) je "
            f"JOIN interview i ON json_extract(je.value, '$.url') = i.url "
            f"WHERE i.deleted_at IS NULL AND i.owner_id IS NULL)"
        )


def filter_sources_by_mode(sources_list: list, bank_mode: str, user_id: int) -> list:
    """根据 bank_mode 过滤 sources 列表，只保留当前模式可见的来源。"""
    if not sources_list:
        return []
    urls = [s.get('url') for s in sources_list if s.get('url')]
    if not urls:
        return sources_list
    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(urls))
        rows = conn.execute(
            f"SELECT url, owner_id FROM interview WHERE url IN ({placeholders}) AND deleted_at IS NULL",
            urls
        ).fetchall()
    url_owner = {r['url']: r['owner_id'] for r in rows}
    result = []
    for s in sources_list:
        owner = url_owner.get(s.get('url'))
        if bank_mode == 'personal' and owner == user_id:
            result.append(s)
        elif bank_mode == 'public' and owner is None:
            result.append(s)
        elif bank_mode == 'mixed' and (owner is None or owner == user_id):
            result.append(s)
    return result


def filter_original_question_sources_by_mode(oqs_list: list, bank_mode: str, user_id: int) -> list:
    """根据 bank_mode 过滤 original_question_sources 中每条记录的 sources 子列表。"""
    if not oqs_list:
        return []
    all_urls = set()
    for item in oqs_list:
        for s in item.get('sources', []):
            if s.get('url'):
                all_urls.add(s['url'])
    if not all_urls:
        return oqs_list
    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(all_urls))
        rows = conn.execute(
            f"SELECT url, owner_id FROM interview WHERE url IN ({placeholders}) AND deleted_at IS NULL",
            list(all_urls)
        ).fetchall()
    url_owner = {r['url']: r['owner_id'] for r in rows}
    result = []
    for item in oqs_list:
        filtered_sources = []
        for s in item.get('sources', []):
            owner = url_owner.get(s.get('url'))
            if bank_mode == 'personal' and owner == user_id:
                filtered_sources.append(s)
            elif bank_mode == 'public' and owner is None:
                filtered_sources.append(s)
            elif bank_mode == 'mixed' and (owner is None or owner == user_id):
                filtered_sources.append(s)
        if filtered_sources:
            result.append({**item, 'sources': filtered_sources})
    return result


def get_taxonomy_for_position(position: str = None) -> dict:
    """从 taxonomy 表读取岗位分类配置，fallback 链: position 行 → default 行 → 常量"""
    import json as _json
    from app.core.prompts import DEFAULT_TAXONOMY
    if position is None:
        position = get_current_job_position()
    try:
        with get_db_connection() as conn:
            # 1. 按岗位名查找
            row = conn.execute(
                "SELECT categories_json FROM taxonomy WHERE position_name = ?", (position,)
            ).fetchone()
            if row and row['categories_json']:
                return {"job_position": position, "categories": _json.loads(row['categories_json'])}
            # 2. fallback 到默认行
            row2 = conn.execute(
                "SELECT position_name, categories_json FROM taxonomy WHERE is_default = 1"
            ).fetchone()
            if row2 and row2['categories_json']:
                return {"job_position": row2['position_name'], "categories": _json.loads(row2['categories_json'])}
    except Exception:
        pass
    # 3. 最终 fallback 到代码常量
    return DEFAULT_TAXONOMY


def save_taxonomy_for_position(position_name: str, categories: list):
    """UPSERT taxonomy 到 taxonomy 表"""
    import json as _json
    with get_db_connection() as conn:
        categories_json = _json.dumps(categories, ensure_ascii=False)
        conn.execute(
            "INSERT INTO taxonomy (position_name, categories_json, updated_at) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(position_name) DO UPDATE SET "
            "categories_json = excluded.categories_json, updated_at = CURRENT_TIMESTAMP",
            (position_name, categories_json)
        )
        conn.commit()


async def run_db(func):
    """在线程池中执行同步数据库操作，避免阻塞事件循环"""
    return await asyncio.to_thread(func)

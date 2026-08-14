"""Schema hygiene migrations 081-086.

081 cleanup_fk_orphans       — 删除已核实 FK 孤儿行（chat/asked_questions/quality_issue 等），断言 foreign_key_check=0
082 fts_rebuild_triggers     — 全量重建 question_fts + 安装 question_bank INSERT/UPDATE/DELETE 同步触发器
083 index_housekeeping       — 删除重复唯一索引（practice_decks.deck_key / user_question_review）
084 normalize_timestamps_jobs— 重建 jobs（去 error 列、available_at 默认 CURRENT_TIMESTAMP、回填空串）、
                              login_failures（locked_until REAL→TEXT）、mcp_sessions（updated_at INTEGER→TEXT）、
                              refresh_tokens.created_at 统一 ISO
085 add_fk_declarations      — 重建 12 张表补齐 FK 声明与 ON DELETE 策略；users.username 回填小写
086 drop_dead_columns_indexes— 删除 question_bank.vector/duplicate_of 死列；新增过期清理索引

所有 destructive 迁移由 run_migrations 自动前置整库备份并临时关闭 FK 约束（见 __init__.py）。
"""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


# ── helpers ─────────────────────────────────────────────────────────────────


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _index_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn, table: str, column: str) -> bool:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info('{table}')")}
    return column in cols


def _column_type(conn, table: str, column: str) -> str | None:
    for r in conn.execute(f"PRAGMA table_info('{table}')"):
        if r[1] == column:
            return (r[2] or "").upper()
    return None


def _has_fk(conn, table: str, column: str) -> bool:
    for r in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
        if r[3] == column:  # 第 4 列是 from（本表列名）
            return True
    return False


def _fk_on_delete(conn, table: str, column: str) -> str | None:
    """返回该列 FK 的 ON DELETE 动作（NO ACTION / CASCADE / SET NULL / RESTRICT）。"""
    for r in conn.execute(f"PRAGMA foreign_key_list('{table}')"):
        if r[3] == column:
            return r[6]  # on_delete 列
    return None


def _rebuild_table(conn, table: str, create_sql: str, columns: list[str], select_sql: str | None = None):
    """标准重建：CREATE new → 拷贝数据 → DROP old → RENAME。迁移期 FK 由 runner 关闭。"""
    cols = ", ".join(columns)
    sel = select_sql or cols
    conn.execute(f"DROP TABLE IF EXISTS {table}_new")
    conn.execute(create_sql)
    conn.execute(f"INSERT INTO {table}_new ({cols}) SELECT {sel} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")


def _drop_index_if_exists(conn, name: str):
    if _index_exists(conn, name):
        conn.execute(f"DROP INDEX {name}")


def _create_index_if_missing(conn, sql: str, name: str):
    if not _index_exists(conn, name):
        conn.execute(sql)


# ── 081 cleanup_fk_orphans ──────────────────────────────────────────────────


def _migration_081_cleanup_fk_orphans(conn):
    """删除已核实的 FK 孤儿行，删除后断言 PRAGMA foreign_key_check = 0。

    孤儿来源：e3936da 启用 PRAGMA foreign_keys=ON 之前级联从未生效，
    硬删父行留下的历史残留（chat_messages 1316、asked_questions 2235/1860、
    quality_issue 7、analysis_queue 19、question_sources/qoi/qp 各 1）。
    """
    deleted = {}

    def _del(label, sql, params=()):
        cur = conn.execute(sql, params)
        deleted[label] = cur.rowcount

    # chat_messages → chat_conversations
    _del("chat_messages", """
        DELETE FROM chat_messages
        WHERE NOT EXISTS (SELECT 1 FROM chat_conversations c WHERE c.id = chat_messages.conversation_id)
    """)
    # question_sources / question_original_items / question_position → question_bank
    _del("question_sources", """
        DELETE FROM question_sources
        WHERE NOT EXISTS (SELECT 1 FROM question_bank q WHERE q.id = question_sources.question_bank_id)
    """)
    _del("question_original_items", """
        DELETE FROM question_original_items
        WHERE NOT EXISTS (SELECT 1 FROM question_bank q WHERE q.id = question_original_items.question_bank_id)
    """)
    # 迁移期 FK 关闭，ON DELETE CASCADE 不生效：删除孤儿父行后必须手动清理子表
    # （顺序在父行删除之后，否则父行仍存在时子行不会被清）
    _del("question_original_item_sources", """
        DELETE FROM question_original_item_sources
        WHERE NOT EXISTS (SELECT 1 FROM question_original_items o
                          WHERE o.id = question_original_item_sources.original_item_id)
    """)
    _del("question_position", """
        DELETE FROM question_position
        WHERE NOT EXISTS (SELECT 1 FROM question_bank q WHERE q.id = question_position.question_id)
    """)
    # quality_issue → question_bank（无 FK 声明，硬删题后残留）
    if _table_exists(conn, "quality_issue"):
        _del("quality_issue", """
            DELETE FROM quality_issue
            WHERE NOT EXISTS (SELECT 1 FROM question_bank q WHERE q.id = quality_issue.qb_id)
        """)
    # interview_asked_questions → 三张父表（全列缺 FK）
    if _table_exists(conn, "interview_asked_questions"):
        _del("asked_questions_conversation", """
            DELETE FROM interview_asked_questions
            WHERE NOT EXISTS (SELECT 1 FROM chat_conversations c WHERE c.id = interview_asked_questions.conversation_id)
        """)
        _del("asked_questions_question", """
            DELETE FROM interview_asked_questions
            WHERE NOT EXISTS (SELECT 1 FROM question_bank q WHERE q.id = interview_asked_questions.question_id)
        """)
        _del("asked_questions_user", """
            DELETE FROM interview_asked_questions
            WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = interview_asked_questions.user_id)
        """)
    # analysis_queue.question_detail_id → questions_detail
    if _table_exists(conn, "analysis_queue") and _column_exists(conn, "analysis_queue", "question_detail_id"):
        _del("analysis_queue_question_detail", """
            DELETE FROM analysis_queue
            WHERE question_detail_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM questions_detail d WHERE d.id = analysis_queue.question_detail_id)
        """)
    # email_verification_codes.user_id → users（补 FK 前的存量防御）
    if _table_exists(conn, "email_verification_codes") and _column_exists(conn, "email_verification_codes", "user_id"):
        _del("email_codes_user", """
            DELETE FROM email_verification_codes
            WHERE user_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM users u WHERE u.id = email_verification_codes.user_id)
        """)

    logger.info("迁移 081 删除孤儿行: %s", deleted)

    # 断言：声明过 FK 的表不允许再有任何违规
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            f"迁移 081 后仍存在 {len(violations)} 条 FK 违规（前 5 条: {violations[:5]}），拒绝继续"
        )


# ── 082 fts_rebuild_triggers ───────────────────────────────────────────────


def _migration_082_fts_rebuild_triggers(conn):
    """全量重建 question_fts 与 question_bank 对齐，并安装同步触发器。

    历史问题：sync_fts_entry/delete_fts_entry 无生产调用，FTS 只在迁移 025
    填充一次，删除/合并/清空路径均不清理 → 88 死 rowid、44 活跃题缺失。
    改用数据库级触发器根除漂移（查询侧仍按 deleted_at/duplicate_of 过滤）。
    """
    if _table_exists(conn, "question_bank") and _table_exists(conn, "question_fts"):
        conn.execute("DELETE FROM question_fts")
        conn.execute(
            "INSERT INTO question_fts (rowid, question, cat1, cat2, tags, ai_answer) "
            "SELECT id, question, cat1, cat2, tags, ai_answer FROM question_bank"
        )
        logger.info("迁移 082 重建 question_fts（%d 行）",
                    conn.execute("SELECT count(*) FROM question_fts").fetchone()[0])

    conn.execute("DROP TRIGGER IF EXISTS trg_question_fts_insert")
    conn.execute("DROP TRIGGER IF EXISTS trg_question_fts_update")
    conn.execute("DROP TRIGGER IF EXISTS trg_question_fts_delete")
    conn.execute(
        """
        CREATE TRIGGER trg_question_fts_insert AFTER INSERT ON question_bank BEGIN
            INSERT INTO question_fts (rowid, question, cat1, cat2, tags, ai_answer)
            VALUES (new.id, new.question, new.cat1, new.cat2, new.tags, new.ai_answer);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_question_fts_update AFTER UPDATE ON question_bank BEGIN
            DELETE FROM question_fts WHERE rowid = old.id;
            INSERT INTO question_fts (rowid, question, cat1, cat2, tags, ai_answer)
            VALUES (new.id, new.question, new.cat1, new.cat2, new.tags, new.ai_answer);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER trg_question_fts_delete AFTER DELETE ON question_bank BEGIN
            DELETE FROM question_fts WHERE rowid = old.id;
        END
        """
    )


# ── 083 index_housekeeping ─────────────────────────────────────────────────


def _migration_083_index_housekeeping(conn):
    """删除与表级/列级 UNIQUE 约束重复的显式唯一索引。"""
    _drop_index_if_exists(conn, "idx_practice_deck_key")
    _drop_index_if_exists(conn, "idx_uqr_user_question")


# ── 084 normalize_timestamps_jobs ──────────────────────────────────────────


_JOBS_NEW_SQL = """
CREATE TABLE jobs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    progress_current INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    progress_message TEXT DEFAULT '',
    result TEXT,
    created_by INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_until TEXT,
    arq_job_id TEXT,
    worker_id TEXT,
    last_error TEXT,
    started_at TEXT,
    idempotency_key TEXT,
    parent_job_id INTEGER,
    FOREIGN KEY (created_by) REFERENCES users(id)
)
"""

_JOBS_COLUMNS = [
    "id", "job_type", "status", "progress_current", "progress_total",
    "progress_message", "result", "created_by", "created_at", "updated_at",
    "completed_at", "attempts", "available_at", "locked_until", "arq_job_id",
    "worker_id", "last_error", "started_at", "idempotency_key", "parent_job_id",
]

_JOBS_SELECT = """
    id, job_type, status, progress_current, progress_total, progress_message,
    result, created_by, created_at, updated_at, completed_at, attempts,
    CASE WHEN available_at = '' THEN CURRENT_TIMESTAMP ELSE available_at END,
    locked_until, arq_job_id, worker_id, last_error, started_at, idempotency_key,
    parent_job_id
"""


def _migration_084_normalize_timestamps_jobs(conn):
    """重建 jobs（去 error 冗余列、available_at 去空串哨兵、默认 CURRENT_TIMESTAMP）。

    同时把 login_failures.locked_until（REAL epoch）与 mcp_sessions.updated_at
    （INTEGER epoch）统一为全库 ISO 文本；refresh_tokens.created_at 补 '+00:00'。
    """
    if _table_exists(conn, "jobs"):
        if _column_exists(conn, "jobs", "error"):
            _rebuild_table(conn, "jobs", _JOBS_NEW_SQL, _JOBS_COLUMNS, _JOBS_SELECT)
            for sql in [
                "CREATE INDEX idx_jobs_creator_type_status ON jobs(created_by, job_type, status)",
                "CREATE INDEX idx_jobs_dispatch ON jobs(job_type, status, available_at, locked_until)",
                "CREATE INDEX idx_jobs_parent ON jobs(parent_job_id, created_at)",
                "CREATE INDEX idx_jobs_status ON jobs(status)",
                "CREATE INDEX idx_jobs_type ON jobs(job_type)",
                "CREATE UNIQUE INDEX uq_jobs_idempotency ON jobs(job_type, idempotency_key) WHERE idempotency_key IS NOT NULL",
            ]:
                conn.execute(sql)
            logger.info("迁移 084 重建 jobs（移除 error 列，available_at 回填默认时间戳）")
        else:
            logger.info("迁移 084 jobs 已无 error 列，跳过重建")

    if _table_exists(conn, "login_failures") and _column_type(conn, "login_failures", "locked_until") == "REAL":
        _rebuild_table(
            conn,
            "login_failures",
            """
            CREATE TABLE login_failures_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                failure_count INTEGER DEFAULT 0,
                locked_until TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            ["id", "username", "failure_count", "locked_until", "updated_at"],
            """
            id, username, failure_count,
            CASE WHEN locked_until > 0 THEN datetime(locked_until, 'unixepoch') ELSE '' END,
            updated_at
            """,
        )
        logger.info("迁移 084 重建 login_failures（locked_until REAL→TEXT）")

    if _table_exists(conn, "mcp_sessions") and _column_type(conn, "mcp_sessions", "updated_at") == "INTEGER":
        _rebuild_table(
            conn,
            "mcp_sessions",
            """
            CREATE TABLE mcp_sessions_new (
                session_id TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            ["session_id", "data_json", "updated_at"],
            # 兼容两类历史存储 + 兜底坏值：
            #   - INTEGER/REAL Unix 秒 -> datetime(epoch,'unixepoch') 转 ISO 文本；
            #   - 已是 ISO 文本的 datetime 字符串 -> 原样保留（datetime(msg,'unixepoch') 对非整数会返回 NULL）；
            #   - NULL / 空串 / 纯空白 -> datetime('now') 回填当前时间，避免新表 NOT NULL 重建失败或留下语义无效的 ''。
            "session_id, data_json, "
            "CASE "
            "WHEN updated_at IS NULL OR trim(updated_at) = '' THEN datetime('now') "
            "WHEN typeof(updated_at) IN ('integer', 'real') THEN datetime(updated_at, 'unixepoch') "
            "ELSE updated_at END",
        )
        logger.info("迁移 084 重建 mcp_sessions（updated_at INTEGER→TEXT）")

    if _table_exists(conn, "refresh_tokens") and _column_exists(conn, "refresh_tokens", "created_at"):
        conn.execute(
            "UPDATE refresh_tokens SET created_at = replace(created_at, ' ', 'T') || '+00:00' "
            "WHERE created_at NOT LIKE '%T%' AND created_at != ''"
        )


# ── 085 add_fk_declarations ────────────────────────────────────────────────


def _migration_085_add_fk_declarations(conn):
    """重建 12 张表补齐 FK 声明与 ON DELETE 策略；users.username 回填小写。

    仅当目标 FK 缺失时重建（幂等）。重建期间 FK 约束由 runner 临时关闭。
    """
    # 1. interview_asked_questions
    if _table_exists(conn, "interview_asked_questions") and not _has_fk(conn, "interview_asked_questions", "conversation_id"):
        _rebuild_table(
            conn,
            "interview_asked_questions",
            """
            CREATE TABLE interview_asked_questions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                conversation_id TEXT NOT NULL,
                question_id INTEGER NOT NULL,
                asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE
            )
            """,
            ["id", "user_id", "conversation_id", "question_id", "asked_at"],
        )
        conn.execute("CREATE INDEX idx_iaq_conversation ON interview_asked_questions(conversation_id)")
        conn.execute("CREATE INDEX idx_iaq_user_question ON interview_asked_questions(user_id, question_id)")

    # 2. chat_tool_traces
    if _table_exists(conn, "chat_tool_traces") and not _has_fk(conn, "chat_tool_traces", "conversation_id"):
        _rebuild_table(
            conn,
            "chat_tool_traces",
            """
            CREATE TABLE chat_tool_traces_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                message_id INTEGER,
                react_step INTEGER NOT NULL,
                tool_name TEXT NOT NULL,
                sanitized_args_json TEXT NOT NULL,
                result_summary_json TEXT NOT NULL,
                elapsed_ms INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
                FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE SET NULL
            )
            """,
            ["id", "conversation_id", "message_id", "react_step", "tool_name",
             "sanitized_args_json", "result_summary_json", "elapsed_ms", "created_at"],
        )
        conn.execute("CREATE INDEX idx_ctt_conversation ON chat_tool_traces(conversation_id, created_at)")

    # 3. quality_issue
    if _table_exists(conn, "quality_issue") and not _has_fk(conn, "quality_issue", "qb_id"):
        _rebuild_table(
            conn,
            "quality_issue",
            """
            CREATE TABLE quality_issue_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qb_id INTEGER NOT NULL,
                variant_index INTEGER,
                issue_type TEXT NOT NULL,
                suggested_action TEXT NOT NULL,
                reason TEXT,
                suggested_value TEXT,
                confidence REAL,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                target_qb_id INTEGER DEFAULT NULL,
                new_cat2 TEXT DEFAULT NULL,
                review_version TEXT,
                review_task_id TEXT,
                trigger_reason TEXT,
                variant_key TEXT NOT NULL DEFAULT '',
                source_question TEXT DEFAULT NULL,
                source_cat2 TEXT DEFAULT NULL,
                issue_fingerprint TEXT,
                superseded_at TEXT,
                superseded_by INTEGER,
                FOREIGN KEY (qb_id) REFERENCES question_bank(id) ON DELETE CASCADE
            )
            """,
            ["id", "qb_id", "variant_index", "issue_type", "suggested_action", "reason",
             "suggested_value", "confidence", "status", "created_at", "reviewed_at",
             "reviewed_by", "target_qb_id", "new_cat2", "review_version", "review_task_id",
             "trigger_reason", "variant_key", "source_question", "source_cat2",
             "issue_fingerprint", "superseded_at", "superseded_by"],
        )
        conn.execute("CREATE INDEX idx_quality_issue_fingerprint ON quality_issue(issue_fingerprint)")
        conn.execute("CREATE INDEX idx_quality_issue_review_version ON quality_issue(qb_id, review_version, status)")
        conn.execute(
            "CREATE UNIQUE INDEX uq_quality_issue_active_fingerprint ON quality_issue(issue_fingerprint) "
            "WHERE issue_fingerprint IS NOT NULL AND status IN ('pending', 'approved')"
        )
        conn.execute(
            "CREATE UNIQUE INDEX uq_quality_issue_review_version ON quality_issue(qb_id, review_version, issue_type, variant_key) "
            "WHERE review_version IS NOT NULL"
        )

    # 4. email_verification_codes
    if _table_exists(conn, "email_verification_codes") and not _has_fk(conn, "email_verification_codes", "user_id"):
        _rebuild_table(
            conn,
            "email_verification_codes",
            """
            CREATE TABLE email_verification_codes_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                purpose TEXT NOT NULL,
                user_id INTEGER,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            ["id", "email", "code", "purpose", "user_id", "expires_at", "used", "created_at"],
        )
        conn.execute("CREATE INDEX idx_email_codes_email ON email_verification_codes(email, purpose, used)")

    # 5. analysis_queue
    if _table_exists(conn, "analysis_queue") and not _has_fk(conn, "analysis_queue", "question_detail_id"):
        _rebuild_table(
            conn,
            "analysis_queue",
            """
            CREATE TABLE analysis_queue_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                question_detail_id INTEGER,
                owner_id INTEGER DEFAULT NULL,
                FOREIGN KEY (interview_id) REFERENCES interview(id),
                FOREIGN KEY (question_detail_id) REFERENCES questions_detail(id) ON DELETE CASCADE,
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """,
            ["id", "interview_id", "status", "created_at", "processed_at", "question_detail_id", "owner_id"],
        )
        conn.execute("CREATE INDEX idx_aq_interview ON analysis_queue(interview_id)")
        conn.execute("CREATE INDEX idx_aq_owner ON analysis_queue(owner_id)")
        conn.execute("CREATE INDEX idx_aq_question_detail ON analysis_queue(question_detail_id)")
        conn.execute("CREATE INDEX idx_aq_status ON analysis_queue(status)")
        conn.execute("CREATE INDEX idx_aq_status_created ON analysis_queue(status, created_at)")

    # 6. chat_conversations（jd_id）
    if _table_exists(conn, "chat_conversations") and not _has_fk(conn, "chat_conversations", "jd_id"):
        _rebuild_table(
            conn,
            "chat_conversations",
            """
            CREATE TABLE chat_conversations_new (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL,
                title TEXT,
                jd_id INTEGER,
                resume_text TEXT,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                session_notes TEXT DEFAULT '',
                metadata TEXT DEFAULT '{}',
                job_position TEXT DEFAULT '',
                metadata_version INTEGER NOT NULL DEFAULT 0,
                session_notes_version INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (jd_id) REFERENCES jd(id) ON DELETE SET NULL
            )
            """,
            ["id", "user_id", "mode", "title", "jd_id", "resume_text", "status",
             "created_at", "updated_at", "session_notes", "metadata", "job_position",
             "metadata_version", "session_notes_version"],
        )
        conn.execute("CREATE INDEX idx_cc_updated ON chat_conversations(updated_at)")
        conn.execute("CREATE INDEX idx_cc_user_status ON chat_conversations(user_id, status)")
        conn.execute("CREATE INDEX idx_cc_user_status_position ON chat_conversations(user_id, status, job_position)")

    # 7. chat_memories（provenance 外键）
    if _table_exists(conn, "chat_memories") and not _has_fk(conn, "chat_memories", "source_turn_id"):
        _rebuild_table(
            conn,
            "chat_memories",
            """
            CREATE TABLE chat_memories_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'auto_extract',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                summary TEXT DEFAULT '',
                source_turn_id TEXT,
                source_job_id TEXT,
                memory_schema_version INTEGER NOT NULL DEFAULT 1,
                expires_at TIMESTAMP,
                content_hash TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (source_turn_id) REFERENCES chat_turns(id) ON DELETE SET NULL,
                FOREIGN KEY (source_job_id) REFERENCES chat_side_effect_jobs(id) ON DELETE SET NULL
            )
            """,
            ["id", "user_id", "memory_type", "content", "source", "is_active",
             "created_at", "updated_at", "summary", "source_turn_id", "source_job_id",
             "memory_schema_version", "expires_at", "content_hash"],
        )
        conn.execute("CREATE INDEX idx_chat_memories_provenance ON chat_memories(user_id, source_turn_id, content_hash)")
        conn.execute("CREATE INDEX idx_cmem_user_active ON chat_memories(user_id, is_active)")

    # 8. coding_problems（owner_id）
    if _table_exists(conn, "coding_problems") and not _has_fk(conn, "coding_problems", "owner_id"):
        _rebuild_table(
            conn,
            "coding_problems",
            """
            CREATE TABLE coding_problems_new (
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
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_id INTEGER,
                source_type TEXT DEFAULT 'seed',
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """,
            ["id", "title", "description", "difficulty", "tags", "expected_complexity",
             "source", "supported_languages", "is_active", "created_at", "updated_at",
             "owner_id", "source_type"],
        )
        conn.execute("CREATE INDEX idx_coding_problem_owner ON coding_problems(owner_id)")

    # 9. coding_submissions（ON DELETE 策略）
    if _table_exists(conn, "coding_submissions") and not _has_fk(conn, "coding_submissions", "parent_submission_id"):
        _rebuild_table(
            conn,
            "coding_submissions",
            """
            CREATE TABLE coding_submissions_new (
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
                scores TEXT DEFAULT '{}',
                reference_answer TEXT DEFAULT '',
                total_score REAL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (problem_id) REFERENCES coding_problems(id) ON DELETE CASCADE,
                FOREIGN KEY (parent_submission_id) REFERENCES coding_submissions(id) ON DELETE SET NULL
            )
            """,
            ["id", "user_id", "problem_id", "language", "code", "mode", "hint_round",
             "parent_submission_id", "ai_feedback", "error_categories", "is_passed",
             "created_at", "scores", "reference_answer", "total_score"],
        )
        conn.execute("CREATE INDEX idx_coding_sub_parent ON coding_submissions(parent_submission_id)")
        conn.execute("CREATE INDEX idx_coding_sub_problem ON coding_submissions(problem_id)")
        conn.execute("CREATE INDEX idx_coding_sub_user ON coding_submissions(user_id)")

    # 10. users（current_position_id ON DELETE SET NULL + username 小写回填）
    #     注意：users 自迁移 010 起就有内联 REFERENCES（无 ON DELETE），
    #     必须按 ON DELETE 动作而非 FK 是否存在来判断是否需要重建
    if _table_exists(conn, "users") and _fk_on_delete(conn, "users", "current_position_id") != "SET NULL":
        _rebuild_table(
            conn,
            "users",
            """
            CREATE TABLE users_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                bank_mode TEXT DEFAULT 'public',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                current_position_id INTEGER,
                updated_at TIMESTAMP,
                personal_position TEXT,
                email TEXT,
                share_default TEXT DEFAULT 'private',
                FOREIGN KEY (current_position_id) REFERENCES job_positions(id) ON DELETE SET NULL
            )
            """,
            ["id", "username", "password_hash", "is_admin", "bank_mode", "created_at",
             "current_position_id", "updated_at", "personal_position", "email", "share_default"],
        )
        conn.execute(
            "CREATE UNIQUE INDEX idx_users_email_unique ON users(email) WHERE email IS NOT NULL AND email != ''"
        )
    if _table_exists(conn, "users"):
        # username 归一化回填（存在大小写冲突则跳过并告警）
        collisions = conn.execute(
            "SELECT lower(username) FROM users GROUP BY lower(username) HAVING count(*) > 1"
        ).fetchall()
        if collisions:
            logger.warning("迁移 085 username 小写回填跳过（存在冲突: %s）",
                           [r[0] for r in collisions])
        else:
            cur = conn.execute(
                "UPDATE users SET username = lower(username), updated_at = CURRENT_TIMESTAMP "
                "WHERE username != lower(username)"
            )
            if cur.rowcount:
                logger.info("迁移 085 username 回填小写 %d 个用户", cur.rowcount)

    # 11. practice_decks（owner_id FK）
    if _table_exists(conn, "practice_decks") and not _has_fk(conn, "practice_decks", "owner_id"):
        _rebuild_table(
            conn,
            "practice_decks",
            """
            CREATE TABLE practice_decks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deck_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                deck_type TEXT NOT NULL DEFAULT 'system',
                criteria_json TEXT NOT NULL DEFAULT '{}',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                owner_id INTEGER,
                visibility TEXT NOT NULL DEFAULT 'private',
                FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            ["id", "deck_key", "name", "description", "deck_type", "criteria_json",
             "sort_order", "created_at", "updated_at", "owner_id", "visibility"],
        )
        conn.execute("CREATE INDEX idx_practice_decks_owner ON practice_decks(owner_id, sort_order)")

    # 12. taxonomy 公共分类（owner_id IS NULL）唯一索引兜底
    if _table_exists(conn, "taxonomy"):
        # UNIQUE(position_name, source, owner_id) 对 owner_id IS NULL 不约束（NULL 互异），
        # 迁移链种子曾产生重复公共分类 → 先清理（保留每组 MIN(id)），再建部分唯一索引
        dup_groups = conn.execute(
            "SELECT position_name, source FROM taxonomy WHERE owner_id IS NULL "
            "GROUP BY position_name, source HAVING count(*) > 1"
        ).fetchall()
        if dup_groups:
            conn.execute(
                "DELETE FROM taxonomy WHERE owner_id IS NULL AND id NOT IN ("
                "SELECT min(id) FROM taxonomy WHERE owner_id IS NULL "
                "GROUP BY position_name, source)"
            )
            logger.info("迁移 085 清理 taxonomy 公共分类种子重复 %d 组", len(dup_groups))
        _create_index_if_missing(
            conn,
            "CREATE UNIQUE INDEX uq_taxonomy_public ON taxonomy(position_name, source) WHERE owner_id IS NULL",
            "uq_taxonomy_public",
        )


# ── 086 drop_dead_columns_indexes ──────────────────────────────────────────


def _migration_086_drop_dead_columns_indexes(conn):
    """删除死列（vector / duplicate_of）并新增过期清理索引。"""
    _drop_index_if_exists(conn, "idx_qb_duplicate_of")
    if _table_exists(conn, "question_bank"):
        if _column_exists(conn, "question_bank", "vector"):
            conn.execute("ALTER TABLE question_bank DROP COLUMN vector")
        if _column_exists(conn, "question_bank", "duplicate_of"):
            conn.execute("ALTER TABLE question_bank DROP COLUMN duplicate_of")

    _create_index_if_missing(
        conn,
        "CREATE INDEX idx_email_codes_expires ON email_verification_codes(expires_at)",
        "idx_email_codes_expires",
    )
    _create_index_if_missing(
        conn,
        "CREATE INDEX idx_rt_expires ON refresh_tokens(expires_at)",
        "idx_rt_expires",
    )

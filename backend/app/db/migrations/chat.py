"""Chat domain migrations: 024-028, 037-046."""

import logging

from app.core.prompts import DEFAULT_TAXONOMY

logger = logging.getLogger("interview-boss")


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


def _migration_037_conversation_metadata(conn):
    """Add metadata column to chat_conversations for persisting active skill names etc."""
    cursor = conn.cursor()
    col_set = {row[1] for row in cursor.execute("PRAGMA table_info('chat_conversations')").fetchall()}
    if "metadata" not in col_set:
        conn.execute("ALTER TABLE chat_conversations ADD COLUMN metadata TEXT DEFAULT '{}'")
    logger.info("已添加 chat_conversations.metadata 列")


def _migration_038_chat_conversation_position(conn):
    """Add job_position to chat conversations and backfill existing rows."""
    cursor = conn.cursor()
    col_set = {row[1] for row in cursor.execute("PRAGMA table_info('chat_conversations')").fetchall()}
    if "job_position" not in col_set:
        conn.execute("ALTER TABLE chat_conversations ADD COLUMN job_position TEXT DEFAULT ''")

    fallback_row = conn.execute("SELECT value FROM user_profile WHERE key = 'current_job_position'").fetchone()
    fallback_position = fallback_row[0] if fallback_row and fallback_row[0] else DEFAULT_TAXONOMY["job_position"]

    rows = conn.execute(
        "SELECT c.id, u.personal_position, jp.name "
        "FROM chat_conversations c "
        "LEFT JOIN users u ON c.user_id = u.id "
        "LEFT JOIN job_positions jp ON u.current_position_id = jp.id "
        "WHERE c.job_position IS NULL OR c.job_position = ''"
    ).fetchall()
    for row in rows:
        position = row[1] or row[2] or fallback_position
        conn.execute("UPDATE chat_conversations SET job_position = ? WHERE id = ?", (position, row[0]))

    cursor.execute("PRAGMA index_list('chat_conversations')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_cc_user_status_position" not in indexes:
        conn.execute(
            "CREATE INDEX idx_cc_user_status_position "
            "ON chat_conversations(user_id, status, job_position)"
        )
    logger.info("已添加 chat_conversations.job_position 并回填历史会话")


def _migration_040_chat_tool_traces(conn):
    """Create chat_tool_traces table for tool call audit."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS chat_tool_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            message_id INTEGER,
            react_step INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            sanitized_args_json TEXT NOT NULL,
            result_summary_json TEXT NOT NULL,
            elapsed_ms INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor = conn.cursor()
    cursor.execute("PRAGMA index_list('chat_tool_traces')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_ctt_conversation" not in indexes:
        conn.execute(
            "CREATE INDEX idx_ctt_conversation ON chat_tool_traces(conversation_id, created_at)"
        )


def _migration_041_asked_questions(conn):
    """Cross-conversation question dedup: track which questions were asked per user."""
    conn.execute('''
        CREATE TABLE IF NOT EXISTS interview_asked_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor = conn.cursor()
    cursor.execute("PRAGMA index_list('interview_asked_questions')")
    indexes = [row[1] for row in cursor.fetchall()]
    if "idx_iaq_user_question" not in indexes:
        conn.execute(
            "CREATE INDEX idx_iaq_user_question "
            "ON interview_asked_questions(user_id, question_id)"
        )
    if "idx_iaq_conversation" not in indexes:
        conn.execute(
            "CREATE INDEX idx_iaq_conversation "
            "ON interview_asked_questions(conversation_id)"
        )
    logger.info("已创建 chat_tool_traces 表")


def _migration_043_chat_turns(conn):
    """Create durable chat turn fences for concurrent/cancellable requests."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_turns (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            client_request_id TEXT NOT NULL,
            fence INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'cancelled', 'completed', 'failed')),
            user_message_id INTEGER,
            assistant_message_id INTEGER,
            cancel_reason TEXT,
            error_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (user_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
            FOREIGN KEY (assistant_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
            UNIQUE (conversation_id, client_request_id)
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_turn_running_conversation "
        "ON chat_turns(conversation_id) WHERE status = 'running'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_turn_fence "
        "ON chat_turns(conversation_id, fence)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_turn_user_status "
        "ON chat_turns(user_id, status, created_at)"
    )
    logger.info("已创建 chat_turns 表")


def _migration_044_turn_replay_and_revision(conn):
    """Add request fingerprints and assistant revision linkage."""
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info('chat_turns')").fetchall()
    }
    if "request_fingerprint" not in columns:
        conn.execute(
            "ALTER TABLE chat_turns ADD COLUMN request_fingerprint TEXT NOT NULL DEFAULT ''"
        )
    if "revision_of_message_id" not in columns:
        conn.execute(
            "ALTER TABLE chat_turns ADD COLUMN revision_of_message_id INTEGER"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_turn_request_fingerprint "
        "ON chat_turns(conversation_id, request_fingerprint)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_turn_revision "
        "ON chat_turns(revision_of_message_id)"
    )
    logger.info("已添加 chat_turns request fingerprint 和 revision linkage")


def _migration_045_durable_side_effects(conn):
    """Add durable side-effect jobs, memory provenance, and optimistic versions."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info('chat_memories')").fetchall()}
    additions = {
        "source_turn_id": "TEXT",
        "source_job_id": "TEXT",
        "memory_schema_version": "INTEGER NOT NULL DEFAULT 1",
        "expires_at": "TIMESTAMP",
        "content_hash": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE chat_memories ADD COLUMN {name} {definition}")

    conversation_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('chat_conversations')").fetchall()
    }
    if "metadata_version" not in conversation_columns:
        conn.execute(
            "ALTER TABLE chat_conversations ADD COLUMN metadata_version INTEGER NOT NULL DEFAULT 0"
        )
    if "session_notes_version" not in conversation_columns:
        conn.execute(
            "ALTER TABLE chat_conversations ADD COLUMN session_notes_version INTEGER NOT NULL DEFAULT 0"
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_side_effect_jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            source_turn_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'dead_letter', 'skipped')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_at TIMESTAMP,
            finished_at TIMESTAMP,
            last_error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (source_turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE,
            UNIQUE(kind, source_turn_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_side_effect_jobs_ready "
        "ON chat_side_effect_jobs(status, available_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_memories_provenance "
        "ON chat_memories(user_id, source_turn_id, content_hash)"
    )


def _migration_046_structured_turns(conn):
    """Add candidate sets, lifecycle events, and assistant generations."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_candidate_sets (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            source TEXT NOT NULL,
            source_turn_id TEXT,
            items_json TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'available'
                CHECK (status IN ('available', 'consumed', 'expired', 'invalidated')),
            expires_at TIMESTAMP NOT NULL,
            selected_item_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (source_turn_id) REFERENCES chat_turns(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_candidate_sets_owner "
        "ON chat_candidate_sets(user_id, conversation_id, status, expires_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            event_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(turn_id, event_key),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interview_events_replay "
        "ON interview_events(conversation_id, id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS assistant_generations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            parent_generation_id TEXT,
            source_turn_id TEXT NOT NULL,
            contract_hash TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            visible INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_generation_id) REFERENCES assistant_generations(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_assistant_generations_visible "
        "ON assistant_generations(conversation_id, visible, created_at)"
    )

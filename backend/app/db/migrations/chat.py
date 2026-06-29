"""Chat domain migrations: 024, 025, 026, 027, 028, 037, 038."""

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

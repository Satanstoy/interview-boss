"""Jobs domain migrations: 009, 022, 036."""

import logging

logger = logging.getLogger("interview-boss")


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

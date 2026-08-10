"""Jobs domain migrations: 009, 022, 036."""

import logging

logger = logging.getLogger("interview-boss")


def _migration_009_analysis_queue(conn):
    """Create analysis_queue table + question_detail_id column + indexes."""
    cursor = conn.cursor()

    # ── 两阶段流水线队列表（基本单位：单个问题） ──
    conn.execute("""
        CREATE TABLE IF NOT EXISTS analysis_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER NOT NULL,
            question_detail_id INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (interview_id) REFERENCES interview(id)
        )
    """)
    # 迁移：为旧表添加 question_detail_id 列（必须在创建索引之前）
    aq_col_set = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    if "question_detail_id" not in aq_col_set:
        conn.execute("ALTER TABLE analysis_queue ADD COLUMN question_detail_id INTEGER")
    cursor.execute("PRAGMA index_list('analysis_queue')")
    aq_indexes = [row[1] for row in cursor.fetchall()]
    if "idx_aq_status" not in aq_indexes:
        conn.execute("CREATE INDEX idx_aq_status ON analysis_queue(status)")
    if "idx_aq_interview" not in aq_indexes:
        conn.execute("CREATE INDEX idx_aq_interview ON analysis_queue(interview_id)")
    if "idx_aq_question_detail" not in aq_indexes:
        conn.execute(
            "CREATE INDEX idx_aq_question_detail ON analysis_queue(question_detail_id)"
        )


def _migration_022_jobs_table(conn):
    """Add jobs table for tracking async background tasks."""
    conn.execute("""
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
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")


def _migration_036_job_payloads(conn):
    """Create job_payloads table for storing submit import task payloads.
    Add composite index on jobs for active submit job queries."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS job_payloads (
            job_id INTEGER PRIMARY KEY,
            payload TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_creator_type_status ON jobs(created_by, job_type, status)"
    )
    logger.info("已创建 job_payloads 表和 jobs 复合索引")


def _migration_049_analysis_queue_owner(conn):
    """Add owner_id to analysis_queue for personal/public path unification.

    owner_id IS NULL → public queue (processed by cluster_batch as before).
    owner_id = user_id → personal queue (cluster_batch matches only within
    that user's existing clusters, never mixing with public or other users).
    """
    aq_cols = {
        row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    if "owner_id" not in aq_cols:
        conn.execute(
            "ALTER TABLE analysis_queue ADD COLUMN owner_id INTEGER DEFAULT NULL"
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aq_owner ON analysis_queue(owner_id)")
    logger.info("migration_049: analysis_queue.owner_id 列已就绪")


def _migration_074_durable_job_lifecycle(conn):
    """Add durable dispatch/lease fields for long-running application jobs.

    ``jobs`` is the source of truth; ARQ only transports execution.  Existing
    jobs retain their current status and gain safe defaults so this migration
    does not replay or rewrite historical results.
    """
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('jobs')").fetchall()
    }
    additions = {
        "attempts": "INTEGER NOT NULL DEFAULT 0",
        # SQLite does not allow a non-constant default in ALTER TABLE ADD COLUMN.
        # We normalize the empty compatibility value immediately below.
        "available_at": "TEXT NOT NULL DEFAULT ''",
        "locked_until": "TEXT",
        "arq_job_id": "TEXT",
        "worker_id": "TEXT",
        "last_error": "TEXT",
        "started_at": "TEXT",
        "idempotency_key": "TEXT",
    }
    for name, definition in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")

    conn.execute(
        "UPDATE jobs SET available_at = CURRENT_TIMESTAMP "
        "WHERE available_at IS NULL OR available_at = ''"
    )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_dispatch "
        "ON jobs(job_type, status, available_at, locked_until)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_jobs_idempotency "
        "ON jobs(job_type, idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    logger.info("migration_074: jobs durable dispatch/lease fields are ready")


def _migration_075_job_retry_lineage(conn):
    """Track retry attempts without replacing the original job record.

    A retry is a new durable job that reuses the original payload.  Keeping the
    lineage lets contextual UIs show only the latest attempt while operators
    retain the full audit trail.
    """
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info('jobs')").fetchall()
    }
    if "parent_job_id" not in columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN parent_job_id INTEGER")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_parent ON jobs(parent_job_id, created_at)"
    )
    logger.info("migration_075: jobs retry lineage is ready")


def _migration_050_pipeline_metrics(conn):
    """Create pipeline_metrics table for observability.

    Records every cluster_batch / compaction / extract run with timing,
    counts, and LLM call stats so we can analyse bottlenecks offline.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            job_position TEXT DEFAULT '',
            owner_id INTEGER,
            questions_in INTEGER DEFAULT 0,
            matched INTEGER DEFAULT 0,
            new_clusters INTEGER DEFAULT 0,
            merged INTEGER DEFAULT 0,
            llm_calls INTEGER DEFAULT 0,
            elapsed_seconds REAL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pm_op ON pipeline_metrics(operation)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pm_created ON pipeline_metrics(created_at)"
    )
    logger.info("migration_050: pipeline_metrics 表已就绪")

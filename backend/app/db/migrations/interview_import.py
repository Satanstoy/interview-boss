"""MCP interview import staging and publication tables."""

import logging

logger = logging.getLogger("interview-boss")


def _migration_080_interview_import(conn):
    """Persist resumable external interview imports independently of MCP sessions."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_imports (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            client_request_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            job_position TEXT NOT NULL DEFAULT '',
            company TEXT NOT NULL DEFAULT '',
            interview_round TEXT NOT NULL DEFAULT '',
            recruiting_season TEXT NOT NULL DEFAULT '',
            resume_id INTEGER,
            resume_text TEXT,
            context_json TEXT NOT NULL DEFAULT '{}',
            external_analysis_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'uploading'
                CHECK (status IN ('uploading', 'queued', 'processing', 'completed', 'failed')),
            job_id INTEGER,
            conversation_id TEXT,
            report_json TEXT,
            error_code TEXT,
            error_message TEXT,
            analysis_attempt INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            UNIQUE(user_id, client_request_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interview_imports_user_status "
        "ON interview_imports(user_id, status, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interview_imports_conversation "
        "ON interview_imports(conversation_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_import_chunks (
            import_id TEXT NOT NULL,
            stream_type TEXT NOT NULL
                CHECK (stream_type IN ('turns', 'transcript')),
            chunk_index INTEGER NOT NULL,
            total_chunks INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(import_id, stream_type, chunk_index),
            FOREIGN KEY (import_id) REFERENCES interview_imports(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_interview_import_chunks_import "
        "ON interview_import_chunks(import_id, stream_type, chunk_index)"
    )
    logger.info("migration_080: interview import staging tables are ready")

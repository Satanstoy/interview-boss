"""Public contribution workflow migrations.

The contribution request is deliberately separate from ``question_bank`` and
from the user's private source rows.  A request owns an immutable snapshot;
review edits are stored as a projection, so a later edit to the private source
cannot silently change what an administrator approved.
"""

import logging

logger = logging.getLogger("interview-boss")


def _migration_102_public_contribution_workflow(conn):
    """Create the interview/JD public contribution request state machine."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_contribution_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL
                CHECK (source_type IN ('interview', 'jd')),
            source_id INTEGER NOT NULL,
            requester_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_review'
                CHECK (status IN (
                    'pending_review', 'changes_requested',
                    'approved_for_processing', 'queued', 'processing',
                    'published', 'partially_published', 'rejected',
                    'withdrawn', 'failed'
                )),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            review_json TEXT NOT NULL DEFAULT '{}',
            public_interview_id INTEGER,
            public_jd_id INTEGER,
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            error_message TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (requester_id) REFERENCES users(id),
            FOREIGN KEY (reviewed_by) REFERENCES users(id),
            FOREIGN KEY (public_interview_id) REFERENCES interview(id),
            FOREIGN KEY (public_jd_id) REFERENCES jd(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_contribution_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            source_item_type TEXT NOT NULL
                CHECK (source_item_type IN ('question', 'jd_document')),
            source_item_id INTEGER,
            ordinal INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_review'
                CHECK (status IN (
                    'pending_review', 'approved_for_processing', 'queued',
                    'processing', 'published', 'rejected', 'failed'
                )),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            review_json TEXT NOT NULL DEFAULT '{}',
            public_detail_id INTEGER,
            error_message TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(request_id, ordinal),
            FOREIGN KEY (request_id) REFERENCES public_contribution_requests(id)
                ON DELETE CASCADE,
            FOREIGN KEY (public_detail_id) REFERENCES questions_detail(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_contribution_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            actor_id INTEGER,
            action TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES public_contribution_requests(id)
                ON DELETE CASCADE,
            FOREIGN KEY (actor_id) REFERENCES users(id)
        )
        """
    )

    # Existing analysis_queue rows remain valid.  The nullable request link
    # lets approved contributions be traced without changing ordinary public
    # uploads or old rebuild jobs.
    aq_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    if "contribution_request_id" not in aq_columns:
        conn.execute(
            "ALTER TABLE analysis_queue ADD COLUMN contribution_request_id INTEGER"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_public_contribution_request_status "
        "ON public_contribution_requests(status, source_type, updated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_public_contribution_request_owner "
        "ON public_contribution_requests(requester_id, created_at)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_public_contribution_active_source "
        "ON public_contribution_requests(source_type, source_id, requester_id) "
        "WHERE status IN ('pending_review', 'changes_requested', "
        "'approved_for_processing', 'queued', 'processing')"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_public_contribution_items_status "
        "ON public_contribution_items(request_id, status, ordinal)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_analysis_queue_contribution "
        "ON analysis_queue(contribution_request_id, status)"
    )
    logger.info("migration_102: public contribution workflow is ready")


def _migration_103_public_contribution_retry_scope(conn):
    """Keep failed requests idempotent while their queue rows are retryable."""
    conn.execute("DROP INDEX IF EXISTS uq_public_contribution_active_source")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_public_contribution_active_source "
        "ON public_contribution_requests(source_type, source_id, requester_id) "
        "WHERE status IN ('pending_review', 'changes_requested', "
        "'approved_for_processing', 'queued', 'processing', 'failed')"
    )
    logger.info("migration_103: failed contribution requests remain retry-idempotent")

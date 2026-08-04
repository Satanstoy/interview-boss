"""Interview-distribution fact storage migration."""

from __future__ import annotations

import logging

from app.services.interview_distribution import map_dimension, map_question_type


logger = logging.getLogger("interview-boss")


def _migration_042_interview_distribution(conn):
    """Add linked typed facts and tables used to publish distribution defaults."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(questions_detail)")}
    if "interview_id" not in columns:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN interview_id INTEGER")
    if "question_type" not in columns:
        conn.execute(
            "ALTER TABLE questions_detail ADD COLUMN question_type TEXT NOT NULL DEFAULT 'unclassified'"
        )
    if "dimension" not in columns:
        conn.execute(
            "ALTER TABLE questions_detail ADD COLUMN dimension TEXT NOT NULL DEFAULT 'unclassified'"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qd_interview_question_type "
        "ON questions_detail(interview_id, question_type)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_interview_distribution_preferences (
            user_id INTEGER NOT NULL,
            job_position TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'system_default',
            target_question_count INTEGER,
            custom_distribution TEXT,
            selected_experience_id INTEGER,
            style_strength TEXT NOT NULL DEFAULT 'normal',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, job_position)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_distribution_stats (
            scope TEXT NOT NULL,
            job_position TEXT NOT NULL,
            question_type TEXT NOT NULL,
            stats_version INTEGER NOT NULL,
            posterior_mean_ratio REAL NOT NULL,
            posterior_alpha REAL NOT NULL,
            raw_question_count INTEGER NOT NULL,
            sample_interview_count INTEGER NOT NULL,
            sample_question_count INTEGER NOT NULL,
            recommended_total_count INTEGER NOT NULL,
            dispersion REAL NOT NULL,
            confidence TEXT NOT NULL,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, job_position, question_type, stats_version)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_distribution_refresh_jobs (
            scope TEXT NOT NULL,
            job_position TEXT NOT NULL,
            requested_source_version TEXT NOT NULL,
            published_source_version TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_at TIMESTAMP,
            last_error TEXT,
            next_retry_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, job_position)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS interview_distribution_stat_exclusions (
            stats_version INTEGER NOT NULL,
            scope TEXT NOT NULL,
            job_position TEXT NOT NULL,
            interview_id INTEGER NOT NULL,
            exclusion_reason TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stats_version, scope, job_position, interview_id)
        )
        """
    )

    _backfill_linked_typed_details(conn)


def _backfill_linked_typed_details(conn) -> None:
    """Link unambiguous active details, then classify every linked active fact."""
    unlinked_rows = conn.execute(
        """
        SELECT qd.id, qd.url
        FROM questions_detail qd
        WHERE qd.interview_id IS NULL AND qd.deleted_at IS NULL
          AND qd.url IS NOT NULL AND qd.url != ''
        """
    ).fetchall()
    ambiguous_urls: set[str] = set()
    for row in unlinked_rows:
        interviews = conn.execute(
            """
            SELECT id FROM interview
            WHERE url = ? AND deleted_at IS NULL
            """,
            (row["url"],),
        ).fetchall()
        if len(interviews) == 1:
            conn.execute(
                "UPDATE questions_detail SET interview_id = ? WHERE id = ?",
                (interviews[0]["id"], row["id"]),
            )
        elif len(interviews) > 1:
            ambiguous_urls.add(row["url"])

    if ambiguous_urls:
        logger.warning(
            "interview_distribution_backfill_ambiguous_urls",
            extra={"ambiguous_url_count": len(ambiguous_urls)},
        )

    details = conn.execute(
        """
        SELECT id, cat1, cat2, tags, question
        FROM questions_detail
        WHERE interview_id IS NOT NULL AND deleted_at IS NULL
        """
    ).fetchall()
    for detail in details:
        question_type = map_question_type(
            detail["cat1"], detail["cat2"], detail["tags"], detail["question"]
        )
        conn.execute(
            "UPDATE questions_detail SET question_type = ?, dimension = ? WHERE id = ?",
            (question_type.value, map_dimension(question_type), detail["id"]),
        )

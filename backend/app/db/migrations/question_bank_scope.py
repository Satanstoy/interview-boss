"""Question-bank scope invariants and legacy detail quarantine."""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def _migration_108_question_bank_scope(conn):
    """Expose derived scope fields and reject unknown question-bank states."""
    columns = {row[1] for row in conn.execute("PRAGMA table_xinfo('question_bank')").fetchall()}
    if "visibility" not in columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN visibility TEXT GENERATED ALWAYS AS "
            "(CASE WHEN owner_id IS NULL THEN 'public' ELSE 'private' END) VIRTUAL"
        )
    if "review_state" not in columns:
        conn.execute(
            "ALTER TABLE question_bank ADD COLUMN review_state TEXT GENERATED ALWAYS AS "
            "(status) VIRTUAL"
        )

    invalid = conn.execute(
        "SELECT id, status FROM question_bank "
        "WHERE status IS NULL OR status NOT IN ('pending', 'approved') LIMIT 1"
    ).fetchone()
    if invalid:
        raise ValueError(
            f"question_bank contains unsupported status for id={invalid[0]}: {invalid[1]!r}"
        )

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qb_visibility_review_state "
        "ON question_bank(visibility, review_state, job_position, deleted_at)"
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_question_bank_scope_insert
        BEFORE INSERT ON question_bank
        WHEN NEW.status IS NULL OR NEW.status NOT IN ('pending', 'approved')
        BEGIN
            SELECT RAISE(ABORT, 'question_bank status must be pending or approved');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS trg_question_bank_scope_update
        BEFORE UPDATE OF status ON question_bank
        WHEN NEW.status IS NULL OR NEW.status NOT IN ('pending', 'approved')
        BEGIN
            SELECT RAISE(ABORT, 'question_bank status must be pending or approved');
        END
        """
    )


def _migration_109_question_detail_scope_guard(conn):
    """Link uniquely identifiable legacy details and quarantine the rest."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS question_detail_scope_quarantine (
            detail_id INTEGER PRIMARY KEY
                REFERENCES questions_detail(id) ON DELETE CASCADE,
            url TEXT NOT NULL DEFAULT '',
            reason TEXT NOT NULL
                CHECK (reason IN ('missing_interview', 'ambiguous_interview')),
            candidate_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_qd_scope_quarantine_reason "
        "ON question_detail_scope_quarantine(reason, created_at)"
    )

    detail_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('questions_detail')").fetchall()
    }
    owner_select = ", owner_id" if "owner_id" in detail_columns else ""
    rows = conn.execute(
        "SELECT id, url" + owner_select + " FROM questions_detail "
        "WHERE interview_id IS NULL AND deleted_at IS NULL"
    ).fetchall()

    for row in rows:
        detail_id = row[0]
        url = row[1] or ""
        detail_owner_id = row[2] if owner_select else None
        candidates = []
        if url:
            sql = "SELECT id FROM interview WHERE url = ? AND deleted_at IS NULL"
            params: list[object] = [url]
            if detail_owner_id is not None:
                sql += " AND owner_id = ?"
                params.append(detail_owner_id)
            candidates = conn.execute(sql, params).fetchall()

        if len(candidates) == 1:
            conn.execute(
                "UPDATE questions_detail SET interview_id = ? WHERE id = ?",
                (candidates[0][0], detail_id),
            )
            conn.execute(
                "DELETE FROM question_detail_scope_quarantine WHERE detail_id = ?",
                (detail_id,),
            )
            continue

        reason = "missing_interview" if not candidates else "ambiguous_interview"
        conn.execute(
            """
            INSERT INTO question_detail_scope_quarantine
                (detail_id, url, reason, candidate_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(detail_id) DO UPDATE SET
                url = excluded.url,
                reason = excluded.reason,
                candidate_count = excluded.candidate_count
            """,
            (detail_id, url, reason, len(candidates)),
        )

    logger.info(
        "question_detail_scope_guard completed: quarantined=%s",
        conn.execute("SELECT COUNT(*) FROM question_detail_scope_quarantine").fetchone()[0],
    )

"""Stable identities for quality-review findings.

``review_version`` identifies one evaluation snapshot.  It must not identify
the human-review item itself: a cluster can change while the same original
question remains the same finding.  This module keeps that distinction in one
place so migrations and all review generators use identical fingerprints.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from typing import Any


QUALITY_ISSUE_STATUSES = ("pending", "approved", "superseded", "done", "rejected")
ACTIVE_QUALITY_ISSUE_STATUSES = ("pending", "approved")


def normalize_issue_subject(value: Any) -> str:
    """Normalize exact source text for a stable identity, not semantic matching."""

    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def build_issue_fingerprint(
    issue_type: str,
    subject: Any,
    *,
    qb_id: int | None = None,
) -> str:
    """Return a stable fingerprint independent of review_version or index.

    Mismerge/unmerged findings are keyed by their original question text so
    the same question cannot produce a second active review item after a
    cluster mutation.  Representative findings are scoped to the cluster,
    while the representative text makes a materially changed question a new
    finding.
    """

    normalized = normalize_issue_subject(subject)
    if not normalized:
        normalized = f"qb:{qb_id or 0}"
    if issue_type in ("weak_representative", "new_representative"):
        identity = f"{issue_type}\x00qb:{qb_id or 0}\x00{normalized}"
    else:
        identity = f"{issue_type}\x00source:{normalized}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def issue_subject_from_row(row: Any, conn) -> str:
    """Recover the source subject used to fingerprint a historical row."""

    issue_type = str(_row_value(row, "issue_type", ""))
    if issue_type in ("weak_representative", "new_representative"):
        qb = conn.execute(
            "SELECT question FROM question_bank WHERE id = ?",
            (_row_value(row, "qb_id"),),
        ).fetchone()
        return str(qb["question"] if qb else "")

    source_question = str(_row_value(row, "source_question", "") or "").strip()
    if source_question:
        return source_question

    qb = conn.execute(
        "SELECT question, original_questions FROM question_bank WHERE id = ?",
        (_row_value(row, "qb_id"),),
    ).fetchone()
    variant_index = _row_value(row, "variant_index")
    if qb and variant_index is not None:
        try:
            variants = json.loads(qb["original_questions"] or "[]")
        except (TypeError, ValueError):
            variants = []
        if isinstance(variants, list) and 0 <= variant_index < len(variants):
            return str(variants[variant_index] or "")

    # A stale historical row may no longer have its variant in question_bank.
    # Keep it deterministic without pretending that its old text is known.
    variant_key = str(_row_value(row, "variant_key", "") or "")
    if variant_key:
        return f"qb:{_row_value(row, 'qb_id')}:variant:{variant_key}"
    return str(qb["question"] if qb else "")


def issue_fingerprint_from_row(row: Any, conn) -> str:
    return build_issue_fingerprint(
        str(_row_value(row, "issue_type", "")),
        issue_subject_from_row(row, conn),
        qb_id=_row_value(row, "qb_id"),
    )


def find_existing_issue(conn, fingerprint: str):
    """Return the canonical historical row for a fingerprint, if present."""

    return conn.execute(
        "SELECT * FROM quality_issue WHERE issue_fingerprint = ? "
        "ORDER BY CASE status "
        "WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 WHEN 'done' THEN 2 "
        "WHEN 'rejected' THEN 3 WHEN 'superseded' THEN 4 ELSE 5 END, id",
        (fingerprint,),
    ).fetchone()


def update_issue_from_observation(conn, issue_id: int, values: dict[str, Any]) -> None:
    """Refresh an old superseded/pending row with the latest scan evidence."""

    assignments = [
        "variant_index = ?",
        "issue_type = ?",
        "suggested_action = ?",
        "reason = ?",
        "suggested_value = ?",
        "confidence = ?",
        "target_qb_id = ?",
        "new_cat2 = ?",
        "source_question = ?",
        "source_cat2 = ?",
        "review_version = ?",
        "review_task_id = ?",
        "trigger_reason = ?",
        "variant_key = ?",
        "issue_fingerprint = ?",
        "status = 'pending'",
        "reviewed_at = NULL",
        "reviewed_by = NULL",
        "superseded_at = NULL",
        "superseded_by = NULL",
    ]
    params = [
        values.get("variant_index"),
        values["issue_type"],
        values["suggested_action"],
        values.get("reason"),
        values.get("suggested_value"),
        values.get("confidence"),
        values.get("target_qb_id"),
        values.get("new_cat2"),
        values.get("source_question"),
        values.get("source_cat2"),
        values.get("review_version"),
        values.get("review_task_id"),
        values.get("trigger_reason"),
        values.get("variant_key", ""),
        values["issue_fingerprint"],
        issue_id,
    ]
    conn.execute(
        "UPDATE quality_issue SET " + ", ".join(assignments) + " WHERE id = ?",
        params,
    )


def upsert_quality_issue(conn, values: dict[str, Any]) -> tuple[int | None, bool]:
    """Create one review item or reuse its stable historical row.

    Resolved findings are intentionally not reopened by an ordinary scan.  A
    future explicit force-review path can reset the same row if needed; a
    scheduled scan must never create a fresh card for an already decided
    question.
    """

    existing = find_existing_issue(conn, values["issue_fingerprint"])
    if existing:
        if existing["status"] in ("done", "rejected"):
            return existing["id"], False
        if existing["status"] == "approved":
            # An approval belongs to one evidence snapshot.  A newer scan
            # must reopen that same row for fresh evidence; an identical scan
            # must leave the human decision untouched.
            if (
                not values.get("review_version")
                or existing["review_version"] == values["review_version"]
            ):
                return existing["id"], False
        was_pending = existing["status"] == "pending"
        update_issue_from_observation(conn, existing["id"], values)
        return existing["id"], not was_pending

    columns = [
        "qb_id", "variant_index", "issue_type", "suggested_action", "reason",
        "suggested_value", "confidence", "status", "created_at", "target_qb_id",
        "new_cat2", "source_question", "source_cat2", "review_version",
        "review_task_id", "trigger_reason", "variant_key", "issue_fingerprint",
    ]
    params = [values.get(column) for column in columns if column != "created_at"]
    placeholders = ", ".join("?" if column != "created_at" else "datetime('now')" for column in columns)
    try:
        cursor = conn.execute(
            "INSERT INTO quality_issue (" + ", ".join(columns) + ") VALUES (" + placeholders + ")",
            params,
        )
    except sqlite3.IntegrityError:
        # Two workers can evaluate the same cluster concurrently.  The
        # partial unique index is the final race-safe guard; if it won the
        # race, report the existing canonical row instead of retrying it.
        existing = find_existing_issue(conn, values["issue_fingerprint"])
        if existing:
            return existing["id"], False
        raise
    return cursor.lastrowid, True

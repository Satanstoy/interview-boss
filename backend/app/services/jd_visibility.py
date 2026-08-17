"""Centralized visibility rules for job-description reads."""

from __future__ import annotations

import sqlite3


def load_visible_jd(
    conn: sqlite3.Connection, jd_id: int | None, user_id: int | None
):
    """Return a JD visible to ``user_id`` or ``None``.

    A JD is visible when it is owned by the current user, or when it is a
    non-deleted public record explicitly approved for sharing.
    """
    if not jd_id:
        return None
    return conn.execute(
        "SELECT id, company, job_title, salary, tech_stack, season, job_position "
        "FROM jd "
        "WHERE id = ? AND deleted_at IS NULL "
        "AND (owner_id = ? OR (owner_id IS NULL AND status = 'approved'))",
        (jd_id, user_id),
    ).fetchone()


def format_jd_text(row) -> str:
    """Convert the persisted JD fields into the prompt context string."""
    if row is None:
        return ""
    labels = (
        ("公司", row["company"]),
        ("岗位", row["job_title"]),
        ("薪资", row["salary"]),
        ("技术栈", row["tech_stack"]),
        ("招聘季", row["season"]),
        ("岗位方向", row["job_position"]),
    )
    return "\n".join(f"{label}：{value}" for label, value in labels if value)

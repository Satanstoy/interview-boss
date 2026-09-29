"""AC-005 / UR-005：原题与规范题关联（resolution）。

契约（contracts.md §1.5）：

- 私人原题命中公共规范题：保留私人明细 + resolution，**不改**公共 sources/frequency；
- ``mine`` 视图用 EXISTS 关联展示本人引用的公共题，仅本人能看到自己的来源关联；
- 公共规范题失效/重聚类时，同事务把 resolution 置 invalidated，原题不删除，
  可重新关联；
- 每个明细最多一个当前（未失效）resolution；scope 归属必须自洽。
"""

from __future__ import annotations

import sqlite3


class ResolutionConflict(Exception):
    code = "STATE_CONFLICT"


def _validate_scope(*, occurrence_scope: str, occurrence_owner_id, canonical_scope=None):
    if occurrence_scope not in ("private", "public"):
        raise ValueError(f"不合法的 occurrence_scope: {occurrence_scope!r}")
    if occurrence_scope == "private" and occurrence_owner_id is None:
        raise ValueError("private 原题必须有 owner")
    if occurrence_scope == "public" and occurrence_owner_id is not None:
        raise ValueError("public 原题不得有 owner")


def record_resolution(
    conn,
    *,
    detail_id: int,
    occurrence_scope: str,
    occurrence_owner_id,
    canonical_id,
    canonical_scope: str,
    status: str,
    pipeline_version: str,
    taxonomy_version: str | None = None,
    input_version: int = 1,
    confidence=None,
    reason: str | None = None,
    invalidate_previous: bool = True,
):
    """登记一条原题→规范题关联；同一明细只保留一个当前 resolution。"""

    _validate_scope(
        occurrence_scope=occurrence_scope,
        occurrence_owner_id=occurrence_owner_id,
    )
    if status in ("matched", "created"):
        if canonical_id is None:
            raise ValueError(f"status={status} 必须提供 canonical_id")
        if canonical_scope not in ("private", "public"):
            raise ValueError(f"不合法的 canonical_scope: {canonical_scope!r}")
        # 私人原题只能挂本人私人题或已发布的公共题；公共原题只能挂公共题
        if occurrence_scope == "private":
            if canonical_scope == "private":
                row = conn.execute(
                    "SELECT owner_id FROM question_bank WHERE id = ?", (canonical_id,)
                ).fetchone()
                if row is None or row["owner_id"] != occurrence_owner_id:
                    raise ResolutionConflict("私人原题只能关联本人的私人规范题")
        else:
            if canonical_scope != "public":
                raise ResolutionConflict("公共原题只能关联公共规范题")
    elif status not in ("needs_review", "failed", "invalidated"):
        raise ValueError(f"不合法的 resolution 状态: {status!r}")

    if invalidate_previous:
        conn.execute(
            "UPDATE question_resolutions SET invalidated_at = CURRENT_TIMESTAMP "
            "WHERE detail_id = ? AND invalidated_at IS NULL",
            (detail_id,),
        )
    cursor = conn.execute(
        "INSERT INTO question_resolutions (detail_id, occurrence_scope, "
        "occurrence_owner_id, canonical_id, canonical_scope, status, "
        "taxonomy_version, pipeline_version, input_version, confidence, reason) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            detail_id,
            occurrence_scope,
            occurrence_owner_id,
            canonical_id,
            canonical_scope,
            status,
            taxonomy_version,
            pipeline_version,
            input_version,
            confidence,
            reason,
        ),
    )
    return conn.execute(
        "SELECT * FROM question_resolutions WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()


def get_current_resolution(conn, *, detail_id: int):
    return conn.execute(
        "SELECT * FROM question_resolutions WHERE detail_id = ? AND invalidated_at IS NULL",
        (detail_id,),
    ).fetchone()


def invalidate_resolutions_for_canonical(conn, *, canonical_id: int, reason: str) -> int:
    """公共规范题失效/重聚类时同事务失效其关联；原题保留待重新关联。"""

    cursor = conn.execute(
        "UPDATE question_resolutions SET invalidated_at = CURRENT_TIMESTAMP, "
        "reason = ? WHERE canonical_id = ? AND invalidated_at IS NULL",
        (reason, canonical_id),
    )
    return cursor.rowcount


def list_mine_canonical_ids(conn, *, user_id: int) -> list[int]:
    """``mine`` 视图：本人私人规范题 + 本人原题引用的公共规范题（EXISTS 去重）。"""

    rows = conn.execute(
        "SELECT DISTINCT r.canonical_id AS canonical_id "
        "FROM question_resolutions r "
        "WHERE r.invalidated_at IS NULL AND r.occurrence_owner_id = ? "
        "AND r.canonical_id IS NOT NULL "
        "UNION "
        "SELECT qb.id AS canonical_id FROM question_bank qb "
        "WHERE qb.owner_id = ? AND qb.deleted_at IS NULL",
        (user_id, user_id),
    ).fetchall()
    return sorted(int(row["canonical_id"]) for row in rows)


def resolution_source_visibility(conn, *, user_id: int, canonical_id: int) -> dict:
    """该用户是否可看到自己的来源关联（他人一律不可见）。"""

    rows = conn.execute(
        "SELECT r.detail_id, r.occurrence_owner_id FROM question_resolutions r "
        "WHERE r.canonical_id = ? AND r.invalidated_at IS NULL",
        (canonical_id,),
    ).fetchall()
    own = [row for row in rows if row["occurrence_owner_id"] == user_id]
    return {
        "has_own_source": bool(own),
        "visible_detail_ids": sorted(int(row["detail_id"]) for row in own),
    }

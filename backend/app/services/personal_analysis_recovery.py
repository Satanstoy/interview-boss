"""Business rules for owner recovery of rootless personal analysis rows."""


class PersonalAnalysisRetryError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


MAX_PERSONAL_FAILURE_REFRESH_ITEMS = 5000
MAX_SQLITE_INTEGER = 2**63 - 1


_PERSONAL_FAILURE_FILTERS = (
    "aq.owner_id = ? AND aq.root_import_id IS NULL "
    "AND aq.contribution_request_id IS NULL AND aq.status = 'failed' "
    "AND i.owner_id = aq.owner_id AND i.status = 'approved' "
    "AND i.deleted_at IS NULL AND qd.deleted_at IS NULL "
    "AND qd.interview_id = aq.interview_id AND qd.import_id IS NULL"
)
_PERSONAL_FAILURE_SELECT = (
    "SELECT aq.id AS queue_id, aq.interview_id, aq.created_at, "
    "i.company, i.job_position, qd.question "
    "FROM analysis_queue aq "
    "JOIN interview i ON i.id = aq.interview_id "
    "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
)


def _personal_failure_items(rows):
    return [
        {**dict(row), "status": "failed", "allowed_actions": ["retry"]}
        for row in rows
    ]


def oldest_pending_personal_rootless_owner(conn) -> int | None:
    """Return an owner whose durable rootless row still needs scheduling."""

    row = conn.execute(
        "SELECT aq.owner_id FROM analysis_queue aq "
        "JOIN interview i ON i.id = aq.interview_id "
        "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
        "WHERE aq.status = 'pending' AND aq.owner_id IS NOT NULL "
        "AND aq.root_import_id IS NULL AND aq.contribution_request_id IS NULL "
        "AND i.owner_id = aq.owner_id AND i.status = 'approved' "
        "AND i.deleted_at IS NULL AND qd.deleted_at IS NULL "
        "AND qd.interview_id = aq.interview_id AND qd.import_id IS NULL "
        "ORDER BY aq.created_at, aq.id LIMIT 1"
    ).fetchone()
    return int(row["owner_id"]) if row else None


def list_personal_analysis_failures(conn, *, owner_id: int, page: int, page_size: int):
    """Return readable, failed personal rows owned by ``owner_id`` only."""

    offset = (page - 1) * page_size
    filters = _PERSONAL_FAILURE_FILTERS
    params = (int(owner_id),)
    total = conn.execute(
        "SELECT COUNT(*) FROM analysis_queue aq "
        "JOIN interview i ON i.id = aq.interview_id "
        "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
        f"WHERE {filters}",
        params,
    ).fetchone()[0]
    query_page_size = max(0, min(int(page_size), int(total) - offset))
    rows = conn.execute(
        f"{_PERSONAL_FAILURE_SELECT} "
        f"WHERE {filters} "
        "ORDER BY aq.created_at DESC, aq.id DESC LIMIT ? OFFSET ?",
        (*params, query_page_size, offset),
    ).fetchall()
    return {
        "items": _personal_failure_items(rows),
        "total": int(total),
        "page": page,
        "page_size": page_size,
    }


def refresh_personal_analysis_failures(
    conn, *, owner_id: int, loaded_count: int, cursor: dict | None = None
):
    """Return one bounded keyset page of the owner's current failures."""

    loaded_count = max(1, min(MAX_PERSONAL_FAILURE_REFRESH_ITEMS, int(loaded_count)))
    cursor_filter = ""
    params = (int(owner_id),)
    if cursor is not None:
        cursor_created_at = str(cursor["created_at"])
        cursor_queue_id = int(cursor["queue_id"])
        if not 1 <= cursor_queue_id <= MAX_SQLITE_INTEGER:
            raise ValueError("cursor queue_id must fit SQLite signed integer range")
        cursor_filter = (
            " AND (aq.created_at < ? OR (aq.created_at = ? AND aq.id < ?))"
        )
        params = (*params, cursor_created_at, cursor_created_at, cursor_queue_id)

    total = conn.execute(
        "SELECT COUNT(*) FROM analysis_queue aq "
        "JOIN interview i ON i.id = aq.interview_id "
        "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
        f"WHERE {_PERSONAL_FAILURE_FILTERS}",
        (int(owner_id),),
    ).fetchone()[0]
    rows = conn.execute(
        f"{_PERSONAL_FAILURE_SELECT} WHERE {_PERSONAL_FAILURE_FILTERS}"
        f"{cursor_filter} ORDER BY aq.created_at DESC, aq.id DESC LIMIT ?",
        (*params, loaded_count + 1),
    ).fetchall()
    has_more = len(rows) > loaded_count
    page_rows = rows[:loaded_count]
    next_cursor = None
    if has_more and page_rows:
        last_row = page_rows[-1]
        next_cursor = {
            "created_at": str(last_row["created_at"]),
            "queue_id": int(last_row["queue_id"]),
        }

    return {
        "items": _personal_failure_items(page_rows),
        "total": int(total),
        "page": 1,
        "page_size": loaded_count,
        "next_cursor": next_cursor,
    }


def retry_personal_analysis_failure(conn, *, queue_id: int, owner_id: int):
    """Requeue one authorized private row, preserving its rootless identity."""

    queue_id = int(queue_id)
    if not 1 <= queue_id <= MAX_SQLITE_INTEGER:
        raise ValueError("queue_id must fit SQLite signed integer range")

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT aq.id, aq.status FROM analysis_queue aq "
            "JOIN interview i ON i.id = aq.interview_id "
            "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
            "WHERE aq.id = ? AND aq.owner_id = ? "
            "AND aq.root_import_id IS NULL "
            "AND aq.contribution_request_id IS NULL "
            "AND i.owner_id = aq.owner_id AND i.status = 'approved' "
            "AND i.deleted_at IS NULL AND qd.deleted_at IS NULL "
            "AND qd.interview_id = aq.interview_id AND qd.import_id IS NULL",
            (int(queue_id), int(owner_id)),
        ).fetchone()
        if row is None:
            raise PersonalAnalysisRetryError(404, "任务不存在")

        status = str(row["status"] or "")
        created = False
        if status == "failed":
            changed = conn.execute(
                "UPDATE analysis_queue SET status = 'pending', "
                "processed_at = NULL, locked_until = NULL, claimed_at = NULL "
                "WHERE id = ? AND owner_id = ? AND root_import_id IS NULL "
                "AND contribution_request_id IS NULL AND status = 'failed' "
                "AND EXISTS (SELECT 1 FROM questions_detail qd "
                "WHERE qd.id = analysis_queue.question_detail_id "
                "AND qd.interview_id = analysis_queue.interview_id "
                "AND qd.import_id IS NULL)",
                (int(queue_id), int(owner_id)),
            ).rowcount
            if changed != 1:
                raise PersonalAnalysisRetryError(409, "RETRY_STATE_CHANGED: 任务状态已变化，请刷新")
            created = True
            status = "pending"
        elif status not in ("pending", "processing"):
            raise PersonalAnalysisRetryError(409, "RETRY_NOT_ALLOWED: 该任务当前状态不支持重试")

        conn.commit()
        return {"queue_id": int(queue_id), "status": status, "created": created}
    except Exception:
        conn.rollback()
        raise

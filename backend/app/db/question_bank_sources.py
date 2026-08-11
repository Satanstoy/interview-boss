"""Normalized helpers for question_bank source tracking.

Replaces JSON TEXT column manipulation (sources, original_questions,
original_question_sources) with proper relational table operations.

All write helpers accept a cursor (transactional context).
All read helpers accept a cursor for consistency.
"""

import logging
import sqlite3

logger = logging.getLogger("interview-boss")


# ``None`` is a valid scope: it means public rows.  The sentinel keeps the
# legacy callers that intentionally operate on every owner distinguishable.
_OWNER_SCOPE_UNSET = object()


def _table_exists(cursor, table_name: str) -> bool:
    return bool(
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    )


def _has_column(cursor, table_name: str, column_name: str) -> bool:
    return any(
        row[1] == column_name
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    )


def _owner_scope_clause(owner_scope):
    if owner_scope is _OWNER_SCOPE_UNSET:
        return "", ()
    return " AND qb.owner_id IS ?", (owner_scope,)


def _upsert_source(cursor, qb_id: int, source: dict, *, restore: bool = True):
    if not _table_exists(cursor, "question_sources"):
        return
    url = source.get("url", "")
    if not url:
        return
    row = cursor.execute(
        "SELECT id FROM question_sources WHERE question_bank_id = ? AND url = ?",
        (qb_id, url),
    ).fetchone()
    if row:
        if _has_column(cursor, "question_sources", "deleted_at") and restore:
            cursor.execute(
                "UPDATE question_sources SET company = ?, round = ?, deleted_at = NULL "
                "WHERE question_bank_id = ? AND url = ?",
                (source.get("company", ""), source.get("round", ""), qb_id, url),
            )
        else:
            cursor.execute(
                "UPDATE question_sources SET company = ?, round = ? "
                "WHERE question_bank_id = ? AND url = ?",
                (source.get("company", ""), source.get("round", ""), qb_id, url),
            )
        return
    cursor.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, ?, ?)",
        (qb_id, url, source.get("company", ""), source.get("round", "")),
    )


def _upsert_original_item_source(
    cursor, item_id: int, source: dict, *, restore: bool = True
):
    if not _table_exists(cursor, "question_original_item_sources"):
        return
    url = source.get("url", "")
    if not url:
        return
    row = cursor.execute(
        "SELECT id FROM question_original_item_sources "
        "WHERE original_item_id = ? AND url = ?",
        (item_id, url),
    ).fetchone()
    if row:
        if _has_column(cursor, "question_original_item_sources", "deleted_at") and restore:
            cursor.execute(
                "UPDATE question_original_item_sources SET company = ?, round = ?, deleted_at = NULL "
                "WHERE original_item_id = ? AND url = ?",
                (source.get("company", ""), source.get("round", ""), item_id, url),
            )
        else:
            cursor.execute(
                "UPDATE question_original_item_sources SET company = ?, round = ? "
                "WHERE original_item_id = ? AND url = ?",
                (source.get("company", ""), source.get("round", ""), item_id, url),
            )
        return
    cursor.execute(
        "INSERT INTO question_original_item_sources "
        "(original_item_id, url, company, round) VALUES (?, ?, ?, ?)",
        (item_id, url, source.get("company", ""), source.get("round", "")),
    )


# ═══════════════════════════════════════════════════
#  Write helpers (transactional — accept cursor)
# ═══════════════════════════════════════════════════


def insert_source(cursor, qb_id: int, url: str, company: str = "", round_: str = ""):
    """Insert a source entry. ON CONFLICT IGNORE (dedup by qb_id + url)."""
    cursor.execute(
        "INSERT OR IGNORE INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, ?, ?)",
        (qb_id, url, company, round_),
    )


def delete_source(cursor, qb_id: int, url: str):
    """Soft delete a specific source by qb_id + url."""
    cursor.execute(
        "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP WHERE question_bank_id = ? AND url = ? AND deleted_at IS NULL",
        (qb_id, url),
    )


def delete_sources_by_url(cursor, url: str):
    """Soft delete source entries from every owner (legacy helper)."""
    if not _table_exists(cursor, "question_sources"):
        return
    if _has_column(cursor, "question_sources", "deleted_at"):
        cursor.execute(
            "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE url = ? AND deleted_at IS NULL",
            (url,),
        )
    else:
        cursor.execute("DELETE FROM question_sources WHERE url = ?", (url,))


def delete_sources_by_url_scoped(cursor, url: str, owner_scope):
    """Soft delete sources for one owner scope, including public ``None``."""
    if not _table_exists(cursor, "question_sources"):
        return
    clause, params = _owner_scope_clause(owner_scope)
    if _has_column(cursor, "question_sources", "deleted_at"):
        cursor.execute(
            "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE url = ? AND deleted_at IS NULL AND question_bank_id IN "
            "(SELECT id FROM question_bank qb WHERE 1 = 1" + clause + ")",
            (url, *params),
        )
    else:
        cursor.execute(
            "DELETE FROM question_sources WHERE url = ? AND question_bank_id IN "
            "(SELECT id FROM question_bank qb WHERE 1 = 1" + clause + ")",
            (url, *params),
        )


def delete_all_sources(cursor, qb_id: int):
    """Soft delete all sources for a question_bank row."""
    cursor.execute(
        "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP WHERE question_bank_id = ? AND deleted_at IS NULL",
        (qb_id,),
    )


def insert_original_item(
    cursor, qb_id: int, question_text: str, sources_list: list = None
):
    """Insert an original question item and its sources.

    Args:
        qb_id: question_bank.id
        question_text: the original question text
        sources_list: list of {url, company, round} dicts
    """
    cursor.execute(
        "INSERT OR IGNORE INTO question_original_items (question_bank_id, question_text) VALUES (?, ?)",
        (qb_id, question_text),
    )
    item_id = cursor.execute(
        "SELECT id FROM question_original_items WHERE question_bank_id = ? AND question_text = ?",
        (qb_id, question_text),
    ).fetchone()
    if item_id is None:
        return
    item_id = item_id[0]

    if sources_list:
        for s in sources_list:
            if isinstance(s, dict):
                cursor.execute(
                    "INSERT OR IGNORE INTO question_original_item_sources (original_item_id, url, company, round) VALUES (?, ?, ?, ?)",
                    (
                        item_id,
                        s.get("url", ""),
                        s.get("company", ""),
                        s.get("round", ""),
                    ),
                )


def delete_original_item(cursor, qb_id: int, question_text: str):
    """Soft delete an original item and its sources by qb_id + question_text."""
    cursor.execute(
        "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
        "WHERE original_item_id IN "
        "(SELECT id FROM question_original_items WHERE question_bank_id = ? AND question_text = ?) "
        "AND deleted_at IS NULL",
        (qb_id, question_text),
    )
    cursor.execute(
        "UPDATE question_original_items SET deleted_at = CURRENT_TIMESTAMP "
        "WHERE question_bank_id = ? AND question_text = ? AND deleted_at IS NULL",
        (qb_id, question_text),
    )


def delete_all_original_items(cursor, qb_id: int):
    """Soft delete all original items + their sources for a qb_id."""
    cursor.execute(
        "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
        "WHERE original_item_id IN "
        "(SELECT id FROM question_original_items WHERE question_bank_id = ? AND deleted_at IS NULL) "
        "AND deleted_at IS NULL",
        (qb_id,),
    )
    cursor.execute(
        "UPDATE question_original_items SET deleted_at = CURRENT_TIMESTAMP "
        "WHERE question_bank_id = ? AND deleted_at IS NULL",
        (qb_id,),
    )


def delete_all_for_qb(cursor, qb_id: int):
    """Soft delete all normalized data for a question_bank row."""
    delete_all_sources(cursor, qb_id)
    delete_all_original_items(cursor, qb_id)


def sync_question_bank_sources(
    cursor,
    qb_id: int,
    sources: list,
    original_questions: list,
    original_question_sources: list,
):
    """Make normalized source tables match the JSON compatibility columns.

    This function is deliberately transactional: callers must invoke it with
    the same cursor that updates ``question_bank``.  It repairs legacy
    half-dual-writes while deleting/restoring a source, instead of silently
    leaving one representation stale.
    """
    if not isinstance(getattr(cursor, "connection", None), sqlite3.Connection):
        # Keep lightweight unit-test cursors on the legacy JSON path.
        return
    desired_sources = {
        item.get("url"): item
        for item in (sources or [])
        if isinstance(item, dict) and item.get("url")
    }
    if _table_exists(cursor, "question_sources"):
        has_deleted = _has_column(cursor, "question_sources", "deleted_at")
        if desired_sources:
            placeholders = ",".join("?" * len(desired_sources))
            params = [qb_id, *desired_sources]
            if has_deleted:
                cursor.execute(
                    "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP "
                    f"WHERE question_bank_id = ? AND url NOT IN ({placeholders}) AND deleted_at IS NULL",
                    params,
                )
            else:
                cursor.execute(
                    "DELETE FROM question_sources "
                    f"WHERE question_bank_id = ? AND url NOT IN ({placeholders})",
                    params,
                )
        elif has_deleted:
            cursor.execute(
                "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE question_bank_id = ? AND deleted_at IS NULL",
                (qb_id,),
            )
        else:
            cursor.execute(
                "DELETE FROM question_sources WHERE question_bank_id = ?", (qb_id,)
            )
        for source in desired_sources.values():
            _upsert_source(cursor, qb_id, source)

    if not (
        _table_exists(cursor, "question_original_items")
        and _table_exists(cursor, "question_original_item_sources")
    ):
        return

    desired_by_question = {}
    for item in original_question_sources or []:
        if not isinstance(item, dict):
            continue
        question = str(item.get("question", ""))
        desired_by_question[question] = [
            source
            for source in item.get("sources", [])
            if isinstance(source, dict) and source.get("url")
        ]
    for question in original_questions or []:
        desired_by_question.setdefault(str(question), [])

    item_deleted = _has_column(cursor, "question_original_items", "deleted_at")
    item_source_deleted = _has_column(
        cursor, "question_original_item_sources", "deleted_at"
    )
    existing_items = cursor.execute(
        "SELECT id, question_text FROM question_original_items WHERE question_bank_id = ?",
        (qb_id,),
    ).fetchall()
    existing_by_question = {row[1]: row[0] for row in existing_items}

    for question, item_sources in desired_by_question.items():
        item_id = existing_by_question.get(question)
        if item_id is None:
            cursor.execute(
                "INSERT INTO question_original_items (question_bank_id, question_text) VALUES (?, ?)",
                (qb_id, question),
            )
            item_id = cursor.lastrowid
        elif item_deleted:
            cursor.execute(
                "UPDATE question_original_items SET deleted_at = NULL WHERE id = ?",
                (item_id,),
            )

        desired_urls = {
            source.get("url") for source in item_sources if source.get("url")
        }
        if desired_urls:
            placeholders = ",".join("?" * len(desired_urls))
            params = [item_id, *desired_urls]
            if item_source_deleted:
                cursor.execute(
                    "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
                    f"WHERE original_item_id = ? AND url NOT IN ({placeholders}) AND deleted_at IS NULL",
                    params,
                )
            else:
                cursor.execute(
                    "DELETE FROM question_original_item_sources "
                    f"WHERE original_item_id = ? AND url NOT IN ({placeholders})",
                    params,
                )
        elif item_source_deleted:
            cursor.execute(
                "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE original_item_id = ? AND deleted_at IS NULL",
                (item_id,),
            )
        else:
            cursor.execute(
                "DELETE FROM question_original_item_sources WHERE original_item_id = ?",
                (item_id,),
            )
        for source in item_sources:
            _upsert_original_item_source(cursor, item_id, source)

    stale_items = [
        item_id
        for question, item_id in existing_by_question.items()
        if question not in desired_by_question
    ]
    for item_id in stale_items:
        if item_source_deleted:
            cursor.execute(
                "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE original_item_id = ? AND deleted_at IS NULL",
                (item_id,),
            )
        else:
            cursor.execute(
                "DELETE FROM question_original_item_sources WHERE original_item_id = ?",
                (item_id,),
            )
        if item_deleted:
            cursor.execute(
                "UPDATE question_original_items SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND deleted_at IS NULL",
                (item_id,),
            )
        else:
            cursor.execute("DELETE FROM question_original_items WHERE id = ?", (item_id,))


def merge_source_into_original_item(
    cursor,
    qb_id: int,
    question_text: str,
    url: str,
    company: str = "",
    round_: str = "",
):
    """Add a source to an existing original item (ON CONFLICT IGNORE)."""
    item_id = cursor.execute(
        "SELECT id FROM question_original_items WHERE question_bank_id = ? AND question_text = ?",
        (qb_id, question_text),
    ).fetchone()
    if item_id is None:
        return
    cursor.execute(
        "INSERT OR IGNORE INTO question_original_item_sources (original_item_id, url, company, round) VALUES (?, ?, ?, ?)",
        (item_id[0], url, company, round_),
    )


def remove_original_items_by_url(
    cursor, url: str, owner_scope=_OWNER_SCOPE_UNSET
):
    """Soft delete original-item source links for a URL and owner scope.

    The rows are retained for restoration, but hidden from active source
    queries.  An original item is also soft-deleted when its last source is
    gone, which keeps ``original_questions`` and normalized rows aligned.
    """
    if not (
        _table_exists(cursor, "question_original_items")
        and _table_exists(cursor, "question_original_item_sources")
    ):
        return
    clause, params = _owner_scope_clause(owner_scope)
    has_source_deleted = _has_column(
        cursor, "question_original_item_sources", "deleted_at"
    )
    has_item_deleted = _has_column(cursor, "question_original_items", "deleted_at")
    if has_source_deleted:
        cursor.execute(
            "UPDATE question_original_item_sources SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE url = ? AND original_item_id IN ("
            "SELECT qoi.id FROM question_original_items qoi "
            "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
            "WHERE 1 = 1" + clause + ") AND deleted_at IS NULL",
            (url, *params),
        )
    else:
        cursor.execute(
            "DELETE FROM question_original_item_sources "
            "WHERE url = ? AND original_item_id IN ("
            "SELECT qoi.id FROM question_original_items qoi "
            "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
            "WHERE 1 = 1" + clause + ")",
            (url, *params),
        )

    if has_item_deleted and has_source_deleted:
        cursor.execute(
            "UPDATE question_original_items SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE deleted_at IS NULL AND id IN ("
            "SELECT qoi.id FROM question_original_items qoi "
            "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
            "WHERE 1 = 1" + clause + ") AND NOT EXISTS ("
            "SELECT 1 FROM question_original_item_sources qois "
            "WHERE qois.original_item_id = question_original_items.id "
            "AND qois.deleted_at IS NULL)",
            params,
        )


def restore_source_for_url(cursor, url: str, owner_scope=_OWNER_SCOPE_UNSET) -> list[int]:
    """Restore sources for a URL by restoring soft-deleted records.

    Called when an interview is restored from soft-delete.
    """
    if not isinstance(getattr(cursor, "connection", None), sqlite3.Connection):
        return []
    affected_ids = set()
    clause, params = _owner_scope_clause(owner_scope)
    if _table_exists(cursor, "question_sources"):
        rows = cursor.execute(
            "SELECT DISTINCT qb.id FROM question_sources qs "
            "JOIN question_bank qb ON qb.id = qs.question_bank_id "
            "WHERE qs.url = ?" + clause,
            (url, *params),
        ).fetchall()
        affected_ids.update(row[0] for row in rows)
        if _has_column(cursor, "question_sources", "deleted_at"):
            cursor.execute(
                "UPDATE question_sources SET deleted_at = NULL WHERE url = ? "
                "AND deleted_at IS NOT NULL AND question_bank_id IN ("
                "SELECT id FROM question_bank qb WHERE 1 = 1" + clause + ")",
                (url, *params),
            )

    if _table_exists(cursor, "question_original_item_sources"):
        rows = cursor.execute(
            "SELECT DISTINCT qoi.question_bank_id "
            "FROM question_original_item_sources qois "
            "JOIN question_original_items qoi ON qois.original_item_id = qoi.id "
            "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
            "WHERE qois.url = ?" + clause,
            (url, *params),
        ).fetchall()
        affected_ids.update(row[0] for row in rows)
        if _has_column(cursor, "question_original_item_sources", "deleted_at"):
            cursor.execute(
                "UPDATE question_original_item_sources SET deleted_at = NULL "
                "WHERE url = ? AND deleted_at IS NOT NULL AND original_item_id IN ("
                "SELECT qoi.id FROM question_original_items qoi "
                "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
                "WHERE 1 = 1" + clause + ")",
                (url, *params),
            )
        if _has_column(cursor, "question_original_items", "deleted_at"):
            cursor.execute(
                "UPDATE question_original_items SET deleted_at = NULL "
                "WHERE deleted_at IS NOT NULL AND id IN ("
                "SELECT DISTINCT qois.original_item_id "
                "FROM question_original_item_sources qois "
                "JOIN question_original_items qoi ON qoi.id = qois.original_item_id "
                "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
                "WHERE qois.url = ?" + clause + ")",
                (url, *params),
            )

    for qb_id in affected_ids:
        row = cursor.execute(
            "SELECT sources, original_questions, original_question_sources "
            "FROM question_bank WHERE id = ?",
            (qb_id,),
        ).fetchone()
        if row is None:
            continue
        # The caller rebuilds JSON from these normalized rows.  Returning IDs
        # keeps this helper independent of the router layer.
    return sorted(affected_ids)


# ═══════════════════════════════════════════════════
#  Read helpers
# ═══════════════════════════════════════════════════


def get_sources(cursor, qb_id: int) -> list:
    """Return [{url, company, round}, ...] from question_sources."""
    rows = cursor.execute(
        "SELECT url, company, round FROM question_sources WHERE question_bank_id = ? AND deleted_at IS NULL ORDER BY id",
        (qb_id,),
    ).fetchall()
    return [{"url": r[0], "company": r[1], "round": r[2]} for r in rows]


def get_original_questions(cursor, qb_id: int) -> list:
    """Return ['text1', 'text2', ...] from question_original_items."""
    rows = cursor.execute(
        "SELECT question_text FROM question_original_items WHERE question_bank_id = ? AND deleted_at IS NULL ORDER BY id",
        (qb_id,),
    ).fetchall()
    return [r[0] for r in rows]


def get_original_question_sources(cursor, qb_id: int) -> list:
    """Return [{question, sources: [{url, company, round}]}, ...]"""
    items = cursor.execute(
        "SELECT id, question_text FROM question_original_items WHERE question_bank_id = ? AND deleted_at IS NULL ORDER BY id",
        (qb_id,),
    ).fetchall()

    result = []
    for item in items:
        sources = cursor.execute(
            "SELECT url, company, round FROM question_original_item_sources WHERE original_item_id = ? AND deleted_at IS NULL ORDER BY id",
            (item[0],),
        ).fetchall()
        result.append(
            {
                "question": item[1],
                "sources": [
                    {"url": s[0], "company": s[1], "round": s[2]} for s in sources
                ],
            }
        )
    return result



def _normalize_bank_mode(bank_mode: str) -> str:
    """Normalize old bank_mode / new filter values to 'public' | 'mixed'.

    public → 只公共来源；all/mine/personal/mixed → 公共 + 自己的来源。
    """
    return "public" if bank_mode == "public" else "mixed"


def get_sources_filtered(cursor, qb_id: int, bank_mode: str, user_id: int) -> list:
    """Get sources filtered by bank_mode using SQL JOIN (replaces filter_sources_by_mode).

    接受新 filter 口径（all/public/mine）或旧值（personal/mixed）。
    """
    mode = _normalize_bank_mode(bank_mode)
    owner_filter = {
        "mixed": "(i.owner_id IS NULL OR i.owner_id = ?)",
        "public": "i.owner_id IS NULL",
    }[mode]
    user_param = () if mode == "public" else (user_id,)
    owner_clause = f" AND {owner_filter}" if owner_filter else ""

    if mode == "public":
        rows = cursor.execute(
            f"SELECT DISTINCT qs.url, qs.company, qs.round "
            f"FROM question_sources qs "
            f"JOIN interview i ON qs.url = i.url "
            f"WHERE qs.question_bank_id = ? AND qs.deleted_at IS NULL AND i.deleted_at IS NULL{owner_clause}",
            (qb_id,),
        ).fetchall()
    else:
        rows = cursor.execute(
            f"SELECT DISTINCT qs.url, qs.company, qs.round "
            f"FROM question_sources qs "
            f"JOIN interview i ON qs.url = i.url "
            f"WHERE qs.question_bank_id = ? AND qs.deleted_at IS NULL AND i.deleted_at IS NULL{owner_clause}",
            (qb_id, *user_param),
        ).fetchall()
    return [{"url": r[0], "company": r[1], "round": r[2]} for r in rows]


def get_original_question_sources_filtered(
    cursor, qb_id: int, bank_mode: str, user_id: int
) -> list:
    """Get original question sources filtered by bank_mode using SQL JOIN.

    接受新 filter 口径（all/public/mine）或旧值（personal/mixed）。
    """
    mode = _normalize_bank_mode(bank_mode)
    owner_filter = {
        "mixed": "(i.owner_id IS NULL OR i.owner_id = ?)",
        "public": "i.owner_id IS NULL",
    }[mode]
    user_param = () if mode == "public" else (user_id,)
    owner_clause = f" AND {owner_filter}" if owner_filter else ""

    items = cursor.execute(
        "SELECT id, question_text FROM question_original_items WHERE question_bank_id = ? AND deleted_at IS NULL ORDER BY id",
        (qb_id,),
    ).fetchall()

    result = []
    for item in items:
        if mode == "public":
            sources = cursor.execute(
                f"SELECT DISTINCT qois.url, qois.company, qois.round "
                f"FROM question_original_item_sources qois "
                f"JOIN interview i ON qois.url = i.url "
                f"WHERE qois.original_item_id = ? AND qois.deleted_at IS NULL AND i.deleted_at IS NULL{owner_clause}",
                (item[0],),
            ).fetchall()
        else:
            sources = cursor.execute(
                f"SELECT DISTINCT qois.url, qois.company, qois.round "
                f"FROM question_original_item_sources qois "
                f"JOIN interview i ON qois.url = i.url "
                f"WHERE qois.original_item_id = ? AND qois.deleted_at IS NULL AND i.deleted_at IS NULL{owner_clause}",
                (item[0], *user_param),
            ).fetchall()
        if sources:
            result.append(
                {
                    "question": item[1],
                    "sources": [
                        {"url": s[0], "company": s[1], "round": s[2]} for s in sources
                    ],
                }
            )
    return result


# ═══════════════════════════════════════════════════
#  Batch helpers (avoid N+1 queries)
# ═══════════════════════════════════════════════════


def build_api_shapes_batch(cursor, qb_ids: list) -> dict:
    """Batch-fetch all source data for a list of qb_ids.

    Returns {qb_id: {sources, original_questions, original_question_sources, frequency}}.
    Uses 3 queries instead of N+1.
    """
    if not qb_ids:
        return {}

    placeholders = ",".join(["?"] * len(qb_ids))

    # Query 1: all sources
    src_rows = cursor.execute(
        f"SELECT question_bank_id, url, company, round FROM question_sources "
        f"WHERE question_bank_id IN ({placeholders}) ORDER BY id",
        qb_ids,
    ).fetchall()
    sources_by_qb = {}
    for r in src_rows:
        sources_by_qb.setdefault(r[0], []).append(
            {"url": r[1], "company": r[2], "round": r[3]}
        )

    # Query 2: all original items
    oi_rows = cursor.execute(
        f"SELECT id, question_bank_id, question_text FROM question_original_items "
        f"WHERE question_bank_id IN ({placeholders}) ORDER BY id",
        qb_ids,
    ).fetchall()
    oi_by_qb = {}
    oi_ids = []
    oi_id_to_qb = {}
    oi_id_to_text = {}
    for r in oi_rows:
        oi_by_qb.setdefault(r[1], []).append(r[2])
        oi_ids.append(r[0])
        oi_id_to_qb[r[0]] = r[1]
        oi_id_to_text[r[0]] = r[2]

    # Query 3: all original item sources
    ois_by_oi = {}
    if oi_ids:
        oi_placeholders = ",".join(["?"] * len(oi_ids))
        ois_rows = cursor.execute(
            f"SELECT original_item_id, url, company, round FROM question_original_item_sources "
            f"WHERE original_item_id IN ({oi_placeholders}) ORDER BY id",
            oi_ids,
        ).fetchall()
        for r in ois_rows:
            ois_by_oi.setdefault(r[0], []).append(
                {"url": r[1], "company": r[2], "round": r[3]}
            )

    # Assemble results
    result = {}
    for qb_id in qb_ids:
        sources = sources_by_qb.get(qb_id, [])
        oq_texts = oi_by_qb.get(qb_id, [])

        # Build original_question_sources
        oqs = []
        for oi in oi_rows:
            if oi[1] != qb_id:
                continue
            oi_sources = ois_by_oi.get(oi[0], [])
            oqs.append({"question": oi[2], "sources": oi_sources})

        result[qb_id] = {
            "sources": sources,
            "original_questions": oq_texts,
            "original_question_sources": oqs,
            "frequency": len(sources),
        }

    return result


def build_api_shapes_batch_filtered(
    cursor, qb_ids: list, bank_mode: str, user_id: int
) -> dict:
    """Batch-fetch with bank_mode filtering. 3 queries total (no redundant unfiltered fetch).

    bank_mode 接受新 filter 口径（all/public/mine）或旧值（personal/mixed）：
    public → 只显示公共来源；all/mine/personal/mixed → 公共 + 自己的来源。
    """
    if not qb_ids:
        return {}

    placeholders = ",".join(["?"] * len(qb_ids))

    if bank_mode in ("public",):
        normalized = "public"
    else:
        normalized = "mixed"

    owner_filter = {
        "mixed": "(i.owner_id IS NULL OR i.owner_id = ?)",
        "public": "i.owner_id IS NULL",
    }[normalized]
    user_param = () if normalized == "public" else (user_id,)
    owner_clause = f" AND {owner_filter}" if owner_filter else ""

    # Query 1: filtered sources via JOIN
    if normalized == "public":
        src_rows = cursor.execute(
            f"SELECT DISTINCT qs.question_bank_id, qs.url, qs.company, qs.round "
            f"FROM question_sources qs JOIN interview i ON qs.url = i.url "
            f"WHERE qs.question_bank_id IN ({placeholders}) AND i.deleted_at IS NULL{owner_clause}",
            (*qb_ids,),
        ).fetchall()
    else:
        src_rows = cursor.execute(
            f"SELECT DISTINCT qs.question_bank_id, qs.url, qs.company, qs.round "
            f"FROM question_sources qs JOIN interview i ON qs.url = i.url "
            f"WHERE qs.question_bank_id IN ({placeholders}) AND i.deleted_at IS NULL{owner_clause}",
            (*qb_ids, *user_param),
        ).fetchall()
    sources_by_qb = {}
    for r in src_rows:
        sources_by_qb.setdefault(r[0], []).append(
            {"url": r[1], "company": r[2], "round": r[3]}
        )

    # Query 2: all original items (no filtering needed - items are owned by QB)
    oi_rows = cursor.execute(
        f"SELECT id, question_bank_id, question_text FROM question_original_items "
        f"WHERE question_bank_id IN ({placeholders}) ORDER BY id",
        qb_ids,
    ).fetchall()
    oi_by_qb = {}
    oi_ids = []
    for r in oi_rows:
        oi_by_qb.setdefault(r[1], []).append(r[2])
        oi_ids.append(r[0])

    # Query 3: filtered original item sources via JOIN
    ois_by_oi = {}
    if oi_ids:
        oi_ph = ",".join(["?"] * len(oi_ids))
        if normalized == "public":
            ois_rows = cursor.execute(
                f"SELECT DISTINCT qois.original_item_id, qoi.question_bank_id, qois.url, qois.company, qois.round "
                f"FROM question_original_item_sources qois "
                f"JOIN question_original_items qoi ON qois.original_item_id = qoi.id "
                f"JOIN interview i ON qois.url = i.url "
                f"WHERE qois.original_item_id IN ({oi_ph}) AND i.deleted_at IS NULL{owner_clause}",
                (*oi_ids,),
            ).fetchall()
        else:
            ois_rows = cursor.execute(
                f"SELECT DISTINCT qois.original_item_id, qoi.question_bank_id, qois.url, qois.company, qois.round "
                f"FROM question_original_item_sources qois "
                f"JOIN question_original_items qoi ON qois.original_item_id = qoi.id "
                f"JOIN interview i ON qois.url = i.url "
                f"WHERE qois.original_item_id IN ({oi_ph}) AND i.deleted_at IS NULL{owner_clause}",
                (*oi_ids, *user_param),
            ).fetchall()
        for r in ois_rows:
            ois_by_oi.setdefault(r[0], []).append(
                {"url": r[2], "company": r[3], "round": r[4]}
            )

    # Assemble
    result = {}
    for qb_id in qb_ids:
        sources = sources_by_qb.get(qb_id, [])
        oq_texts = oi_by_qb.get(qb_id, [])
        oqs = []
        for r in oi_rows:
            if r[1] != qb_id:
                continue
            oi_sources = ois_by_oi.get(r[0], [])
            if oi_sources:
                oqs.append({"question": r[2], "sources": oi_sources})
        result[qb_id] = {
            "sources": sources,
            "original_questions": [item["question"] for item in oqs]
            if oqs
            else oq_texts,
            "original_question_sources": oqs,
            "frequency": len(sources),
        }
    return result

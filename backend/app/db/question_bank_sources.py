"""Normalized helpers for question_bank source tracking.

Replaces JSON TEXT column manipulation (sources, original_questions,
original_question_sources) with proper relational table operations.

All write helpers accept a cursor (transactional context).
All read helpers accept a cursor for consistency.
"""

import logging

logger = logging.getLogger("interview-boss")


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
    """Soft delete source entries from question_sources table only.

    Note: We preserve question_original_item_sources for restoration.
    """
    cursor.execute(
        "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP WHERE url = ? AND deleted_at IS NULL",
        (url,),
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


def remove_original_items_by_url(cursor, url: str):
    """保留 original_item_sources 记录以支持恢复。

    删除面经时，只从 question_sources 表删除记录，
    保留 question_original_item_sources 表的记录，
    这样恢复面经时可以重新插入到 question_sources 表。
    """
    pass


def restore_source_for_url(cursor, url: str):
    """Restore sources for a URL by restoring soft-deleted records.

    Called when an interview is restored from soft-delete.
    """
    cursor.execute(
        "UPDATE question_sources SET deleted_at = NULL WHERE url = ? AND deleted_at IS NOT NULL",
        (url,),
    )

    cursor.execute(
        "UPDATE question_original_item_sources SET deleted_at = NULL WHERE url = ? AND deleted_at IS NOT NULL",
        (url,),
    )

    cursor.execute(
        "UPDATE question_original_items SET deleted_at = NULL "
        "WHERE id IN (SELECT DISTINCT original_item_id FROM question_original_item_sources WHERE url = ?) "
        "AND deleted_at IS NOT NULL",
        (url,),
    )

    affected_qb = cursor.execute(
        "SELECT DISTINCT qoi.question_bank_id "
        "FROM question_original_items qoi "
        "JOIN question_original_item_sources qois ON qois.original_item_id = qoi.id "
        "WHERE qois.url = ? AND qois.deleted_at IS NULL",
        (url,),
    ).fetchall()

    for row in affected_qb:
        qb_id = row[0]
        src = cursor.execute(
            "SELECT DISTINCT qois.company, qois.round "
            "FROM question_original_item_sources qois "
            "JOIN question_original_items qoi ON qois.original_item_id = qoi.id "
            "WHERE qoi.question_bank_id = ? AND qois.url = ? AND qois.deleted_at IS NULL LIMIT 1",
            (qb_id, url),
        ).fetchone()
        company = src[0] if src else ""
        round_ = src[1] if src else ""
        insert_source(cursor, qb_id, url, company, round_)


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

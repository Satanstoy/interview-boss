"""Question-bank backed study plans and per-user review state queries."""

from __future__ import annotations

import json
from datetime import datetime

from app.db.queries import build_bank_where_clause, get_dynamic_frequency_sql


DECKS = (
    {
        "key": "due",
        "name": "今日复习",
        "description": "到期复习优先，按重要度和遗忘风险安排",
        "kind": "due",
        "sort_order": 0,
    },
    {
        "key": "all",
        "name": "全部题",
        "description": "按复习状态和面试频率安排顺序",
        "kind": "all",
        "sort_order": 1,
    },
    {
        "key": "starred",
        "name": "我的收藏",
        "description": "把收藏题集中起来反复背",
        "kind": "starred",
        "sort_order": 2,
    },
)

DECK_BY_KEY = {deck["key"]: deck for deck in DECKS}
HIGH_FREQUENCY_THRESHOLD = 3


def _split_bank_params(from_clause: str, params: list) -> tuple[list, list]:
    """Separate position JOIN parameters from WHERE parameters."""

    if "qp.position_id = ?" not in from_clause:
        return [], list(params)
    return list(params[:1]), list(params[1:])


def _json_or_default(value, default):
    if not value:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _review_join(user_id: int) -> str:
    return (
        " LEFT JOIN user_question_view uqv ON uqv.question_bank_id = qb.id "
        "AND uqv.user_id = ? "
        " LEFT JOIN user_question_review uqr ON uqr.question_bank_id = qb.id "
        "AND uqr.user_id = ? "
    )


def _deck_condition(deck_key: str, frequency_sql: str) -> str:
    if deck_key == "due":
        return "(uqr.next_review_at IS NULL OR datetime(uqr.next_review_at) <= datetime('now'))"
    if deck_key == "high-frequency":
        return f"(COALESCE(qb.frequency, 0) >= {HIGH_FREQUENCY_THRESHOLD} OR ({frequency_sql}) >= {HIGH_FREQUENCY_THRESHOLD})"
    if deck_key == "starred":
        return "COALESCE(uqv.is_starred, 0) = 1"
    if deck_key == "unpracticed":
        return "COALESCE(uqr.review_count, 0) = 0"
    return "1 = 1"


def _difficulty_condition(deck_key: str) -> str:
    if deck_key in {"l1", "l2", "l3"}:
        return f"qb.difficulty LIKE '{deck_key.upper()}%'"
    return "1 = 1"


def get_deck_definition(conn, user_id: int, deck_key: str) -> dict | None:
    if deck_key in DECK_BY_KEY:
        return {**DECK_BY_KEY[deck_key], "kind": DECK_BY_KEY[deck_key]["kind"]}
    if deck_key in {"l1", "l2", "l3"}:
        labels = {"l1": "L1 基础", "l2": "L2 进阶", "l3": "L3 挑战"}
        return {
            "key": deck_key,
            "name": labels[deck_key],
            "description": "按难度复习",
            "kind": "difficulty",
        }
    row = conn.execute(
        "SELECT id, deck_key AS key, name, description, visibility, owner_id, "
        "sort_order, 'custom' AS kind FROM practice_decks "
        "WHERE deck_key = ? AND owner_id = ?",
        (deck_key, user_id),
    ).fetchone()
    return dict(row) if row else None


def _base_query_parts(conn, user_id: int, filter_mode: str, deck_key: str):
    deck = get_deck_definition(conn, user_id, deck_key)
    if not deck:
        raise KeyError(deck_key)
    from_clause, where_clause, params = build_bank_where_clause(
        user_id, filter_mode, "qb"
    )
    join_params, where_params = _split_bank_params(from_clause, params)
    frequency_sql = get_dynamic_frequency_sql(filter_mode, user_id, "qb")
    conditions = [
        _deck_condition(deck_key, frequency_sql)
        if deck["kind"] != "custom"
        else "1 = 1",
        _difficulty_condition(deck_key),
    ]
    source_params = join_params
    if deck["kind"] == "custom":
        from_clause += (
            " JOIN practice_deck_items pdi ON pdi.question_bank_id = qb.id "
            "AND pdi.deck_id = ?"
        )
        source_params = join_params + [deck["id"]]
    where_clause = f"{where_clause} AND {' AND '.join(conditions)}"
    return deck, from_clause, where_clause, source_params, where_params, frequency_sql


def _select_sql(from_clause: str, where_clause: str, frequency_sql: str) -> str:
    # question_bank.frequency is the high-frequency-bank signal.  The
    # dynamic frequency query captures the user's current bank scope; using
    # the larger of the two keeps high-frequency interview questions visible
    # near the front of every queue without turning them into a separate UI
    # category.
    frequency_score_sql = f"MAX(COALESCE(qb.frequency, 0), ({frequency_sql}))"
    return (
        "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, "
        f"{frequency_score_sql} AS frequency, qb.ai_answer, qb.sources, "
        "qb.original_questions, qb.original_question_sources, qb.owner_id, "
        "COALESCE(uqv.is_starred, 0) AS is_starred, "
        "COALESCE(uqv.user_answer, '') AS user_answer, "
        "COALESCE(uqr.state, 'new') AS review_state, "
        "COALESCE(uqr.proficiency, 0) AS proficiency, "
        "COALESCE(uqr.review_count, 0) AS review_count, "
        "COALESCE(uqr.lapse_count, 0) AS lapse_count, "
        "uqr.last_rating, uqr.last_reviewed_at, uqr.next_review_at, "
        "COALESCE(uqr.interval_days, 0) AS interval_days, "
        "COALESCE(uqr.ease_factor, 2.3) AS ease_factor "
        f"{from_clause}{_review_join('?')}{where_clause}"
    )


def _normalise_question(row) -> dict:
    item = dict(row)
    item["frequency"] = int(item.get("frequency") or 0)
    item["is_starred"] = bool(item.get("is_starred"))
    item["is_personal"] = item.get("owner_id") is not None
    item["has_been_practiced"] = int(item.get("review_count") or 0) > 0
    item["is_due"] = not item.get("next_review_at") or _is_due(item["next_review_at"])
    item["proficiency"] = int(item.get("proficiency") or 0)
    item["review_count"] = int(item.get("review_count") or 0)
    item["lapse_count"] = int(item.get("lapse_count") or 0)
    item["interval_days"] = float(item.get("interval_days") or 0)
    item["ease_factor"] = float(item.get("ease_factor") or 2.3)
    item["tags"] = _json_or_default(item.get("tags"), item.get("tags") or "")
    item["sources"] = _json_or_default(item.get("sources"), [])
    item["original_questions"] = _json_or_default(item.get("original_questions"), [])
    item["original_question_sources"] = _json_or_default(
        item.get("original_question_sources"), []
    )
    item["has_reference_answer"] = bool(
        item.get("ai_answer") and "生成失败" not in item["ai_answer"]
    )
    return item


def _is_due(value: str) -> bool:
    try:
        due = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if due.tzinfo:
            return due <= datetime.now(due.tzinfo)
        return due <= datetime.utcnow()
    except (TypeError, ValueError):
        return True


def list_decks(conn, user_id: int, filter_mode: str = "all") -> list[dict]:
    """Return named system study plans with live counts and progress."""

    result = []
    custom_where = "owner_id = ?"
    custom_params = [user_id]
    if filter_mode == "public":
        # 自定义题单纯私有：public 口径不返回任何自定义题单
        custom_where = "1 = 0"
        custom_params = []
    elif filter_mode == "mine":
        custom_where = "owner_id = ?"
    custom_decks = conn.execute(
        "SELECT id, deck_key AS key, name, description, visibility, owner_id, "
        "sort_order, 'custom' AS kind FROM practice_decks "
        f"WHERE {custom_where} ORDER BY sort_order, id",
        custom_params,
    ).fetchall()
    deck_definitions = [{**deck, "kind": deck["kind"]} for deck in DECKS]
    deck_definitions.extend(dict(row) for row in custom_decks)
    for deck in deck_definitions:
        _, from_clause, where_clause, source_params, where_params, _ = (
            _base_query_parts(conn, user_id, filter_mode, deck["key"])
        )
        query = (
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN COALESCE(uqr.review_count, 0) > 0 THEN 1 ELSE 0 END) AS reviewed, "
            "SUM(CASE WHEN uqr.next_review_at IS NULL OR datetime(uqr.next_review_at) <= datetime('now') THEN 1 ELSE 0 END) AS due "
            f"{from_clause}{_review_join('?')}{where_clause}"
        )
        # The two ? placeholders in _review_join are the user id values.
        params = source_params + [user_id, user_id] + where_params
        row = conn.execute(query, params).fetchone()
        total = int(row["total"] or 0)
        reviewed = int(row["reviewed"] or 0)
        due = int(row["due"] or 0)
        result.append(
            {
                **{
                    key: value
                    for key, value in deck.items()
                    if key not in {"owner_id", "sort_order"}
                },
                "total": total,
                "reviewed": reviewed,
                "due": due,
                "progress": round(reviewed / total * 100) if total else 0,
            }
        )
    return result


def list_deck_questions(
    conn,
    user_id: int,
    deck_key: str,
    *,
    filter_mode: str = "all",
    limit: int = 100,
    offset: int = 0,
    max_new: int | None = None,
) -> tuple[dict, list[dict], int]:
    """Load a deck ordered as a review queue, not as a random bank page."""

    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    deck, from_clause, where_clause, source_params, where_params, frequency_sql = (
        _base_query_parts(conn, user_id, filter_mode, deck_key)
    )
    join = _review_join("?")
    params = source_params + [user_id, user_id] + where_params
    total = conn.execute(
        f"SELECT COUNT(*) {from_clause}{join}{where_clause}", params
    ).fetchone()[0]
    custom_order = "pdi.sort_order ASC, " if deck["kind"] == "custom" else ""
    order = (
        " ORDER BY CASE WHEN datetime(uqr.next_review_at) <= datetime('now') THEN 0 "
        "WHEN uqr.next_review_at IS NULL THEN 1 ELSE 2 END, "
        "CASE WHEN uqr.next_review_at IS NULL THEN COALESCE(qb.frequency, 0) "
        "ELSE COALESCE(qb.frequency, 0) * (5 - COALESCE(uqr.proficiency, 0)) END DESC, "
        "COALESCE(uqr.next_review_at, '1970-01-01') ASC, "
        f"{custom_order}"
        # Reuse the SELECT alias instead of evaluating the correlated
        # dynamic-frequency subquery a second time for every row.
        "frequency DESC, qb.id ASC"
    )
    if deck_key == "due" and max_new is not None and offset == 0:
        max_new = max(0, int(max_new))
        due_cond = _deck_condition("due", "")
        due_where = where_clause.replace(
            due_cond,
            "(uqr.next_review_at IS NOT NULL AND datetime(uqr.next_review_at) <= datetime('now'))",
        )
        new_where = where_clause.replace(due_cond, "(uqr.next_review_at IS NULL)")
        due_rows = conn.execute(
            _select_sql(from_clause, due_where, frequency_sql) + order, params
        ).fetchall()
        new_rows = conn.execute(
            _select_sql(from_clause, new_where, frequency_sql)
            + " ORDER BY COALESCE(qb.frequency, 0) DESC, qb.id ASC LIMIT ?",
            params + [max_new],
        ).fetchall()
        rows = due_rows + new_rows
    else:
        rows = conn.execute(
            _select_sql(from_clause, where_clause, frequency_sql)
            + order
            + " LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return (
        {
            key: value
            for key, value in deck.items()
            if key not in {"owner_id", "sort_order"}
        },
        [_normalise_question(row) for row in rows],
        int(total),
    )


def create_custom_deck(
    conn, user_id: int, *, name: str, description: str = "", visibility: str = "private"
) -> dict:
    import secrets

    for _ in range(5):
        deck_key = f"custom-{user_id}-{secrets.token_urlsafe(8)}"
        try:
            cursor = conn.execute(
                "INSERT INTO practice_decks "
                "(deck_key, name, description, deck_type, criteria_json, sort_order, owner_id, visibility) "
                "VALUES (?, ?, ?, 'custom', '{\"kind\":\"custom\"}', 100, ?, ?)",
                (deck_key, name.strip(), description.strip(), user_id, visibility),
            )
            row = conn.execute(
                "SELECT id, deck_key AS key, name, description, visibility, owner_id, "
                "sort_order, 'custom' AS kind FROM practice_decks WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return dict(row)
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise
    raise RuntimeError("无法创建题单，请稍后重试")


def update_custom_deck(conn, user_id: int, deck_key: str, updates: dict) -> dict:
    row = conn.execute(
        "SELECT id FROM practice_decks WHERE deck_key = ? AND owner_id = ?",
        (deck_key, user_id),
    ).fetchone()
    if not row:
        raise KeyError(deck_key)
    fields = []
    params = []
    for field in ("name", "description", "visibility"):
        if updates.get(field) is not None:
            fields.append(f"{field} = ?")
            params.append(
                updates[field].strip()
                if isinstance(updates[field], str)
                else updates[field]
            )
    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        conn.execute(
            f"UPDATE practice_decks SET {', '.join(fields)} WHERE id = ?",
            params + [row["id"]],
        )
    updated = conn.execute(
        "SELECT id, deck_key AS key, name, description, visibility, owner_id, "
        "sort_order, 'custom' AS kind FROM practice_decks WHERE id = ?",
        (row["id"],),
    ).fetchone()
    return dict(updated)


def delete_custom_deck(conn, user_id: int, deck_key: str) -> None:
    cursor = conn.execute(
        "DELETE FROM practice_decks WHERE deck_key = ? AND owner_id = ?",
        (deck_key, user_id),
    )
    if cursor.rowcount == 0:
        raise KeyError(deck_key)


def add_deck_item(conn, user_id: int, deck_key: str, question_id: int) -> dict:
    deck = get_deck_definition(conn, user_id, deck_key)
    if not deck or deck["kind"] != "custom":
        raise KeyError(deck_key)
    existing = conn.execute(
        "SELECT id, sort_order FROM practice_deck_items WHERE deck_id = ? AND question_bank_id = ?",
        (deck["id"], question_id),
    ).fetchone()
    if existing:
        return {
            "id": existing["id"],
            "question_id": question_id,
            "sort_order": existing["sort_order"],
        }
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM practice_deck_items WHERE deck_id = ?",
        (deck["id"],),
    ).fetchone()[0]
    cursor = conn.execute(
        "INSERT INTO practice_deck_items (deck_id, question_bank_id, sort_order) VALUES (?, ?, ?)",
        (deck["id"], question_id, next_order),
    )
    return {
        "id": cursor.lastrowid,
        "question_id": question_id,
        "sort_order": next_order,
    }


def remove_deck_item(conn, user_id: int, deck_key: str, question_id: int) -> None:
    deck = get_deck_definition(conn, user_id, deck_key)
    if not deck or deck["kind"] != "custom":
        raise KeyError(deck_key)
    conn.execute(
        "DELETE FROM practice_deck_items WHERE deck_id = ? AND question_bank_id = ?",
        (deck["id"], question_id),
    )

"""Question-bank backed study plans and per-user review state queries."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def _study_timezone() -> ZoneInfo:
    """Return the product study-day timezone, independent of container TZ."""

    name = os.environ.get("STUDY_TIMEZONE", "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _study_day_utc_bounds(now: datetime | None = None) -> tuple[str, str]:
    """UTC-naive bounds for the current learner-facing calendar day."""

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    zone = _study_timezone()
    local_day = current.astimezone(zone).date()
    start = datetime.combine(local_day, time.min, tzinfo=zone).astimezone(UTC)
    end = start + timedelta(days=1)
    return (
        start.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        end.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
    )


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
    # question_bank.frequency 是聚类合并的原始问题文本条数（同一面经里
    # 一道题的多个问法也会被合并计数），不是「出现在几条面经中」；
    # 题卡展示与排序的风险权重都用动态来源数（与题库列表口径一致），
    # 静态变体数不参与展示/排序。
    return (
        "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, "
        f"({frequency_sql}) AS frequency, qb.ai_answer, qb.answer_sources, qb.sources, "
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
    item["is_checkin"] = item.get("review_state") == "mastered"
    item["proficiency"] = int(item.get("proficiency") or 0)
    item["review_count"] = int(item.get("review_count") or 0)
    item["lapse_count"] = int(item.get("lapse_count") or 0)
    item["interval_days"] = float(item.get("interval_days") or 0)
    item["ease_factor"] = float(item.get("ease_factor") or 2.3)
    item["tags"] = _json_or_default(item.get("tags"), item.get("tags") or "")
    item["sources"] = _json_or_default(item.get("sources"), [])
    item["answer_sources"] = _json_or_default(item.get("answer_sources"), None)
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
        return due <= datetime.now(UTC).replace(tzinfo=None)
    except (TypeError, ValueError):
        return True


def _today_review_metrics(conn, user_id: int) -> dict:
    """Return persisted attempts and passed cards for today's study day."""

    start, end = _study_day_utc_bounds()
    activity = conn.execute(
        "SELECT COUNT(*) AS attempts, COUNT(DISTINCT question_bank_id) AS cards "
        "FROM practice_review_events "
        "WHERE user_id = ? AND reviewed_at >= ? AND reviewed_at < ?",
        (user_id, start, end),
    ).fetchone()
    passed = conn.execute(
        "SELECT COUNT(*) AS count FROM practice_review_events event "
        "JOIN ("
        "  SELECT question_bank_id, MAX(id) AS event_id "
        "  FROM practice_review_events "
        "  WHERE user_id = ? AND reviewed_at >= ? AND reviewed_at < ? "
        "  GROUP BY question_bank_id"
        ") latest ON latest.event_id = event.id "
        "WHERE event.rating IN ('good', 'easy')",
        (user_id, start, end),
    ).fetchone()
    return {
        "review_attempts_today": int(activity["attempts"] or 0),
        "attempted_today": int(activity["cards"] or 0),
        "completed_today": int(passed["count"] or 0),
    }


def _reviewed_today_count(conn, user_id: int) -> int:
    """Compatibility helper for callers that only need passed-card count."""

    return _today_review_metrics(conn, user_id)["completed_today"]


def _study_streak(conn, user_id: int) -> dict:
    """Return habit streaks from distinct learner-local review days.

    A streak through yesterday remains active until the current day ends, so
    the UI can invite the learner to extend it instead of declaring it lost in
    the morning.
    """

    rows = conn.execute(
        "SELECT reviewed_at FROM practice_review_events "
        "WHERE user_id = ? ORDER BY reviewed_at ASC",
        (user_id,),
    ).fetchall()
    zone = _study_timezone()
    day_set = {
        datetime.fromisoformat(str(row["reviewed_at"]))
        .replace(tzinfo=UTC)
        .astimezone(zone)
        .date()
        for row in rows
        if row["reviewed_at"]
    }
    days = sorted(day_set)
    today = datetime.now(UTC).astimezone(zone).date()
    studied_today = today in day_set
    cursor = today if studied_today else today - timedelta(days=1)
    current = 0
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)

    longest = run = 0
    previous = None
    for day in days:
        run = run + 1 if previous and day == previous + timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return {
        "study_streak": current,
        "longest_streak": longest,
        "studied_today": studied_today,
    }


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
    """Load a deck ordered as a review queue, not as a random bank page.

    For the due deck, ``total`` is the full due count
    (reviews + check-ins + all new, uncapped) while items may be fewer when
    the new-question budget (explicit max_new or auto from daily_capacity)
    applies — the frontend should render counts from ``len(items)``.
    """

    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    deck, from_clause, where_clause, source_params, where_params, frequency_sql = (
        _base_query_parts(conn, user_id, filter_mode, deck_key)
    )
    join = _review_join("?")
    params = source_params + [user_id, user_id] + where_params
    study_start, study_end = (
        _study_day_utc_bounds() if deck_key == "due" else ("", "")
    )
    total = conn.execute(
        f"SELECT COUNT(*) {from_clause}{join}{where_clause}", params
    ).fetchone()[0]
    custom_order = "pdi.sort_order ASC, " if deck["kind"] == "custom" else ""
    order = (
        # 四桶：到期复习(0) → mastered 抽查(1) → 新题(2) → 未来(3)
        " ORDER BY CASE WHEN uqr.next_review_at IS NULL THEN 2 "
        "WHEN uqr.state = 'mastered' AND datetime(uqr.next_review_at) <= datetime('now') THEN 1 "
        "WHEN datetime(uqr.next_review_at) <= datetime('now') THEN 0 "
        "ELSE 3 END, "
        # 风险权重 = 真实出现频率（动态来源数）× (5 - proficiency)，
        # 与题卡展示口径一致。SQLite 的 ORDER BY 不支持别名参与表达式
        # （别名只允许整体引用，表达式内会解析为静态列 qb.frequency），
        # 所以显式内联动态频率子查询；因相关子查询无自动 CSE，单用户
        # 题量级下重复求值开销可忽略（题库列表排序同样做法）。
        f"CASE WHEN uqr.next_review_at IS NULL THEN ({frequency_sql}) "
        f"ELSE ({frequency_sql}) * (5 - COALESCE(uqr.proficiency, 0)) END DESC, "
        "COALESCE(uqr.next_review_at, '1970-01-01') ASC, "
        f"{custom_order}"
        f"({frequency_sql}) DESC, qb.id ASC"
    )
    # The due queue is not paginated: the frontend always requests the first
    # page (offset == 0), so the budget only applies there.  On offset > 0 the
    # generic pagination path below runs and the new budget is silently bypassed.
    if deck_key == "due" and offset == 0:
        due_cond = _deck_condition("due", "")
        unfinished_today_cond = (
            f"(uqr.last_reviewed_at >= '{study_start}' "
            f"AND uqr.last_reviewed_at < '{study_end}' "
            "AND uqr.last_rating IN ('again', 'hard'))"
        )
        due_where = where_clause.replace(
            due_cond,
            "(uqr.next_review_at IS NOT NULL AND datetime(uqr.next_review_at) <= datetime('now') "
            "AND COALESCE(uqr.state, 'new') != 'mastered' "
            f"AND NOT {unfinished_today_cond})",
        )
        checkin_where = where_clause.replace(
            due_cond,
            "(uqr.state = 'mastered' AND uqr.next_review_at IS NOT NULL "
            "AND datetime(uqr.next_review_at) <= datetime('now') "
            f"AND NOT {unfinished_today_cond})",
        )
        unfinished_where = where_clause.replace(due_cond, unfinished_today_cond)
        new_where = where_clause.replace(due_cond, "(uqr.next_review_at IS NULL)")
        future_where = where_clause.replace(
            due_cond,
            "(uqr.next_review_at IS NOT NULL AND datetime(uqr.next_review_at) > datetime('now') "
            f"AND NOT {unfinished_today_cond})",
        )
        # Due reviews and mastered check-ins are intentionally uncapped (Anki
        # consensus: never cap reviews); only the new-question tail is limited
        # by the budget.
        due_rows = conn.execute(
            _select_sql(from_clause, due_where, frequency_sql) + order, params
        ).fetchall()
        checkin_rows = conn.execute(
            _select_sql(from_clause, checkin_where, frequency_sql) + order, params
        ).fetchall()
        unfinished_rows = conn.execute(
            _select_sql(from_clause, unfinished_where, frequency_sql) + order, params
        ).fetchall()
        today_metrics = _today_review_metrics(conn, user_id)
        completed_today = today_metrics["completed_today"]
        streak = _study_streak(conn, user_id)
        if max_new is not None:
            new_budget = max(0, int(max_new))
            capacity = (
                completed_today
                + len(due_rows)
                + len(unfinished_rows)
                + len(checkin_rows)
                + new_budget
            )
        else:
            # 新题预算 = 每日容量 − 今天已完成 − 尚待处理的到期复习/抽查。
            # 已完成量必须跨刷新扣除，否则每次重新进入都会补满一批新题。
            capacity_row = conn.execute(
                "SELECT daily_capacity FROM user_recruitment_pref WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            capacity = (
                int(capacity_row["daily_capacity"] or 30) if capacity_row else 30
            )
            new_budget = max(
                0,
                capacity
                - completed_today
                - len(due_rows)
                - len(unfinished_rows)
                - len(checkin_rows),
            )
        new_rows = conn.execute(
            _select_sql(from_clause, new_where, frequency_sql)
            + f" ORDER BY ({frequency_sql}) DESC, qb.id ASC LIMIT ?",
            params + [new_budget],
        ).fetchall()
        # 今日答错/模糊的题不会因为短期 next_review_at 而消失。重新进入时，
        # 它们排在新题之前继续巩固；只有 good/easy 才从今日队列毕业。
        rows = due_rows + unfinished_rows + checkin_rows + new_rows
        total = max(int(total), len(rows))
        next_due_row = conn.execute(
            f"SELECT MIN(uqr.next_review_at) AS next_due_at "
            f"{from_clause}{_review_join('?')}{future_where}",
            params,
        ).fetchone()
        forecast_rows = conn.execute(
            f"SELECT date(uqr.next_review_at) AS review_date, COUNT(*) AS count "
            f"{from_clause}{_review_join('?')}{future_where} "
            "AND date(uqr.next_review_at) > date('now') "
            "AND date(uqr.next_review_at) <= date('now', '+7 days') "
            "GROUP BY date(uqr.next_review_at)",
            params,
        ).fetchall()
        forecast_counts = {
            row["review_date"]: int(row["count"] or 0) for row in forecast_rows
        }
        today = datetime.now(UTC).date()
        review_forecast = [
            {
                "date": (today + timedelta(days=day_offset)).isoformat(),
                "count": forecast_counts.get(
                    (today + timedelta(days=day_offset)).isoformat(), 0
                ),
            }
            for day_offset in range(1, 8)
        ]
        deck = {
            **deck,
            "daily_capacity": capacity,
            **today_metrics,
            "remaining_today": len(rows),
            "planned_today": completed_today + len(rows),
            "due_review_count": len(due_rows),
            "relearning_count": len(unfinished_rows),
            "checkin_count": len(checkin_rows),
            "new_question_count": len(new_rows),
            "next_due_at": next_due_row["next_due_at"] if next_due_row else None,
            "review_forecast": review_forecast,
            **streak,
        }
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
        [
            {
                **_normalise_question(row),
                "is_daily_relearning": (
                    deck_key == "due"
                    and row["last_rating"] in {"again", "hard"}
                    and study_start <= str(row["last_reviewed_at"] or "") < study_end
                ),
            }
            for row in rows
        ],
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

"""洞察工作台的数据聚合服务。

这里集中定义洞察的事实口径，路由层只负责认证、线程池调度和返回 JSON。
"""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json

from app.db.connection import get_db_connection, get_user_job_position
from app.db.queries import build_bank_where_clause


def _count_unique_sources(sources_raw) -> int:
    """sources JSON（[{url, company, round}]）按 url 去重计数；异常返回 0。

    洞察页"被问次数"口径：独立来源数而非问法数（变体归一化配套，
    避免同一面试多个问法虚高 frequency）。
    """
    if not sources_raw:
        return 0
    try:
        sources = json.loads(sources_raw)
    except (json.JSONDecodeError, TypeError):
        return 0
    if not isinstance(sources, list):
        return 0
    urls = {s.get("url") for s in sources if isinstance(s, dict) and s.get("url")}
    return len(urls)


API_VERSION = 1

# 这些是导入/分类失败时的兜底值，没有稳定的岗位语义，不进入能力雷达。
NON_REFERENCE_TOPIC_NAMES = ("其他", "未分类", "其他/未分类", "未分类(API漏标)")


def _topic_name(cat2, cat1) -> str:
    return str(cat2 or cat1 or "未分类").strip()


def _is_reference_topic(topic_name: str) -> bool:
    return topic_name not in NON_REFERENCE_TOPIC_NAMES


def _status_for_practice(practice_count: int, average_score: float | None) -> tuple[str, str]:
    if practice_count == 0:
        return "not_started", "尚无个人练习记录"
    if average_score is None:
        return "evidence_only", "已有练习记录，但还没有结构化评分"
    if average_score < 60:
        return "needs_work", "最近练习平均分低于 60"
    if average_score < 80:
        return "developing", "已有练习记录，仍可继续巩固"
    return "stable", "练习平均分达到 80 以上"


def _action_for_item(item: dict) -> dict:
    status = item["status"]
    if status == "needs_work":
        description = "已有练习记录，但平均分偏低，建议优先复练。"
        action = "继续练习"
        priority = "high"
    elif status == "not_started":
        description = "题库覆盖充分，但还没有个人练习证据。"
        action = "开始练习"
        priority = "high"
    elif status == "developing":
        description = "已经开始练习，建议再做一轮巩固。"
        action = "巩固练习"
        priority = "medium"
    elif status == "evidence_only":
        description = "有练习记录，但还缺少结构化评分。"
        action = "补充练习"
        priority = "medium"
    else:
        description = "当前练习表现稳定，可转向其他薄弱主题。"
        action = "查看题目"
        priority = "low"

    return {
        "id": f"topic:{item['id']}",
        "title": item["name"],
        "description": description,
        "question_count": item["question_count"],
        "priority": priority,
        "action": action,
    }

def _scope_condition(alias: str, user_id: int) -> tuple[str, list]:
    return (
        f"(({alias}.owner_id IS NULL AND {alias}.status = 'approved') "
        f"OR {alias}.owner_id = ?) AND {alias}.deleted_at IS NULL",
        [user_id],
    )


def build_insights_snapshot(user: dict) -> dict:
    """同步聚合当前用户当前岗位的洞察快照。"""

    user_id = int(user["id"])
    position_id, position_name = get_user_job_position(user_id)

    with get_db_connection() as conn:
        from_clause, bank_where, bank_params = build_bank_where_clause(
            user_id, "all", "qb"
        )
        bank_rows = conn.execute(
            f"SELECT qb.id, qb.cat1, qb.cat2, qb.frequency, qb.sources {from_clause} {bank_where}",
            bank_params,
        ).fetchall()

        topic_rows = defaultdict(
            lambda: {
                "question_count": 0,
                "question_frequency": 0,
                "question_ids": [],
            }
        )
        question_to_topic = {}
        for row in bank_rows:
            topic_name = _topic_name(row["cat2"], row["cat1"])
            if not _is_reference_topic(topic_name):
                continue
            topic = topic_rows[topic_name]
            topic["question_count"] += 1
            # 口径修复：洞察页"被问次数"用独立来源数（sources 按 url 去重），
            # 避免同一面试多个问法虚高 frequency（变体归一化的配套）
            topic["question_frequency"] += _count_unique_sources(row["sources"])
            topic["question_ids"].append(row["id"])
            question_to_topic[row["id"]] = topic_name

        practice_by_topic = defaultdict(lambda: {"count": 0, "scores": []})
        practiced_question_ids = set()
        evaluated_answer_count = 0
        for row in conn.execute(
            "SELECT question_bank_id, score FROM practice_review_events WHERE user_id = ? AND source = 'self_check'",
            (user_id,),
        ).fetchall():
            topic_name = question_to_topic.get(row["question_bank_id"])
            if topic_name is None:
                continue
            practiced_question_ids.add(row["question_bank_id"])
            practice_by_topic[topic_name]["count"] += 1
            if row["score"] is not None:
                evaluated_answer_count += 1
                practice_by_topic[topic_name]["scores"].append(float(row["score"]))

        readiness_items = []
        proficiency_by_topic = {
            row["topic"]: row["proficiency"]
            for row in _radar_topics(conn, user_id, position_name, limit=10000)
        }
        for topic_name, topic in topic_rows.items():
            practice = practice_by_topic[topic_name]
            scores = practice["scores"]
            average_score = round(sum(scores) / len(scores), 1) if scores else None
            status, reason = _status_for_practice(practice["count"], average_score)
            readiness_items.append(
                {
                    "id": topic_name,
                    "name": topic_name,
                    "question_count": topic["question_count"],
                    "question_frequency": topic["question_frequency"],
                    "practice_count": practice["count"],
                    "average_score": average_score,
                    "proficiency": proficiency_by_topic.get(topic_name),
                    "status": status,
                    "reason": reason,
                }
            )

        status_rank = {
            "needs_work": 0,
            "not_started": 1,
            "evidence_only": 2,
            "developing": 3,
            "stable": 4,
        }
        readiness_items.sort(
            key=lambda item: (
                status_rank.get(item["status"], 9),
                -item["question_frequency"],
                item["name"],
            )
        )
        actions = [_action_for_item(item) for item in readiness_items[:3]]

        jd_scope, jd_scope_params = _scope_condition("jd", user_id)
        jd_position = "(jd.job_position = ? OR jd.job_position = '' OR jd.job_position IS NULL)"
        jd_count = conn.execute(
            f"SELECT COUNT(*) FROM jd WHERE {jd_scope} AND {jd_position}",
            [*jd_scope_params, position_name],
        ).fetchone()[0]

        interview_scope, interview_scope_params = _scope_condition("i", user_id)
        interview_position = "(i.job_position = ? OR i.job_position = '' OR i.job_position IS NULL)"
        interview_count = conn.execute(
            f"SELECT COUNT(*) FROM interview i WHERE {interview_scope} AND {interview_position}",
            [*interview_scope_params, position_name],
        ).fetchone()[0]

        review_rows = conn.execute(
            "SELECT c.id, c.title, c.mode, c.job_position, c.created_at, c.updated_at, "
            "(SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.id) AS message_count "
            "FROM chat_conversations c "
            "WHERE c.user_id = ? AND (c.job_position = ? OR c.job_position = '' OR c.job_position IS NULL) "
            "ORDER BY c.updated_at DESC, c.created_at DESC LIMIT 8",
            (user_id, position_name),
        ).fetchall()
        review_total = conn.execute(
            "SELECT COUNT(*) FROM chat_conversations c "
            "WHERE c.user_id = ? AND (c.job_position = ? OR c.job_position = '' OR c.job_position IS NULL)",
            (user_id, position_name),
        ).fetchone()[0]
        reviews = [
            {
                "id": row["id"],
                "title": row["title"] or "未命名面试",
                "mode": row["mode"],
                "job_position": row["job_position"] or position_name,
                "message_count": row["message_count"] or 0,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in review_rows
        ]

        unassigned_scope, unassigned_params = _scope_condition("qb", user_id)
        unassigned_count = conn.execute(
            f"SELECT COUNT(*) FROM question_bank qb WHERE {unassigned_scope} "
            "AND (qb.job_position = '' OR qb.job_position IS NULL)",
            unassigned_params,
        ).fetchone()[0]

        # 岗位高频待练：面经 questions_detail 按 cat2 聚合被问频次（降序）
        # 仅当前岗位 + 当前用户可见作用域（他人私有面经不得泄漏进聚合），
        # JOIN interview iv 并复用 _scope_condition 过滤 owner/公共 approved，排除已删，
        # 过滤「其他」/空分类等无意义主题。
        high_scope, high_scope_params = _scope_condition("iv", user_id)
        high_freq_rows = conn.execute(
            "SELECT qd.cat2 AS topic, COUNT(*) AS frequency "
            "FROM questions_detail qd JOIN interview iv ON qd.url = iv.url "
            f"WHERE {high_scope} AND (iv.job_position = ? OR iv.job_position = '' OR iv.job_position IS NULL) "
            "AND qd.deleted_at IS NULL "
            "AND qd.cat2 IS NOT NULL AND qd.cat2 != '' AND qd.cat2 NOT IN ('其他', '未分类') "
            "GROUP BY qd.cat2 ORDER BY frequency DESC LIMIT 10",
            [*high_scope_params, position_name],
        ).fetchall()
        high_frequency = [
            {"topic": row["topic"], "frequency": int(row["frequency"])}
            for row in high_freq_rows
        ]

    has_practice_evidence = bool(practiced_question_ids)
    return {
        "version": API_VERSION,
        "target_position": {
            "name": position_name,
            "source": "position_id" if position_id else "user_position",
        },
        "summary": {
            "question_count": len(bank_rows),
            "jd_count": jd_count,
            "interview_count": interview_count,
            "practiced_question_count": len(practiced_question_ids),
            "evaluated_answer_count": evaluated_answer_count,
            "evidence_state": "available" if evaluated_answer_count else "insufficient",
        },
        "actions": actions,
        "readiness": {"items": readiness_items},
        "high_frequency": high_frequency,
        "reviews": {"total": review_total, "items": reviews},
        "data_quality": {
            "unassigned_question_count": unassigned_count,
            "has_practice_evidence": has_practice_evidence,
            "message": (
                "当前没有结构化练习评分，准备度仅基于岗位和题库事实。"
                if not evaluated_answer_count
                else "准备度包含个人练习评分证据。"
            ),
        },
    }


_DIFFICULTY_LABELS = {"easy": "简单", "medium": "中等", "hard": "困难"}


def _difficulty_label(raw: str | None) -> str:
    return _DIFFICULTY_LABELS.get((raw or "").lower(), raw or "未标注")


def _activity_day_counts(conn, user_id: int, since: str) -> dict[str, int]:
    """按天统计练习次数（正式答题 + 闪卡复习）。"""
    counts: dict[str, int] = {}
    # 双写收敛: user_practice_history 已停写; 只统计 practice_review_events
    # (评估 + 闪卡复习), 修复同一评估被双计的问题。
    for row in conn.execute(
        "SELECT date(reviewed_at) AS day, COUNT(*) AS cnt FROM practice_review_events "
        "WHERE user_id = ? AND reviewed_at >= ? GROUP BY day",
        (user_id, since),
    ).fetchall():
        counts[row["day"]] = counts.get(row["day"], 0) + row["cnt"]
    return counts


def _daily_avg_scores(conn, user_id: int, since: str) -> dict[str, float]:
    """按天统计答题平均分（仅 user_practice_history 的有分记录）。"""
    avgs = {}
    for row in conn.execute(
        "SELECT date(reviewed_at) AS day, AVG(score) AS avg_s FROM practice_review_events "
        "WHERE user_id = ? AND score IS NOT NULL AND source = 'self_check' AND reviewed_at >= ? GROUP BY day",
        (user_id, since),
    ).fetchall():
        avgs[row["day"]] = round(row["avg_s"] or 0, 1)
    return avgs


def _build_daily_series(
    conn, user_id: int, days: int, today: date
) -> list[dict]:
    """生成近 N 天的 {date, count, avg_score} 序列（含今天，无活动补 0）。"""
    since = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    counts = _activity_day_counts(conn, user_id, since)
    avgs = _daily_avg_scores(conn, user_id, since)
    series = []
    for i in range(days - 1, -1, -1):
        key = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        series.append(
            {
                "date": key,
                "count": counts.get(key, 0),
                "avg_score": avgs.get(key, 0),
            }
        )
    return series


def _practice_days(conn, user_id: int) -> set[str]:
    """返回用户全部有练习活动的日期集合（跨 90 天窗口，用于 streak）。"""
    days = set()
    # 双写收敛后 user_practice_history 已停写, 只统计 review 事件表
    for table, column in (
        ("practice_review_events", "reviewed_at"),
    ):
        rows = conn.execute(
            f"SELECT DISTINCT date({column}) AS day FROM {table} WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        for row in rows:
            if row["day"]:
                days.add(row["day"])
    return days


def _streak_stats(days: set[str], today: str) -> dict:
    """计算当前连续天数与历史最长连续天数（自然日，今天未打卡不断连）。"""
    today_date = datetime.strptime(today, "%Y-%m-%d").date()
    cursor = today_date if today in days else today_date - timedelta(days=1)
    current = 0
    while cursor.strftime("%Y-%m-%d") in days:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    prev = None
    for day_str in sorted(days):
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
        run = run + 1 if prev is not None and (day - prev).days == 1 else 1
        longest = max(longest, run)
        prev = day
    return {"current": current, "longest": longest}


def _radar_topics(
    conn, user_id: int, position_name: str, limit: int = 8
) -> list[dict]:
    """取当前岗位最需要巩固的 N 个 SRS 主题（cat2 fallback cat1）。"""
    excluded_placeholders = ", ".join("?" for _ in NON_REFERENCE_TOPIC_NAMES)
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(qb.cat2, ''), NULLIF(qb.cat1, ''), '未分类') AS topic, "
        "AVG(uqr.proficiency) AS prof "
        "FROM user_question_review uqr "
        "JOIN question_bank qb ON qb.id = uqr.question_bank_id "
        "WHERE uqr.user_id = ? AND qb.deleted_at IS NULL "
        "AND (qb.job_position = ? OR qb.job_position = '' OR qb.job_position IS NULL) "
        f"AND COALESCE(NULLIF(qb.cat2, ''), NULLIF(qb.cat1, ''), '未分类') "
        f"NOT IN ({excluded_placeholders}) "
        "GROUP BY topic ORDER BY prof ASC, topic ASC LIMIT ?",
        (user_id, position_name, *NON_REFERENCE_TOPIC_NAMES, limit),
    ).fetchall()
    return [{"topic": row["topic"], "proficiency": round(row["prof"] or 0)} for row in rows]


def _difficulty_stats(conn, user_id: int) -> list[dict]:
    """按难度统计练习次数与正确率（score >= 60 算对）。"""
    rows = conn.execute(
        "SELECT qb.difficulty AS d, COUNT(*) AS total, "
        "SUM(CASE WHEN pre.score >= 60 THEN 1 ELSE 0 END) AS correct "
        "FROM practice_review_events pre "
        "JOIN question_bank qb ON qb.id = pre.question_bank_id "
        "WHERE pre.user_id = ? AND pre.score IS NOT NULL AND pre.source = 'self_check' "
        "GROUP BY qb.difficulty",
        (user_id,),
    ).fetchall()
    stats = []
    for row in rows:
        total = row["total"]
        correct = row["correct"] or 0
        stats.append(
            {
                "difficulty": _difficulty_label(row["d"]),
                "count": total,
                "correct_count": correct,
                "needs_work_count": total - correct,
                "correct_rate": round(correct * 100 / total),
            }
        )
    stats.sort(key=lambda item: -item["count"])
    return stats


def _recent_activities(conn, user_id: int, limit: int = 10) -> list[dict]:
    """合并最近的答题与复习事件，按时间倒序取前 N 条。"""
    answers = conn.execute(
        "SELECT pre.id, 'answer' AS type, pre.question_bank_id, pre.score, "
        "pre.reviewed_at AS ts FROM practice_review_events pre "
        "WHERE pre.user_id = ? AND pre.source = 'self_check' ORDER BY pre.reviewed_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    reviews = conn.execute(
        "SELECT pre.id, 'review' AS type, pre.question_bank_id, NULL AS score, "
        "pre.rating, pre.reviewed_at AS ts FROM practice_review_events pre "
        "WHERE pre.user_id = ? AND pre.source != 'self_check' "
        "ORDER BY pre.reviewed_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    merged = sorted(
        [dict(row) for row in answers] + [dict(row) for row in reviews],
        key=lambda item: item["ts"] or "",
        reverse=True,
    )[:limit]

    questions = {}
    qids = [item["question_bank_id"] for item in merged]
    if qids:
        placeholders = ",".join("?" * len(qids))
        for row in conn.execute(
            f"SELECT id, question, difficulty, cat2 FROM question_bank "
            f"WHERE id IN ({placeholders})",
            qids,
        ).fetchall():
            questions[row["id"]] = dict(row)

    result = []
    for item in merged:
        q = questions.get(item["question_bank_id"]) or {}
        result.append(
            {
                "id": item["id"],
                "type": item["type"],
                "question": q.get("question") or "题目已删除",
                "difficulty": _difficulty_label(q.get("difficulty")),
                "topic": q.get("cat2") or "未分类",
                "score": item.get("score"),
                "rating": item.get("rating"),
                "created_at": item.get("ts"),
            }
        )
    return result


def build_practice_activity(user: dict) -> dict:
    """同步聚合当前用户的练习足迹数据（热力图/连击/趋势/雷达/难度/最近刷题）。"""

    user_id = int(user["id"])
    _, position_name = get_user_job_position(user_id)
    with get_db_connection() as conn:
        today = datetime.now(timezone.utc).date()
        heatmap = _build_daily_series(conn, user_id, 365, today)
        trend = _build_daily_series(conn, user_id, 30, today)
        days = _practice_days(conn, user_id)
        streak = _streak_stats(days, today.strftime("%Y-%m-%d"))
        radar = _radar_topics(conn, user_id, position_name)
        difficulty = _difficulty_stats(conn, user_id)
        recent = _recent_activities(conn, user_id)

    return {
        "version": API_VERSION,
        "heatmap": heatmap,
        "streak": streak,
        "trend": trend,
        "radar": radar,
        "difficulty": difficulty,
        "recent": recent,
    }

"""洞察工作台的数据聚合服务。

这里集中定义洞察的事实口径，路由层只负责认证、线程池调度和返回 JSON。
"""

from collections import defaultdict

from app.db.connection import get_db_connection, get_user_job_position
from app.db.queries import build_bank_where_clause


API_VERSION = 1


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
            f"SELECT qb.id, qb.cat1, qb.cat2, qb.frequency {from_clause} {bank_where}",
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
            topic_name = row["cat2"] or row["cat1"] or "未分类"
            topic = topic_rows[topic_name]
            topic["question_count"] += 1
            topic["question_frequency"] += int(row["frequency"] or 0)
            topic["question_ids"].append(row["id"])
            question_to_topic[row["id"]] = topic_name

        practice_by_topic = defaultdict(lambda: {"count": 0, "scores": []})
        practiced_question_ids = set()
        evaluated_answer_count = 0
        for row in conn.execute(
            "SELECT question_bank_id, score FROM user_practice_history WHERE user_id = ?",
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

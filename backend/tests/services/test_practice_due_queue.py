"""今日复习 (due) deck: review-first risk-weighted queue and new-question budget."""

from datetime import datetime, timedelta

from app.db.connection import get_db_connection
from app.services.practice_deck_service import list_decks, list_deck_questions
from app.services.practice_review_service import record_review

POSITION = "agent开发/大模型应用开发/大模型开发"


def _seed(conn):
    rows = (
        (1, "Q1", "Java", "线程", "L1-基础", 5),
        (2, "Q2", "MySQL", "索引", "L2-中等", 1),
        (3, "Q3", "Redis", "缓存", "L3-困难", 2),
    )
    for qid, question, cat2, tags, difficulty, frequency in rows:
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency, job_position) "
            "VALUES (?, ?, '基础', ?, ?, ?, ?, 'approved', NULL, ?, ?)",
            (qid, question, cat2, tags, difficulty, f"A{qid}", frequency, POSITION),
        )
    conn.commit()


def _fmt(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _review(conn, question_id, *, proficiency, review_count=3, interval_days=5.0, next_review_at):
    conn.execute(
        "INSERT INTO user_question_review "
        "(user_id, question_bank_id, state, proficiency, review_count, interval_days, ease_factor, next_review_at, updated_at) "
        "VALUES (1, ?, 'review', ?, ?, ?, 2.3, ?, CURRENT_TIMESTAMP)",
        (question_id, proficiency, review_count, interval_days, next_review_at),
    )
    conn.commit()


def test_due_deck_is_first_and_counted(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        decks = list_decks(conn, 1)
    assert decks[0]["key"] == "due"
    assert decks[0]["name"] == "今日复习"
    assert decks[0]["total"] == 3  # 新题（未复习）也计入 due


def test_due_queue_orders_reviews_before_new_questions(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=2,
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        _review(
            conn,
            2,
            proficiency=4,
            review_count=6,
            interval_days=12.0,
            next_review_at=_fmt(datetime.utcnow() + timedelta(days=10)),
        )
        _, items, total = list_deck_questions(conn, 1, "due")
    # 未来复习(2) 不属于今日复习；到期复习(1) 最前，新题(3) 其次
    assert total == 2
    assert [item["id"] for item in items] == [1, 3]


def test_all_deck_orders_due_then_new_then_future(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=2,
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        _review(
            conn,
            2,
            proficiency=4,
            review_count=6,
            interval_days=12.0,
            next_review_at=_fmt(datetime.utcnow() + timedelta(days=10)),
        )
        _, items, total = list_deck_questions(conn, 1, "all")
    assert total == 3
    # 到期复习(1) 最前 → 新题(3) 其次 → 未来(2) 最后
    assert [item["id"] for item in items] == [1, 3, 2]


def test_due_queue_new_questions_ordered_by_active_sources(test_db):
    """新题预算内排序使用活跃面经来源数（动态频率），静态变体数不参与"""
    with get_db_connection() as conn:
        _seed(conn)  # 静态 frequency: Q1=5, Q2=1, Q3=2
        for i in range(4):
            url = f"http://q3-source-{i}.com"
            conn.execute(
                "INSERT INTO interview (url, company, round, owner_id, status) "
                "VALUES (?, '公司C', '一面', NULL, 'approved')",
                (url,),
            )
            conn.execute(
                "INSERT INTO question_sources (question_bank_id, url, company, round) "
                "VALUES (3, ?, '公司C', '一面')",
                (url,),
            )
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    # 动态来源数: Q3=4, Q1=0, Q2=0 → Q3 最前，同为 0 的按 id
    assert [item["id"] for item in items] == [3, 1, 2]


def test_due_queue_new_questions_without_sources_order_by_id(test_db):
    """无活跃来源的新题按 id 升序，静态变体数不再决定新题顺序"""
    with get_db_connection() as conn:
        _seed(conn)
        _, items, _ = list_deck_questions(conn, 1, "due")
    assert [item["id"] for item in items] == [1, 2, 3]


def test_due_queue_risk_weight_orders_due_reviews(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=4,  # 静态 5 但无活跃来源 → 风险 0 × (5-4) = 0
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        _review(
            conn,
            2,
            proficiency=1,  # 静态 1 但有 4 个活跃来源 → 风险 4 × (5-1) = 16
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=1)),
        )
        for i in range(4):
            url = f"http://q2-review-{i}.com"
            conn.execute(
                "INSERT INTO interview (url, company, round, owner_id, status) "
                "VALUES (?, '公司C', '一面', NULL, 'approved')",
                (url,),
            )
            conn.execute(
                "INSERT INTO question_sources (question_bank_id, url, company, round) "
                "VALUES (2, ?, '公司C', '一面')",
                (url,),
            )
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    # 真实出现频率（动态来源数）驱动风险权重：静态变体数 5 不再占优；
    # 低熟练度 + 真实高频排在前面，即使到期更晚；新题(3) 兜底
    assert [item["id"] for item in items] == [2, 1, 3]


def test_due_queue_max_new_budget(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=2,
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due", max_new=0)
    assert [item["id"] for item in items] == [1]


def test_due_queue_max_new_budget_limits_new_questions(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _, items, total = list_deck_questions(conn, 1, "due", max_new=1)
    assert total == 3
    # 无到期复习，只放 1 道最高频新题
    assert [item["id"] for item in items] == [1]


def test_due_queue_max_new_ignored_when_offset(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=2,
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        _, items, _ = list_deck_questions(conn, 1, "due", max_new=0, offset=1)
    # offset>0 时预算不生效：走通用分页路径，新题(3) 依然返回（max_new=0 被忽略）；
    # 无活跃来源的新题按 id 升序
    assert [item["id"] for item in items] == [2, 3]


def _seed_mastered(conn):
    conn.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "interval_days, ease_factor, next_review_at, updated_at) "
        "VALUES (1, 2, 'mastered', 5, 9, 30.0, 2.6, datetime('now', '-1 days'), CURRENT_TIMESTAMP)"
    )
    conn.commit()


def test_due_queue_orders_review_checkin_new(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=2,
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        _seed_mastered(conn)
        _, items, total = list_deck_questions(conn, 1, "due")
    # 到期复习(1) → mastered 抽查(2) → 新题(3)
    assert [i["id"] for i in items] == [1, 2, 3]
    assert items[1]["is_checkin"] is True
    assert items[0]["is_checkin"] is False


def test_due_queue_checkin_after_future_review(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
            "interval_days, ease_factor, next_review_at, updated_at) "
            "VALUES (1, 1, 'mastered', 5, 9, 30.0, 2.6, datetime('now', '+5 days'), CURRENT_TIMESTAMP)"
        )
        conn.commit()
        _, due_items, _ = list_deck_questions(conn, 1, "due")
        _, all_items, _ = list_deck_questions(conn, 1, "all")
    # mastered 但未来到期：不进今日复习的抽查桶（due 队列本身不含未来题），
    # 全部题队列中排在最后（新题 → 未来）；无活跃来源的新题按 id 升序
    assert [i["id"] for i in due_items] == [2, 3]
    assert [i["id"] for i in all_items] == [2, 3, 1]
    assert all_items[-1]["id"] == 1


def test_due_queue_auto_new_budget_from_capacity(test_db):
    with get_db_connection() as conn:
        _seed(conn)
        _review(
            conn,
            1,
            proficiency=2,
            next_review_at=_fmt(datetime.utcnow() - timedelta(days=2)),
        )
        _seed_mastered(conn)
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
            "VALUES (1, 2027, 'autumn', 3, 'standard')"
        )
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    # 容量 3：due 1 + 抽查 1 = 2 已占 → 新题预算 1
    assert [i["id"] for i in items] == [1, 2, 3]
    with get_db_connection() as conn:
        conn.execute("UPDATE user_recruitment_pref SET daily_capacity = 1 WHERE user_id = 1")
        conn.commit()
        _, items, _ = list_deck_questions(conn, 1, "due")
    # 容量 1：due 1 + 抽查 1 = 2 已占 → 新题预算 0
    assert [i["id"] for i in items] == [1, 2]


def test_due_queue_daily_budget_does_not_replenish_after_reload(test_db):
    """今天已完成的新题必须占用每日容量，刷新不能再补满一轮新题。"""

    with get_db_connection() as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO user_recruitment_pref "
            "(user_id, graduation_year, batch, daily_capacity, pace) "
            "VALUES (1, 2027, 'autumn', 2, 'standard')"
        )
        record_review(conn, user_id=1, question_id=1, rating="good")
        conn.commit()

        deck, items, total = list_deck_questions(conn, 1, "due")

    assert total == 2
    assert [item["id"] for item in items] == [2]
    assert deck["daily_capacity"] == 2
    assert deck["completed_today"] == 1
    assert deck["remaining_today"] == 1
    assert deck["planned_today"] == 2
    assert deck["next_due_at"] is not None
    assert len(deck["review_forecast"]) == 7
    assert sum(day["count"] for day in deck["review_forecast"]) == 1

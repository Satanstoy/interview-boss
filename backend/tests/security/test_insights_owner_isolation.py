"""insights 洞察隔离回归测试。

覆盖安全审计发现 #2（D5）：
- build_insights_snapshot 的 high_frequency（岗位高频待练）原直接聚合 question_bank
  之外的所有 questions_detail，无 owner 过滤，把其他用户私有面经的 cat2 主题+频次
  泄漏进每个用户可见的聚合。
- 修复：high_frequency 与 data.py/analytics.py 一致，JOIN interview iv 并按
  _scope_condition（owner 或公共 approved + 未删除）过滤调用者作用域。
"""

from __future__ import annotations


def _make_user(test_db, username: str) -> int:
    cur = test_db.execute(
        "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
        "VALUES (?, 'x', ?, 0, 'private')",
        (username, f"{username}@example.com"),
    )
    test_db.commit()
    return cur.lastrowid


def _seed_questions_detail(test_db, user_id, cat2: str, job_position: str = ""):
    """插入一条私有面经及其 questions_detail 行。"""
    cur = test_db.execute(
        "INSERT INTO interview (url, company, round, owner_id, job_position, status, questions_list) "
        "VALUES (?, '公司', '一面', ?, ?, 'active', '[]')",
        (f"https://x-{cat2}/a", user_id, job_position),
    )
    interview_id = cur.lastrowid
    test_db.execute(
        "INSERT INTO questions_detail (url, cat2, deleted_at, job_position) "
        "VALUES (?, ?, NULL, ?)",
        (f"https://x-{cat2}/a", cat2, job_position),
    )
    test_db.commit()
    return interview_id


class TestInsightsHighFrequencyOwnerIsolation:
    """high_frequency 不得包含他人私有面经主题。"""

    def test_high_frequency_excludes_other_users_private_topics(self, test_db):
        _make_user(test_db, "owner_b")
        me = _make_user(test_db, "alice_insights")
        # 其他用户的一条私有面经主题
        _seed_questions_detail(test_db, me - 1, "私密主题_不该出现")

        from app.services.insights import build_insights_snapshot

        snapshot = build_insights_snapshot({"id": me})
        topics = {row["topic"] for row in snapshot["high_frequency"]}
        assert "私密主题_不该出现" not in topics

    def test_high_frequency_includes_own_private_topics(self, test_db):
        me = _make_user(test_db, "bob_insights")
        _seed_questions_detail(test_db, me, "我的私有主题")

        from app.services.insights import build_insights_snapshot

        snapshot = build_insights_snapshot({"id": me})
        topics = {row["topic"] for row in snapshot["high_frequency"]}
        assert "我的私有主题" in topics

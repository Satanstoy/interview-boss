"""BUG: 刷题题卡出现频率显示错误

根因 1（展示语义）: practice_deck_service 的 SELECT 用
  MAX(COALESCE(qb.frequency, 0), dyn_freq) 作为题卡频率。
  qb.frequency 是聚类合并的原始问题文本条数（1 条面经里同一题
  的多个问法也被计入），与「出现在几条面经中」不是同一概念，
  导致题卡显示虚高（如 static=6、真实来源 1 条 → 显示 6）。

根因 2（动态 SQL 计数）: get_dynamic_frequency_sql 未过滤
  qs.deleted_at（面经删除后来源仍计数）；且 JOIN interview 在
  同一 URL 同时存在公共（owner_id NULL）与用户私有面经时不
  去重，COUNT(*) 翻倍。
"""

from app.db.connection import get_db_connection
from app.db.queries import get_dynamic_frequency_sql
from app.services.practice_deck_service import list_deck_questions

POSITION = "agent开发/大模型应用开发/大模型开发"


def _seed_base(conn):
    """一道 static frequency=6、但只有 1 条活跃面经来源的公共题"""
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency, job_position) "
        "VALUES (1, 'Q1', '基础', 'C1', 'tag', 'L1-基础', 'A1', 'approved', NULL, 6, ?)",
        (POSITION,),
    )
    conn.execute(
        "INSERT INTO interview (url, company, round, owner_id, status) "
        "VALUES ('http://a.com', '公司A', '一面', NULL, 'approved')"
    )
    conn.execute(
        "INSERT INTO question_sources (question_bank_id, url, company, round) "
        "VALUES (1, 'http://a.com', '公司A', '一面')"
    )
    conn.commit()


class TestDynamicFrequencySql:
    """get_dynamic_frequency_sql 的计数口径"""

    def test_soft_deleted_source_not_counted(self, test_db):
        """qs 被软删除（面经已删）后不应再计入动态频率"""
        _seed_base(test_db)
        test_db.execute(
            "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE question_bank_id = 1 AND url = 'http://a.com'"
        )
        test_db.commit()
        sql = get_dynamic_frequency_sql("all", 1, "qb")
        row = test_db.execute(
            f"SELECT ({sql}) AS frequency FROM question_bank qb WHERE qb.id = 1"
        ).fetchone()
        assert row["frequency"] == 0, (
            f"软删除来源不应计数，got {row['frequency']}"
        )

    def test_same_url_public_and_private_interview_counted_once(self, test_db):
        """同一 URL 同时有公共面经和用户私有面经时，频率只计 1 次"""
        _seed_base(test_db)
        test_db.execute(
            "INSERT INTO interview (url, company, round, owner_id, status) "
            "VALUES ('http://a.com', '公司A', '一面', 1, 'approved')"
        )
        test_db.commit()
        sql = get_dynamic_frequency_sql("all", 1, "qb")
        row = test_db.execute(
            f"SELECT ({sql}) AS frequency FROM question_bank qb WHERE qb.id = 1"
        ).fetchone()
        assert row["frequency"] == 1, (
            f"同一 URL 只应计 1 次，got {row['frequency']}"
        )

    def test_soft_deleted_interview_not_counted(self, test_db):
        """interview 软删后来源不应计数"""
        _seed_base(test_db)
        test_db.execute(
            "UPDATE interview SET deleted_at = CURRENT_TIMESTAMP WHERE url = 'http://a.com'"
        )
        test_db.commit()
        sql = get_dynamic_frequency_sql("all", 1, "qb")
        row = test_db.execute(
            f"SELECT ({sql}) AS frequency FROM question_bank qb WHERE qb.id = 1"
        ).fetchone()
        assert row["frequency"] == 0, (
            f"软删面经不应计数，got {row['frequency']}"
        )


class TestDeckCardFrequency:
    """刷题题卡展示的频率应等于活跃面经来源数（与题库列表口径一致）"""

    def test_card_frequency_uses_dynamic_not_static(self, test_db):
        """static=6、动态=1 时，题卡 frequency 应为 1"""
        _seed_base(test_db)
        with get_db_connection() as conn:
            _, items, _ = list_deck_questions(conn, 1, "all")
        assert len(items) == 1
        assert items[0]["frequency"] == 1, (
            f"题卡频率应展示真实出现次数 1，got {items[0]['frequency']}"
        )

    def test_card_frequency_zero_when_no_active_source(self, test_db):
        """没有任何活跃来源时题卡频率为 0（而不是 static 残留值）"""
        _seed_base(test_db)
        test_db.execute(
            "UPDATE question_sources SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE question_bank_id = 1 AND url = 'http://a.com'"
        )
        test_db.commit()
        with get_db_connection() as conn:
            _, items, _ = list_deck_questions(conn, 1, "all")
        assert items[0]["frequency"] == 0, (
            f"无来源时频率应为 0，got {items[0]['frequency']}"
        )

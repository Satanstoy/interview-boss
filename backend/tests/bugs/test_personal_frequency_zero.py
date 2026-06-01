"""
BUG-003: Personal 模式下频率显示为 0

根因：personal 模式用 i.owner_id = user_id 过滤面试来源，
但 personal 题目的来源可能是公共面试（owner_id IS NULL），
导致 dynamic frequency = 0。

修复：personal 模式频率统计所有面试来源（不按 owner_id 过滤）。
"""
import sqlite3
import pytest


class TestPersonalFrequencyZero:
    """验证 personal 模式下频率不再为 0"""

    def _seed_data(self, conn: sqlite3.Connection):
        """插入测试数据：admin 用户 + personal 题目 + 公共面试 + question_sources"""
        # 清理迁移种子数据，避免 UNIQUE 冲突
        conn.execute("DELETE FROM question_sources")
        conn.execute("DELETE FROM question_bank")
        conn.execute("DELETE FROM interview")
        conn.execute("DELETE FROM users")
        conn.commit()

        # admin 用户 (id=1)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, bank_mode) "
            "VALUES (1, 'admin', 'fake_hash', 1, 'personal')"
        )

        # 公共面试记录 (owner_id IS NULL)
        conn.execute(
            "INSERT INTO interview (id, url, company, round, owner_id) "
            "VALUES (1, 'http://interview-a.com', 'CompanyA', '1面', NULL)"
        )
        conn.execute(
            "INSERT INTO interview (id, url, company, round, owner_id) "
            "VALUES (2, 'http://interview-b.com', 'CompanyB', '2面', NULL)"
        )

        # personal 题目 (owner_id = 1, 即 admin 的个人题目)
        conn.execute(
            "INSERT INTO question_bank (id, question, owner_id, frequency, status) "
            "VALUES (1, '什么是闭包?', 1, 1, 'approved')"
        )
        conn.execute(
            "INSERT INTO question_bank (id, question, owner_id, frequency, status) "
            "VALUES (2, 'Promise 的原理?', 1, 1, 'approved')"
        )

        # question_sources：题目关联到公共面试
        conn.execute(
            "INSERT INTO question_sources (question_bank_id, url, company, round) "
            "VALUES (1, 'http://interview-a.com', 'CompanyA', '1面')"
        )
        conn.execute(
            "INSERT INTO question_sources (question_bank_id, url, company, round) "
            "VALUES (1, 'http://interview-b.com', 'CompanyB', '2面')"
        )
        conn.execute(
            "INSERT INTO question_sources (question_bank_id, url, company, round) "
            "VALUES (2, 'http://interview-a.com', 'CompanyA', '1面')"
        )
        conn.commit()

    def test_personal_frequency_sql_not_zero(self, test_db):
        """personal 模式下 get_dynamic_frequency_sql 应返回正确的非零频率"""
        from app.db.queries import get_dynamic_frequency_sql

        self._seed_data(test_db)

        # get_dynamic_frequency_sql 返回一个 SQL 子查询字符串
        sql = get_dynamic_frequency_sql('personal', 1, table_alias='qb')

        # 在 test_db 上执行该 SQL 子查询
        row = test_db.execute(
            f"SELECT {sql} FROM question_bank qb WHERE qb.id = 1"
        ).fetchone()

        # 题目 1 有 2 条 question_sources，应该返回 2（修复前返回 0）
        assert row[0] == 2, f"personal mode frequency should be 2, got {row[0]}"

    def test_personal_frequency_sql_single_source(self, test_db):
        """personal 模式下题目 2 只有 1 条来源，频率应为 1"""
        from app.db.queries import get_dynamic_frequency_sql

        self._seed_data(test_db)

        sql = get_dynamic_frequency_sql('personal', 1, table_alias='qb')
        row = test_db.execute(
            f"SELECT {sql} FROM question_bank qb WHERE qb.id = 2"
        ).fetchone()

        assert row[0] == 1, f"personal mode frequency for qb=2 should be 1, got {row[0]}"

    def test_build_api_shapes_batch_filtered_personal_frequency(self, test_db):
        """build_api_shapes_batch_filtered 在 personal 模式下返回正确频率"""
        from app.db.question_bank_sources import build_api_shapes_batch_filtered

        self._seed_data(test_db)

        result = build_api_shapes_batch_filtered(test_db, [1, 2], 'personal', 1)

        # 题目 1 有 2 条不同 URL 的 sources
        assert result[1]['frequency'] == 2, (
            f"qb=1 frequency should be 2, got {result[1]['frequency']}"
        )
        assert len(result[1]['sources']) == 2

        # 题目 2 有 1 条 source
        assert result[2]['frequency'] == 1, (
            f"qb=2 frequency should be 1, got {result[2]['frequency']}"
        )
        assert len(result[2]['sources']) == 1

    def test_public_frequency_unchanged(self, test_db):
        """public 模式频率不受影响（回归测试）"""
        from app.db.queries import get_dynamic_frequency_sql

        self._seed_data(test_db)

        sql = get_dynamic_frequency_sql('public', 1, table_alias='qb')
        row = test_db.execute(
            f"SELECT {sql} FROM question_bank qb WHERE qb.id = 1"
        ).fetchone()

        # public 模式统计 owner_id IS NULL 的面试，结果应该相同
        assert row[0] == 2, f"public mode frequency should be 2, got {row[0]}"

    def test_mixed_frequency_unchanged(self, test_db):
        """mixed 模式频率不受影响（回归测试）"""
        from app.db.queries import get_dynamic_frequency_sql

        self._seed_data(test_db)

        sql = get_dynamic_frequency_sql('mixed', 1, table_alias='qb')
        row = test_db.execute(
            f"SELECT {sql} FROM question_bank qb WHERE qb.id = 1"
        ).fetchone()

        # mixed 模式统计所有（NULL 或个人），结果应该相同
        assert row[0] == 2, f"mixed mode frequency should be 2, got {row[0]}"

    def test_personal_sources_filtered_consistent(self, test_db):
        """build_api_shapes_batch_filtered 的 sources 列表和 frequency 一致"""
        from app.db.question_bank_sources import build_api_shapes_batch_filtered

        self._seed_data(test_db)

        result = build_api_shapes_batch_filtered(test_db, [1, 2], 'personal', 1)

        for qb_id in [1, 2]:
            assert result[qb_id]['frequency'] == len(result[qb_id]['sources']), (
                f"qb={qb_id}: frequency ({result[qb_id]['frequency']}) "
                f"!= len(sources) ({len(result[qb_id]['sources'])})"
            )

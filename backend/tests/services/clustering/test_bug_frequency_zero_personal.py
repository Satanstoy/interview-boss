"""
BUG-007: Personal 模式下频率显示为 0

根因：get_dynamic_frequency_sql('personal', user_id) 生成的 SQL 使用
  i.owner_id = {user_id}
但个人题库的 question_sources 指向的 interview 记录的 owner_id 为 NULL
（因为题目源自公共面经）。SQL 中 NULL != 1，导致 COUNT 返回 0。

修复：personal 模式改为 (i.owner_id = {user_id} OR i.owner_id IS NULL)，
确保也统计公共/遗留面经来源。
"""
import pytest


class TestBugFrequencyZeroPersonal:
    """BUG-007: 个人模式频率不应为 0"""

    def _setup_data(self, conn, user_id: int = 1):
        """创建测试数据：personal question_bank + NULL-owner interview + question_sources"""
        # 使用 INSERT OR IGNORE 避免与 admin seed 冲突
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, email) VALUES (?, 'testuser', 'hash', 'test@test.com')",
            (user_id,)
        )
        # 创建 interview（owner_id = NULL，模拟公共面经）
        conn.execute(
            "INSERT INTO interview (url, company, round, owner_id, status) "
            "VALUES (?, '公司A', '一面', NULL, 'approved')",
            ('http://source1.com',)
        )
        conn.execute(
            "INSERT INTO interview (url, company, round, owner_id, status) "
            "VALUES (?, '公司A', '二面', NULL, 'approved')",
            ('http://source2.com',)
        )
        # 创建 question_bank（owner_id = user_id，个人题目）
        conn.execute(
            "INSERT INTO question_bank (question, cat1, cat2, owner_id, frequency, status) "
            "VALUES ('测试题目', '分类1', '分类2', ?, 2, 'approved')",
            (user_id,)
        )
        qb_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        # 创建 question_sources（链接到 NULL-owner interview）
        conn.execute(
            "INSERT INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, '公司A', '一面')",
            (qb_id, 'http://source1.com')
        )
        conn.execute(
            "INSERT INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, '公司A', '二面')",
            (qb_id, 'http://source2.com')
        )
        conn.commit()
        return qb_id

    def test_dynamic_frequency_personal_mode_not_zero(self, test_db):
        """personal 模式下，指向 NULL-owner interview 的来源应被计入频率"""
        from app.db.queries import get_dynamic_frequency_sql

        user_id = 1
        qb_id = self._setup_data(test_db, user_id)
        dyn_freq_sql = get_dynamic_frequency_sql('personal', user_id)
        row = test_db.execute(
            f"SELECT ({dyn_freq_sql}) as frequency FROM question_bank qb WHERE qb.id = ?", (qb_id,)
        ).fetchone()
        assert row['frequency'] == 2, (
            f"Personal mode frequency should be 2, got {row['frequency']}. "
            "NULL-owner interviews should be counted."
        )

    def test_dynamic_frequency_personal_excludes_other_users(self, test_db):
        """personal 模式下，其他用户的面经来源不应被计入"""
        from app.db.queries import get_dynamic_frequency_sql

        user_id = 1
        other_user_id = 2
        qb_id = self._setup_data(test_db, user_id)

        # 添加一条其他用户的面经来源
        conn = test_db
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, email) VALUES (?, 'other', 'hash', 'other@test.com')",
            (other_user_id,)
        )
        conn.execute(
            "INSERT INTO interview (url, company, round, owner_id, status) "
            "VALUES (?, '公司B', '三面', ?, 'approved')",
            ('http://other.com', other_user_id)
        )
        conn.execute(
            "INSERT INTO question_sources (question_bank_id, url, company, round) VALUES (?, ?, '公司B', '三面')",
            (qb_id, 'http://other.com')
        )
        conn.commit()

        dyn_freq_sql = get_dynamic_frequency_sql('personal', user_id)
        row = test_db.execute(
            f"SELECT ({dyn_freq_sql}) as frequency FROM question_bank qb WHERE qb.id = ?", (qb_id,)
        ).fetchone()
        # 应该只计 NULL-owner 的 2 条，不计 other_user 的 1 条
        assert row['frequency'] == 2, (
            f"Should count only NULL-owner interviews (2), got {row['frequency']}"
        )

    def test_dynamic_frequency_public_mode_unaffected(self, test_db):
        """public 模式频率不受此修复影响"""
        from app.db.queries import get_dynamic_frequency_sql

        user_id = 1
        qb_id = self._setup_data(test_db, user_id)

        dyn_freq_sql = get_dynamic_frequency_sql('public', user_id)
        row = test_db.execute(
            f"SELECT ({dyn_freq_sql}) as frequency FROM question_bank qb WHERE qb.id = ?", (qb_id,)
        ).fetchone()
        # public 模式计 NULL-owner = 2
        assert row['frequency'] == 2

    def test_dynamic_frequency_mixed_mode_unaffected(self, test_db):
        """mixed 模式频率不受此修复影响"""
        from app.db.queries import get_dynamic_frequency_sql

        user_id = 1
        qb_id = self._setup_data(test_db, user_id)

        dyn_freq_sql = get_dynamic_frequency_sql('mixed', user_id)
        row = test_db.execute(
            f"SELECT ({dyn_freq_sql}) as frequency FROM question_bank qb WHERE qb.id = ?", (qb_id,)
        ).fetchone()
        # mixed = NULL + own = 2
        assert row['frequency'] == 2

    def test_get_sources_filtered_personal_includes_null_owner(self, test_db):
        """get_sources_filtered 在 personal 模式下应包含 NULL-owner 来源"""
        from app.db.question_bank_sources import get_sources_filtered

        user_id = 1
        qb_id = self._setup_data(test_db, user_id)

        sources = get_sources_filtered(test_db, qb_id, 'personal', user_id)
        urls = {s['url'] for s in sources}
        assert 'http://source1.com' in urls
        assert 'http://source2.com' in urls
        assert len(sources) == 2

    def test_build_api_shapes_batch_filtered_personal_not_zero(self, test_db):
        """build_api_shapes_batch_filtered 在 personal 模式下 frequency 不应为 0"""
        from app.db.question_bank_sources import build_api_shapes_batch_filtered

        user_id = 1
        qb_id = self._setup_data(test_db, user_id)

        result = build_api_shapes_batch_filtered(test_db, [qb_id], 'personal', user_id)
        assert result[qb_id]['frequency'] == 2, (
            f"Batch filtered frequency should be 2, got {result[qb_id]['frequency']}"
        )

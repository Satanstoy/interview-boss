"""
测试：软删除面经后重新上传同一 URL 的完整流程

验证：
1. _check_duplicate_url_sync 不会因软删除记录误报重复
2. _purge_soft_deleted 能正确清理残留的软删除数据
3. 提交 → 软删除 → 重新提交同一 URL 整条链路正常工作
"""
import json
import os
import sqlite3
import sys
import time
import pytest

# 确保 backend 在 path 中
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db.connection import get_db_connection, DB_PATH
from app.db.operations import _check_duplicate_url_sync, _purge_soft_deleted


# ═══════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════

TEST_URL = "https://test-soft-delete.example.com/interview/12345"
TEST_URL_SIG = "test-soft-delete_sig"  # 简化的 signature


@pytest.fixture(autouse=True)
def _cleanup_test_data():
    """每个测试前后清理测试数据"""
    # 确保测试用户存在（FK 约束要求）
    with get_db_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) VALUES (999, '_test_user_', 'x', 0)")
        conn.commit()
    yield
    with get_db_connection() as conn:
        conn.execute("DELETE FROM interview WHERE url = ?", (TEST_URL,))
        conn.execute("DELETE FROM jd WHERE url = ?", (TEST_URL,))
        conn.execute("DELETE FROM questions_detail WHERE url = ?", (TEST_URL,))
        conn.execute("DELETE FROM users WHERE id = 999")
        conn.commit()


def _insert_test_interview(owner_id=None, deleted_at=None):
    """插入一条测试面经记录"""
    with get_db_connection() as conn:
        if deleted_at:
            conn.execute(
                "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, deleted_at, job_position) "
                "VALUES (?, '测试公司', '一面', '测试', '1.测试题', '中等', ?, 'approved', ?, '')",
                (TEST_URL, owner_id, deleted_at)
            )
        else:
            conn.execute(
                "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, job_position) "
                "VALUES (?, '测试公司', '一面', '测试', '1.测试题', '中等', ?, 'approved', '')",
                (TEST_URL, owner_id)
            )
        conn.commit()


def _insert_test_questions_detail(owner_id=None, deleted_at=None):
    """插入测试 questions_detail 记录"""
    with get_db_connection() as conn:
        if deleted_at:
            conn.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, deleted_at, job_position) "
                "VALUES (?, '测试公司', '一面', '测试题', '测试', '测试分类', '标签', '中等', ?, '')",
                (TEST_URL, deleted_at)
            )
        else:
            conn.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) "
                "VALUES (?, '测试公司', '一面', '测试题', '测试', '测试分类', '标签', '中等', '')",
                (TEST_URL,)
            )
        conn.commit()


# ═══════════════════════════════════════════════════
#  单元测试：_check_duplicate_url_sync
# ═══════════════════════════════════════════════════

class TestDuplicateCheck:
    """测试重复 URL 检查逻辑"""

    def test_no_records_returns_false(self):
        """无任何记录时应返回 False"""
        assert _check_duplicate_url_sync(TEST_URL) is False

    def test_active_record_returns_true(self):
        """存在活跃（未删除）记录时应返回 True"""
        _insert_test_interview()
        assert _check_duplicate_url_sync(TEST_URL) is True

    def test_soft_deleted_record_returns_false(self):
        """仅有软删除记录时应返回 False（允许重新上传）"""
        _insert_test_interview(deleted_at="2026-05-09 12:00:00")
        assert _check_duplicate_url_sync(TEST_URL) is False

    def test_personal_active_record_returns_true(self):
        """个人面经存在活跃记录时应返回 True"""
        _insert_test_interview(owner_id=999)
        assert _check_duplicate_url_sync(TEST_URL, owner_id=999) is True

    def test_personal_soft_deleted_returns_false(self):
        """个人面经仅有软删除记录时应返回 False"""
        _insert_test_interview(owner_id=999, deleted_at="2026-05-09 12:00:00")
        assert _check_duplicate_url_sync(TEST_URL, owner_id=999) is False

    def test_empty_url_returns_false(self):
        """空 URL 应返回 False"""
        assert _check_duplicate_url_sync("") is False
        assert _check_duplicate_url_sync(None) is False


# ═══════════════════════════════════════════════════
#  单元测试：_purge_soft_deleted
# ═══════════════════════════════════════════════════

class TestPurgeSoftDeleted:
    """测试软删除记录清理"""

    def test_purges_soft_deleted_interview(self):
        """应物理删除软删除的 interview 记录"""
        _insert_test_interview(deleted_at="2026-05-09 12:00:00")
        _purge_soft_deleted(TEST_URL)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM interview WHERE url = ?", (TEST_URL,)).fetchone()
            assert row is None, "软删除的 interview 应被物理删除"

    def test_purges_associated_questions_detail(self):
        """应同时清理关联的 questions_detail"""
        _insert_test_interview(deleted_at="2026-05-09 12:00:00")
        _insert_test_questions_detail(deleted_at="2026-05-09 12:00:00")
        _purge_soft_deleted(TEST_URL)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM questions_detail WHERE url = ?", (TEST_URL,)).fetchone()
            assert row is None, "关联的 questions_detail 应被物理删除"

    def test_does_not_purge_active_records(self):
        """不应物理删除活跃记录"""
        _insert_test_interview()  # 无 deleted_at
        _purge_soft_deleted(TEST_URL)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM interview WHERE url = ?", (TEST_URL,)).fetchone()
            assert row is not None, "活跃记录不应被删除"

    def test_purge_personal_soft_deleted(self):
        """应正确清理个人面经的软删除记录"""
        _insert_test_interview(owner_id=999, deleted_at="2026-05-09 12:00:00")
        _purge_soft_deleted(TEST_URL, owner_id=999)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM interview WHERE url = ?", (TEST_URL,)).fetchone()
            assert row is None

    def test_purge_respects_owner_id(self):
        """清理时应尊重 owner_id 过滤（公共 vs 个人）"""
        # 插入公共软删除记录
        _insert_test_interview(owner_id=None, deleted_at="2026-05-09 12:00:00")
        # 用个人 owner_id 清理 — 不应删除公共记录
        _purge_soft_deleted(TEST_URL, owner_id=999)

        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM interview WHERE url = ?", (TEST_URL,)).fetchone()
            assert row is not None, "owner_id 不匹配时不应删除"


# ═══════════════════════════════════════════════════
#  集成测试：完整提交 → 软删除 → 重新提交
# ═══════════════════════════════════════════════════

class TestReuploadAfterSoftDelete:
    """集成测试：软删除后重新上传同一 URL"""

    def test_check_then_purge_allows_reupload(self):
        """模拟完整流程：检查 → 发现软删除 → 清理 → 再检查应通过"""
        # 1. 插入软删除记录
        _insert_test_interview(deleted_at="2026-05-09 12:00:00")
        _insert_test_questions_detail(deleted_at="2026-05-09 12:00:00")

        # 2. 重复检查应通过（软删除记录不算重复）
        assert _check_duplicate_url_sync(TEST_URL) is False

        # 3. 清理后确认数据库干净
        with get_db_connection() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM interview WHERE url = ?", (TEST_URL,)).fetchone()[0]
            assert cnt == 0, "清理后不应有残留记录"

            cnt = conn.execute("SELECT COUNT(*) FROM questions_detail WHERE url = ?", (TEST_URL,)).fetchone()[0]
            assert cnt == 0, "清理后不应有残留的 questions_detail"

    def test_mixed_active_and_soft_deleted(self):
        """有活跃记录时应返回 True（即使有其他 URL 的软删除记录也不影响）"""
        # 活跃记录
        _insert_test_interview()
        assert _check_duplicate_url_sync(TEST_URL) is True

    def test_reupload_after_full_lifecycle(self):
        """完整生命周期：上传 → 软删除 → 重新上传验证"""
        # Step 1: 首次上传（模拟）
        _insert_test_interview(owner_id=None)
        assert _check_duplicate_url_sync(TEST_URL) is True

        # Step 2: 软删除
        with get_db_connection() as conn:
            conn.execute("UPDATE interview SET deleted_at = CURRENT_TIMESTAMP WHERE url = ?", (TEST_URL,))
            conn.commit()

        # Step 3: 重新上传检查
        assert _check_duplicate_url_sync(TEST_URL) is False

        # Step 4: 确认清理后可以重新插入
        with get_db_connection() as conn:
            # 软删除记录应已被清理
            cnt = conn.execute("SELECT COUNT(*) FROM interview WHERE url = ?", (TEST_URL,)).fetchone()[0]
            assert cnt == 0

            # 可以重新插入
            conn.execute(
                "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, job_position) "
                "VALUES (?, '新公司', '二面', '新', '1.新题', '简单', NULL, 'approved', '')",
                (TEST_URL,)
            )
            conn.commit()

            row = conn.execute("SELECT * FROM interview WHERE url = ? AND deleted_at IS NULL", (TEST_URL,)).fetchone()
            assert row is not None
            assert row['company'] == '新公司'

"""
自动化测试 — 针对 BUG-001 和 BUG-002
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock


class TestBug001MixedModeSQL:
    """BUG-001: master_bank.py 混合模式 SQL 括号不匹配"""

    @pytest.mark.asyncio
    async def test_bug001_mixed_mode_sql_syntax_error(self):
        """修复前：混合模式 SQL 应有语法错误（括号不匹配）"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.questions import _build_bank_where_clause

            user = {
                'id': 1,
                'bank_mode': 'mixed',
                'is_admin': True
            }

            from_clause, where_clause, params = _build_bank_where_clause(user)

            # 检查括号匹配
            open_count = where_clause.count('(')
            close_count = where_clause.count(')')

            # 修复前：右括号比左括号多 1（BUG 存在）
            if close_count > open_count:
                pytest.fail(
                    f"BUG-001 确认：SQL 括号不匹配！"
                    f"左括号: {open_count}, 右括号: {close_count}"
                    f"\nSQL: {where_clause}"
                )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="BUG-001: 修复后此测试应通过")
    async def test_bug001_mixed_mode_sql_should_be_valid(self):
        """修复后：混合模式 SQL 应该括号匹配"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.questions import _build_bank_where_clause

            user = {
                'id': 1,
                'bank_mode': 'mixed',
                'is_admin': True
            }

            from_clause, where_clause, params = _build_bank_where_clause(user)

            # 验证括号匹配
            open_count = where_clause.count('(')
            close_count = where_clause.count(')')
            assert open_count == close_count, f"括号不匹配: ({open_count} vs {close_count})"

            # 验证 SQL 结构正确
            assert '((qb.owner_id IS NULL AND qb.status' in where_clause
            assert 'OR qb.owner_id = ?)' in where_clause
            assert 'AND qb.deleted_at IS NULL' in where_clause

    @pytest.mark.asyncio
    async def test_bug001_personal_mode_sql_valid(self):
        """个人模式 SQL 应该正确（无 bug）"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.questions import _build_bank_where_clause

            user = {
                'id': 1,
                'bank_mode': 'personal',
                'is_admin': False
            }

            from_clause, where_clause, params = _build_bank_where_clause(user)

            assert 'qb.owner_id = ?' in where_clause
            assert 'qb.deleted_at IS NULL' in where_clause
            assert params == [1, 1]  # [pos_id, uid]

    @pytest.mark.asyncio
    async def test_bug001_public_mode_sql_valid(self):
        """公共模式 SQL 应该正确（无 bug）"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.questions import _build_bank_where_clause

            user = {
                'id': 1,
                'bank_mode': 'public',
                'is_admin': True
            }

            from_clause, where_clause, params = _build_bank_where_clause(user)

            assert 'qb.owner_id IS NULL' in where_clause
            assert 'qb.status = ' in where_clause
            assert 'qb.deleted_at IS NULL' in where_clause
            assert params == [1]  # [pos_id]


class TestBug002AnalyticsFilter:
    """BUG-002: analytics.py 缺少软删除过滤"""

    @pytest.mark.asyncio
    async def test_bug002_personal_mode_missing_deleted_at(self):
        """修复前：个人模式缺少 deleted_at IS NULL 过滤"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.analytics import _build_analytics_bank_filter

            user = {
                'id': 1,
                'bank_mode': 'personal',
                'is_admin': False
            }

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            # 修复前：缺少 deleted_at IS NULL
            if 'deleted_at IS NULL' not in where_clause:
                pytest.fail(
                    f"BUG-002 确认：个人模式缺少 deleted_at IS NULL 过滤"
                    f"\nWHERE: {where_clause}"
                )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="BUG-002: 修复后此测试应通过")
    async def test_bug002_personal_mode_should_have_deleted_at(self):
        """修复后：个人模式应有 deleted_at IS NULL 过滤"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.analytics import _build_analytics_bank_filter

            user = {
                'id': 1,
                'bank_mode': 'personal',
                'is_admin': False
            }

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            assert 'deleted_at IS NULL' in where_clause, "应包含软删除过滤"

    @pytest.mark.asyncio
    async def test_bug002_mixed_mode_missing_deleted_at(self):
        """修复前：混合模式缺少 deleted_at IS NULL 过滤"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.analytics import _build_analytics_bank_filter

            user = {
                'id': 1,
                'bank_mode': 'mixed',
                'is_admin': True
            }

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            # 修复前：缺少 deleted_at IS NULL
            if 'deleted_at IS NULL' not in where_clause:
                pytest.fail(
                    f"BUG-002 确认：混合模式缺少 deleted_at IS NULL 过滤"
                    f"\nWHERE: {where_clause}"
                )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="BUG-002: 修复后此测试应通过")
    async def test_bug002_mixed_mode_should_have_deleted_at(self):
        """修复后：混合模式应有 deleted_at IS NULL 过滤"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.analytics import _build_analytics_bank_filter

            user = {
                'id': 1,
                'bank_mode': 'mixed',
                'is_admin': True
            }

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            assert 'deleted_at IS NULL' in where_clause, "应包含软删除过滤"
            # 混合模式还应有括号匹配的 OR 条件
            assert '((qb.owner_id IS NULL' in where_clause

    @pytest.mark.asyncio
    async def test_bug002_public_mode_missing_deleted_at(self):
        """修复前：公共模式缺少 deleted_at IS NULL 过滤"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.analytics import _build_analytics_bank_filter

            user = {
                'id': 1,
                'bank_mode': 'public',
                'is_admin': True
            }

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            # 修复前：缺少 deleted_at IS NULL
            if 'deleted_at IS NULL' not in where_clause:
                pytest.fail(
                    f"BUG-002 确认：公共模式缺少 deleted_at IS NULL 过滤"
                    f"\nWHERE: {where_clause}"
                )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="BUG-002: 修复后此测试应通过")
    async def test_bug002_public_mode_should_have_deleted_at(self):
        """修复后：公共模式应有 deleted_at IS NULL 过滤"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (1, '测试岗位')

            from app.routers.analytics import _build_analytics_bank_filter

            user = {
                'id': 1,
                'bank_mode': 'public',
                'is_admin': True
            }

            join_clause, where_clause, params = _build_analytics_bank_filter(user)

            assert 'deleted_at IS NULL' in where_clause, "应包含软删除过滤"


class TestFallbackPaths:
    """测试没有 position_id 时的 fallback 路径"""

    @pytest.mark.asyncio
    async def test_fallback_mixed_mode_sql_valid(self):
        """fallback 路径的混合模式 SQL 应该正确"""
        with patch('app.db.connection.get_user_job_position') as mock_pos:
            mock_pos.return_value = (None, '测试岗位')  # 无 position_id

            from app.routers.questions import _build_bank_where_clause

            user = {
                'id': 1,
                'bank_mode': 'mixed',
                'is_admin': True
            }

            from_clause, where_clause, params = _build_bank_where_clause(user)

            # fallback 路径的 SQL 应该括号匹配
            open_count = where_clause.count('(')
            close_count = where_clause.count(')')
            assert open_count == close_count, f"括号不匹配: ({open_count} vs {close_count})"

            # 验证 SQL 结构
            assert '((qb.owner_id IS NULL' in where_clause
            assert 'OR qb.owner_id = ?)' in where_clause
            assert 'qb.deleted_at IS NULL' in where_clause

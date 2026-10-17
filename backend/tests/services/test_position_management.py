"""
自动化测试 — 针对 BUG-001 和 BUG-002: 岗位管理问题
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, call


class TestPositionManagement:
    """岗位管理测试套件"""

    @pytest.mark.asyncio
    async def test_switch_position_creates_new_position_with_correct_conflict(self):
        """新增岗位应通过独立 create_position 端点写入岗位表。"""
        # Arrange
        from app.routers.profile_pkg.position import create_position

        mock_admin = {"id": 1, "is_admin": True}
        req = {"name": "测试新岗位", "description": ""}

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 模拟岗位不存在的情况
        def mock_execute(sql, *args):
            result = MagicMock()
            if 'SELECT id FROM job_positions' in sql:
                result.fetchone.return_value = None
            elif 'INSERT INTO job_positions' in sql:
                result.lastrowid = 123
            elif 'last_insert_rowid' in sql:
                result.fetchone.return_value = (123,)
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.routers.profile_pkg.position.get_db_connection', return_value=mock_conn):
            with patch('app.routers.profile_pkg.position.run_db', side_effect=lambda f: f()):
                result = await create_position(req, admin=mock_admin)

        assert result == {"status": "success", "id": 123, "name": "测试新岗位"}

    @pytest.mark.asyncio
    async def test_delete_position_endpoint_exists(self):
        """删除岗位端点应存在"""
        # Arrange
        from app.routers.profile_pkg.position import delete_position

        # Assert
        assert delete_position is not None

    @pytest.mark.asyncio
    async def test_get_available_positions_excludes_deleted(self):
        """获取可用岗位列表应排除已删除的岗位"""
        # Arrange
        from app.routers.profile import _get_available_positions

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 模拟返回值 - 使用 MagicMock 模拟行访问
        mock_row1 = MagicMock()
        mock_row1.__getitem__ = MagicMock(side_effect=lambda x: '岗位A' if x == 'position_name' else None)
        mock_row2 = MagicMock()
        mock_row2.__getitem__ = MagicMock(side_effect=lambda x: '岗位B' if x == 'name' else None)

        def mock_execute(sql, *args):
            result = MagicMock()
            if "PRAGMA table_info('job_positions')" in sql:
                result.fetchall.return_value = [(0, "id"), (1, "name"), (2, "is_deleted")]
            elif 'FROM job_positions' in sql:
                result.fetchall.return_value = [mock_row2]
            elif 'FROM taxonomy' in sql:
                result.fetchall.return_value = [{"position_name": "岗位B"}]
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.routers.profile.get_db_connection', return_value=mock_conn):
            # Act
            result = _get_available_positions()

        assert result == ["岗位B"]

    @pytest.mark.asyncio
    async def test_list_positions_excludes_soft_deleted_rows(self):
        """GET /api/positions 应排除软删除岗位，避免前端刷新后旧岗位回流"""
        from app.routers.profile_pkg.position import list_positions

        mock_user = {"id": 1}
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        def mock_execute(sql, *args):
            result = MagicMock()
            if "PRAGMA table_info" in sql:
                result.fetchall.return_value = [(0, "id"), (1, "name"), (2, "description"), (3, "is_deleted")]
            elif "SELECT id, name, description FROM job_positions" in sql:
                assert "is_deleted" in sql
                result.fetchall.return_value = [{"id": 1, "name": "前端开发工程师", "description": ""}]
            elif "sqlite_master" in sql:
                result.fetchone.return_value = (1,)
            elif "SELECT position_name FROM taxonomy" in sql:
                result.fetchall.return_value = [{"position_name": "前端开发工程师"}]
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.routers.profile_pkg.position.get_db_connection', return_value=mock_conn):
            with patch('app.routers.profile_pkg.position.run_db', side_effect=lambda f: f()):
                result = await list_positions(user=mock_user)

        assert result == {"positions": [{"id": 1, "name": "前端开发工程师", "description": ""}]}

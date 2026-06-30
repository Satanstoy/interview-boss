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
        """新增岗位应正确处理复合唯一索引的 ON CONFLICT"""
        # Arrange
        from app.routers.profile_pkg.position import switch_position

        mock_admin = {"id": 1, "is_admin": True}
        req = {"position": "测试新岗位"}

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 模拟岗位不存在的情况
        def mock_execute(sql, *args):
            result = MagicMock()
            if 'SELECT id, name FROM job_positions' in sql:
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
                # Act
                result = await switch_position(req, admin=mock_admin)

                # Assert - 验证 SQL 包含正确的 ON CONFLICT
                call_args_list = mock_conn.execute.call_args_list
                taxonomy_insert_found = False
                for call_item in call_args_list:
                    if call_item[0] and isinstance(call_item[0][0], str) and 'INSERT INTO taxonomy' in call_item[0][0]:
                        sql = call_item[0][0]
                        assert "ON CONFLICT(position_name, source, owner_id)" in sql
                        assert "source" in sql
                        assert "owner_id" in sql
                        taxonomy_insert_found = True
                        break
                assert taxonomy_insert_found, "未找到 taxonomy INSERT 语句"

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

        # 设置 execute 返回值
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row1]
        mock_conn.execute.return_value = mock_result

        # 需要两次不同的返回值
        call_count = [0]
        def mock_execute(sql, *args):
            call_count[0] += 1
            result = MagicMock()
            if 'taxonomy' in sql:
                result.fetchall.return_value = [mock_row1]
            elif 'job_positions' in sql:
                result.fetchall.return_value = [mock_row2]
                # 验证 SQL 排除了已删除的岗位
                assert "is_deleted" in sql
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.routers.profile.get_db_connection', return_value=mock_conn):
            # Act
            result = _get_available_positions()

            # Assert
            assert isinstance(result, list)

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
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.routers.profile_pkg.position.get_db_connection', return_value=mock_conn):
            with patch('app.routers.profile_pkg.position.run_db', side_effect=lambda f: f()):
                result = await list_positions(user=mock_user)

        assert result == {"positions": [{"id": 1, "name": "前端开发工程师", "description": ""}]}

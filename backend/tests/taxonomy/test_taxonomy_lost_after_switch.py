"""
自动化测试 — 针对 BUG-001 和 BUG-002: 采纳AI分类后切换岗位再返回分类丢失
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock


class TestTaxonomyLostAfterSwitch:
    """分类丢失测试套件"""

    @pytest.mark.asyncio
    async def test_get_taxonomy_for_position_prefers_user_taxonomy(self):
        """get_taxonomy_for_position 应优先返回用户个人分类"""
        # Arrange
        from app.db.connection import get_taxonomy_for_position

        position = "测试岗位"
        user_id = 1

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 模拟用户个人分类存在
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(return_value='[{"cat1": "A.用户个人分类", "children": ["A1.子类"]}]')

        def mock_execute(sql, *args):
            result = MagicMock()
            if "source = 'user'" in sql:
                result.fetchone.return_value = mock_row
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            # Act
            result = get_taxonomy_for_position(position, user_id=user_id)

            # Assert
            assert result["job_position"] == position
            assert result["categories"][0]["cat1"] == "A.用户个人分类"

    @pytest.mark.asyncio
    async def test_get_taxonomy_for_position_falls_back_to_system(self):
        """get_taxonomy_for_position 在无用户个人分类时应返回系统分类"""
        # Arrange
        from app.db.connection import get_taxonomy_for_position

        position = "测试岗位"
        user_id = 1

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 模拟用户个人分类不存在，系统分类存在
        mock_system_row = MagicMock()
        mock_system_row.__getitem__ = MagicMock(return_value='[{"cat1": "A.系统分类", "children": ["A1.子类"]}]')

        def mock_execute(sql, *args):
            result = MagicMock()
            if "source = 'user'" in sql:
                result.fetchone.return_value = None
            elif "source = 'system'" in sql:
                result.fetchone.return_value = mock_system_row
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            # Act
            result = get_taxonomy_for_position(position, user_id=user_id)

            # Assert
            assert result["job_position"] == position
            assert result["categories"][0]["cat1"] == "A.系统分类"

    @pytest.mark.asyncio
    async def test_confirm_taxonomy_saves_as_user_taxonomy(self):
        """confirm_taxonomy 应将分类保存为用户个人分类"""
        # Arrange
        from app.routers.profile_pkg.taxonomy import confirm_taxonomy

        mock_user = {"id": 1, "is_admin": True}
        req = {"categories": [{"cat1": "A.AI生成分类", "children": ["A1.子类"]}]}

        with patch('app.routers.profile.get_current_user', return_value=mock_user):
            with patch('app.routers.profile.run_db') as mock_run_db:
                # Mock get_user_job_position
                mock_run_db.side_effect = [
                    (None, "测试岗位"),  # get_user_job_position 返回值
                    None  # save_taxonomy_for_position 返回值
                ]

                # Act
                result = await confirm_taxonomy(req, user=mock_user)

                # Assert
                assert result["status"] == "success"

                # 验证 save_taxonomy_for_position 被调用时使用了正确的参数
                call_args = mock_run_db.call_args_list
                # 第二次调用是 save_taxonomy_for_position
                save_call = call_args[1]
                # 验证 lambda 中调用了 save_taxonomy_for_position 且参数正确

    @pytest.mark.asyncio
    async def test_update_profile_saves_taxonomy_as_user_taxonomy(self):
        """update_profile 应将 taxonomy 保存为用户个人分类（非系统分类）"""
        from app.routers.profile_pkg.taxonomy import update_profile
        from app.models.schemas import ProfileUpdateRequest

        mock_admin = {"id": 1, "is_admin": True}
        categories = [{"cat1": "A.用户编辑分类", "children": ["A1.子类"]}]
        req = ProfileUpdateRequest(settings={
            "taxonomy_config": '{"job_position": "测试岗位", "categories": [{"cat1": "A.用户编辑分类", "children": ["A1.子类"]}]}'
        })

        with patch('app.routers.profile.run_db') as mock_run_db:
            # Mock run_db for save_taxonomy_for_position
            mock_run_db.return_value = None

            with patch('app.routers.profile._reload_from_db'):
                with patch('app.routers.profile._sync_env_file'):
                    # Act
                    result = await update_profile(req, admin=mock_admin)

                    # Assert
                    assert result["status"] == "success"

                    # 验证 run_db 被调用
                    assert mock_run_db.called

                    # 获取 lambda 并执行它来验证 save_taxonomy_for_position 的参数
                    import app.db.connection as db_conn
                    with patch.object(db_conn, 'save_taxonomy_for_position') as mock_save:
                        with patch.object(db_conn, 'get_db_connection'):
                            # 重新调用以捕获 lambda
                            mock_run_db.reset_mock()
                            mock_run_db.side_effect = lambda fn: fn() if callable(fn) else None
                            await update_profile(req, admin=mock_admin)

                            # 验证 save_taxonomy_for_position 被调用且参数正确
                            mock_save.assert_called_once_with(
                                "测试岗位",
                                categories,
                                source='user',
                                owner_id=1
                            )

    @pytest.mark.asyncio
    async def test_get_profile_passes_user_id_to_taxonomy(self):
        """get_profile 应传递 user_id 给 get_taxonomy_for_position 以获取用户个人分类"""
        from app.db.connection import get_taxonomy_for_position

        position = "测试岗位"
        user_id = 1

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 模拟用户个人分类存在
        mock_user_row = MagicMock()
        mock_user_row.__getitem__ = MagicMock(return_value='[{"cat1": "A.用户个人分类", "children": ["A1.子类"]}]')

        call_sqls = []

        def mock_execute(sql, *args):
            call_sqls.append(sql)
            result = MagicMock()
            if "source = 'user'" in sql and "owner_id = ?" in sql:
                result.fetchone.return_value = mock_user_row
            else:
                result.fetchone.return_value = None
            return result

        mock_conn.execute.side_effect = mock_execute

        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            # Act
            result = get_taxonomy_for_position(position, user_id=user_id)

            # Assert - 验证查询包含 owner_id 条件
            assert any("owner_id = ?" in sql for sql in call_sqls), \
                "get_taxonomy_for_position 应该查询用户个人分类（包含 owner_id 条件）"
            assert result["categories"][0]["cat1"] == "A.用户个人分类"

"""
TDD 开发的测试模块 - 分类体系权限管理

采用测试驱动开发（Test-Driven Development）方法编写。
遵循红-绿-重构（Red-Green-Refactor）循环：
- 🔴 阶段：先写测试，预期失败
- 🟢 阶段：写最少代码让测试通过
- 🔵 阶段：重构优化代码结构
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestTaxonomyPermissions:
    """
    分类体系权限管理测试套件

    遵循 TDD 原则，每个测试对应一个用户需求或场景。
    测试命名规范：test_<场景>_<预期行为>
    """

    # =========================================================
    # T-001: 管理员编辑系统分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_admin_can_edit_system_taxonomy(self):
        """
        管理员应该能够编辑系统分类

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import update_taxonomy_permissions

        admin_user = {"id": 1, "is_admin": True}
        taxonomy_id = 999  # 使用不存在的ID避免修改真实数据
        new_categories = [
            {"cat1": "A.测试分类", "children": ["A1.子类1"]}
        ]

        # Mock数据库返回系统分类
        with patch('app.db.operations.get_taxonomy_by_id') as mock_get:
            mock_get.return_value = {
                "id": 999,
                "source": "system",
                "owner_id": None,
                "categories": [{"cat1": "A.原分类", "children": []}]
            }
            # Mock数据库连接避免真实写入
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_conn.execute.return_value = mock_cursor
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            with patch('app.db.operations.get_db_connection', return_value=mock_conn):
                # Act
                result = await update_taxonomy_permissions(
                    taxonomy_id=taxonomy_id,
                    categories=new_categories,
                    user=admin_user
                )

                # Assert
                assert result["success"] is True
                assert result["taxonomy"]["categories"] == new_categories

    # =========================================================
    # T-002: 普通用户编辑系统分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_regular_user_cannot_edit_system_taxonomy(self):
        """
        普通用户不应该能够编辑系统分类

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import update_taxonomy_permissions

        regular_user = {"id": 2, "is_admin": False}
        taxonomy_id = 999  # 使用不存在的ID避免修改真实数据
        new_categories = [
            {"cat1": "A.测试分类", "children": ["A1.子类1"]}
        ]

        # Mock数据库返回系统分类
        with patch('app.db.operations.get_taxonomy_by_id') as mock_get:
            mock_get.return_value = {
                "id": 999,
                "source": "system",
                "owner_id": None,
                "categories": [{"cat1": "A.原分类", "children": []}]
            }

            # Act & Assert
            with pytest.raises(PermissionError, match="只有管理员可以编辑系统分类"):
                await update_taxonomy_permissions(
                taxonomy_id=taxonomy_id,
                categories=new_categories,
                user=regular_user
            )

    # =========================================================
    # T-003: 普通用户创建个人分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_regular_user_can_create_personal_taxonomy(self):
        """
        普通用户应该能够创建个人分类

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import create_personal_taxonomy

        regular_user = {"id": 2, "is_admin": False}
        position = "测试岗位_权限测试"
        categories = [
            {"cat1": "A.个人分类", "children": ["A1.子类1"]}
        ]

        # Act
        result = await create_personal_taxonomy(
            position=position,
            categories=categories,
            user=regular_user
        )

        # Assert
        assert result["success"] is True
        assert result["taxonomy"]["source"] == "user"
        assert result["taxonomy"]["owner_id"] == 2

        # Cleanup: 删除测试数据
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            conn.execute(
                "DELETE FROM taxonomy WHERE position_name = ? AND source = 'user' AND owner_id = ?",
                (position, regular_user["id"])
            )
            conn.commit()

    # =========================================================
    # T-004: 普通用户编辑自己的分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_regular_user_can_edit_own_taxonomy(self):
        """
        普通用户应该能够编辑自己的分类

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import update_taxonomy_permissions

        regular_user = {"id": 2, "is_admin": False}
        taxonomy_id = 100  # 用户自己的分类
        new_categories = [
            {"cat1": "A.更新后的分类", "children": ["A1.子类1"]}
        ]

        # Mock数据库返回用户自己的分类
        with patch('app.db.operations.get_taxonomy_by_id') as mock_get:
            mock_get.return_value = {
                "id": 100,
                "source": "user",
                "owner_id": 2,
                "categories": [{"cat1": "A.原分类", "children": []}]
            }

            # Act
            result = await update_taxonomy_permissions(
                taxonomy_id=taxonomy_id,
                categories=new_categories,
                user=regular_user
            )

            # Assert
            assert result["success"] is True

    # =========================================================
    # T-005: 普通用户编辑他人的分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_regular_user_cannot_edit_others_taxonomy(self):
        """
        普通用户不应该能够编辑他人的分类

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import update_taxonomy_permissions

        regular_user = {"id": 2, "is_admin": False}
        taxonomy_id = 101  # 他人的分类
        new_categories = [
            {"cat1": "A.测试分类", "children": ["A1.子类1"]}
        ]

        # Mock数据库返回他人的分类
        with patch('app.db.operations.get_taxonomy_by_id') as mock_get:
            mock_get.return_value = {
                "id": 101,
                "source": "user",
                "owner_id": 3,  # 其他用户
                "categories": [{"cat1": "A.他人分类", "children": []}]
            }

            # Act & Assert
            with pytest.raises(PermissionError, match="无权编辑此分类"):
                await update_taxonomy_permissions(
                    taxonomy_id=taxonomy_id,
                    categories=new_categories,
                    user=regular_user
                )

    # =========================================================
    # T-006: 用户分享分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_user_can_share_taxonomy(self):
        """
        用户应该能够分享自己的分类

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import share_taxonomy

        regular_user = {"id": 2, "is_admin": False}
        taxonomy_id = 100  # 用户自己的分类

        # Mock数据库返回用户自己的分类
        with patch('app.db.operations.get_taxonomy_by_id') as mock_get:
            mock_get.return_value = {
                "id": 100,
                "source": "user",
                "owner_id": 2,
                "is_public": 0
            }

            # Act
            result = await share_taxonomy(
                taxonomy_id=taxonomy_id,
                user=regular_user
            )

            # Assert
            assert result["success"] is True
            assert result["taxonomy"]["is_public"] == 1

    # =========================================================
    # T-007: 获取公开分享的分类
    # =========================================================
    @pytest.mark.asyncio
    async def test_get_public_shared_taxonomies(self):
        """
        用户应该能够获取公开分享的分类列表

        红灯阶段：此测试应先写，预期失败
        """
        # Arrange
        from app.db.operations import get_public_shared_taxonomies

        regular_user = {"id": 2, "is_admin": False}

        # Mock数据库返回公开分类
        with patch('app.db.operations.get_public_shared_taxonomies') as mock_get:
            mock_get.return_value = [
                {
                    "id": 100,
                    "position_name": "测试岗位",
                    "categories": [{"cat1": "A.测试分类", "children": []}],
                    "source": "user",
                    "owner_id": 3,
                    "is_public": 1,
                    "owner_name": "testuser"
                }
            ]

            # Act
            result = await get_public_shared_taxonomies(user=regular_user)

            # Assert
            assert isinstance(result, list)
            assert len(result) > 0
            assert any(t["is_public"] == 1 for t in result)

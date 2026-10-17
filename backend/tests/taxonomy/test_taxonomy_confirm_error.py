"""
自动化测试 — 针对 BUG-001: 采纳AI分类时服务器内部错误
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock


class TestBugTaxonomyConfirm:
    """BUG-001: UPSERT 语句与唯一索引不匹配"""

    @pytest.mark.asyncio
    async def test_save_taxonomy_for_position_rejects_user_owned_taxonomy(self):
        """旧 helper 不得绕过系统统一维护的 taxonomy 写入策略。"""
        # Arrange
        from app.db.connection import save_taxonomy_for_position

        position = "测试岗位"
        categories = [{"cat1": "A.测试", "children": ["A1.子类"]}]

        with pytest.raises(ValueError, match="系统维护"):
            save_taxonomy_for_position(position, categories, source='user', owner_id=1)

    @pytest.mark.asyncio
    async def test_save_taxonomy_for_position_null_owner_id(self):
        """save_taxonomy_for_position 应正确处理 owner_id 为 NULL 的情况（使用 UPDATE-then-INSERT）"""
        # Arrange
        from app.db.connection import save_taxonomy_for_position

        position = "测试岗位"
        categories = [{"cat1": "A.测试", "children": ["A1.子类"]}]

        # Mock 数据库连接
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value.rowcount = 0  # 模拟 UPDATE 未命中

        with patch('app.db.connection.get_db_connection', return_value=mock_conn):
            # Act - 使用 owner_id 为 NULL
            save_taxonomy_for_position(position, categories, source='system', owner_id=None)

            # Assert - 验证调用了两次 execute（UPDATE + INSERT）
            assert mock_conn.execute.call_count == 2
            # 第一次是 UPDATE
            first_sql = mock_conn.execute.call_args_list[0][0][0]
            assert "UPDATE taxonomy SET" in first_sql
            # 第二次是 INSERT
            second_sql = mock_conn.execute.call_args_list[1][0][0]
            assert "INSERT INTO taxonomy" in second_sql

    @pytest.mark.asyncio
    async def test_confirm_taxonomy_endpoint_works(self):
        """已停用的个人 taxonomy endpoint 应返回明确的 410。"""
        # Arrange
        from app.routers.profile_pkg.taxonomy import confirm_taxonomy
        from fastapi import HTTPException

        mock_user = {"id": 1, "is_admin": True}
        req = {"categories": [{"cat1": "A.测试", "children": ["A1.子类"]}]}

        with pytest.raises(HTTPException) as exc_info:
            await confirm_taxonomy(req, user=mock_user)
        assert exc_info.value.status_code == 410

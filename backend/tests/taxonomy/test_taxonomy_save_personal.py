"""
自动化测试 — 针对 save_personal_taxonomy 缺少 import 导致 NameError
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestSavePersonalTaxonomy:
    """save_personal_taxonomy 端点测试"""

    @pytest.mark.asyncio
    async def test_save_personal_taxonomy_has_correct_imports(self):
        """save_personal_taxonomy 应能正确调用 get_user_job_position（不抛出 NameError）"""
        from app.routers.profile_pkg.taxonomy import save_personal_taxonomy

        mock_user = {"id": 1, "is_admin": True}
        req = {"categories": [{"cat1": "A.个人分类", "children": ["A1.子类"]}]}

        with patch('app.routers.profile.run_db') as mock_run_db:
            # Mock get_user_job_position 返回值
            mock_run_db.return_value = (None, "测试岗位")

            with patch('app.db.operations.create_personal_taxonomy', new_callable=AsyncMock) as mock_create:
                # Mock create_personal_taxonomy 返回值
                mock_create.return_value = {
                    "success": True,
                    "taxonomy": {"id": 1, "position_name": "测试岗位"}
                }

                # Act - 不应抛出 NameError
                result = await save_personal_taxonomy(req, user=mock_user)

                # Assert
                assert result["success"] is True

    @pytest.mark.asyncio
    async def test_save_personal_taxonomy_rejects_empty_categories(self):
        """save_personal_taxonomy 应拒绝空的 categories"""
        from app.routers.profile_pkg.taxonomy import save_personal_taxonomy

        mock_user = {"id": 1, "is_admin": True}
        req = {"categories": []}

        # Act & Assert
        with pytest.raises(Exception) as exc_info:
            await save_personal_taxonomy(req, user=mock_user)
        assert "需要提供 categories 列表" in str(exc_info.value.detail)

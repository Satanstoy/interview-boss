"""
自动化测试 — 针对 BUG-001: build-personal 路由变量名错误
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestBuildPersonalVariableFix:
    """BUG-001: build-personal 路由引用未定义的 admin 变量"""

    @pytest.mark.asyncio
    async def test_build_personal_uses_user_id_not_admin(self):
        """验证 build_personal_bank 函数使用 user['id'] 而非 admin['id']"""
        import inspect
        from app.routers.bank_build import build_personal_bank

        # 读取源代码，检查函数体中不存在 admin['id'] 引用
        source = inspect.getsource(build_personal_bank)
        # 修复后不应包含 admin['id']
        assert "admin['id']" not in source, \
            "BUG-001: build_personal_bank 仍然引用 admin['id']，应为 user['id']"
        # 允许单引号或双引号，但必须从当前用户对象读取 ID。
        assert "user['id']" in source or 'user["id"]' in source, \
            "BUG-001: build_personal_bank 应引用当前用户的 id"

    @pytest.mark.asyncio
    async def test_build_personal_endpoint_accepts_regular_user(self):
        """验证 build-personal 端点接受普通用户（get_current_user）"""
        from app.routers.bank_build import build_personal_bank
        import inspect

        sig = inspect.signature(build_personal_bank)
        # 检查参数使用 get_current_user 而非 get_admin_user
        source = inspect.getsource(build_personal_bank)
        assert "get_current_user" in source, \
            "build-personal 应使用 get_current_user 依赖"
        assert "get_admin_user" not in source, \
            "build-personal 不应使用 get_admin_user 依赖"


class TestAdminEndpointsStillProtected:
    """验证管理员专用端点仍然正确保护"""

    def test_build_requires_admin(self):
        """POST /api/master-bank/build 应要求管理员权限"""
        from app.routers.bank_build import build_master_bank
        import inspect
        source = inspect.getsource(build_master_bank)
        assert "get_admin_user" in source, \
            "build 端点应使用 get_admin_user"

    def test_split_requires_admin(self):
        """POST /api/master-bank/split-question 应要求管理员权限"""
        from app.routers.questions_pkg.mutations import split_question
        import inspect
        source = inspect.getsource(split_question)
        assert "get_admin_user" in source, \
            "split-question 端点应使用 get_admin_user"

    def test_merge_requires_admin(self):
        """POST /api/master-bank/merge-question 应要求管理员权限"""
        from app.routers.questions_pkg.mutations import merge_question
        import inspect
        source = inspect.getsource(merge_question)
        assert "get_admin_user" in source, \
            "merge-question 端点应使用 get_admin_user"

    def test_retag_requires_admin(self):
        """POST /api/master-bank/re-tag 应要求管理员权限"""
        from app.routers.questions_pkg.mutations import retag_master_question
        import inspect
        source = inspect.getsource(retag_master_question)
        assert "get_admin_user" in source, \
            "re-tag 端点应使用 get_admin_user"

    def test_clear_db_requires_admin(self):
        """POST /api/clear-db 应要求管理员权限"""
        from app.routers.analytics import clear_db
        import inspect
        source = inspect.getsource(clear_db)
        assert "get_admin_user" in source, \
            "clear-db 端点应使用 get_admin_user"

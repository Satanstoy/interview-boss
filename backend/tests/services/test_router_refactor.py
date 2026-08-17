"""
路由拆分重构测试 — 验证拆分后所有端点仍然存在

这些测试在重构前应该 PASS（验证当前状态），
重构后也必须 PASS（验证无回归）。
"""
import pytest


# ═══════════════════════════════════════════════════
#  profile.py 端点完整性
# ═══════════════════════════════════════════════════

class TestProfileEndpoints:
    """profile 路由的所有端点必须可访问"""

    PROFILE_ENDPOINTS = [
        ("GET",  "/api/profile/public"),
        ("GET",  "/api/profile/llm"),
        ("POST", "/api/profile/llm/validate"),
        ("PUT",  "/api/profile/llm"),
        ("DELETE", "/api/profile/llm"),
        ("GET",  "/api/profile/search"),
        ("PUT",  "/api/profile/search"),
        ("DELETE", "/api/profile/search"),
        ("POST", "/api/profile/search/test"),
        ("GET",  "/api/profile"),
        ("PUT",  "/api/profile"),
        ("GET",  "/api/profile/taxonomy"),
        ("POST", "/api/profile/taxonomy/generate"),
        ("POST", "/api/profile/taxonomy/confirm"),
        ("POST", "/api/profile/taxonomy/save-personal"),
        ("POST", "/api/profile/taxonomy/1/share"),
        ("GET",  "/api/profile/taxonomy/public"),
        ("DELETE", "/api/profile/taxonomy/1/public"),
        ("PUT",  "/api/profile/my-position"),
        ("PUT",  "/api/profile/position"),
        ("GET",  "/api/positions"),
        ("POST", "/api/positions"),
        ("DELETE", "/api/profile/position/test"),
        ("POST", "/api/profile/bind-email"),
        ("GET",  "/api/profile/email"),
        ("POST", "/api/profile/send-bind-code"),
        ("POST", "/api/profile/resume"),
        ("GET",  "/api/profile/resume"),
        ("DELETE", "/api/profile/resume"),
    ]

    @pytest.mark.parametrize("method,path", PROFILE_ENDPOINTS)
    def test_profile_endpoint_exists(self, client, method, path):
        """端点应返回 401/403/422（存在但未授权），而非 404（不存在）"""
        resp = getattr(client, method.lower())(path)
        assert resp.status_code != 404, (
            f"{method} {path} 返回 404，端点可能丢失"
        )


# ═══════════════════════════════════════════════════
#  questions.py 端点完整性
# ═══════════════════════════════════════════════════

class TestQuestionsEndpoints:
    """questions 路由的所有端点必须可访问"""

    QUESTIONS_ENDPOINTS = [
        ("GET",  "/api/master-bank"),
        ("GET",  "/api/master-bank/1"),
        ("GET",  "/api/master-bank/search"),
        ("PUT",  "/api/master-bank/1"),
        ("POST", "/api/master-bank/1/split"),
        ("DELETE", "/api/master-bank/1/original"),
        ("POST", "/api/master-bank/1/merge"),
        ("DELETE", "/api/master-bank/1"),
        ("POST", "/api/master-bank/batch-delete"),
        ("POST", "/api/master-bank/1/retag"),
        ("POST", "/api/master-bank/upload"),
    ]

    @pytest.mark.parametrize("method,path", QUESTIONS_ENDPOINTS)
    def test_questions_endpoint_exists(self, client, method, path):
        """端点应返回 401/403/422（存在但未授权），而非 404（不存在）"""
        resp = getattr(client, method.lower())(path)
        assert resp.status_code != 404, (
            f"{method} {path} 返回 404，端点可能丢失"
        )


# ═══════════════════════════════════════════════════
#  内部导入兼容性
# ═══════════════════════════════════════════════════

class TestInternalImports:
    """内部模块导入必须兼容"""

    def test_build_bank_where_clause_importable(self):
        """practice.py 依赖的 _build_bank_where_clause 必须可从原路径导入"""
        from app.routers.questions import _build_bank_where_clause
        assert callable(_build_bank_where_clause)

    def test_tag_questions_batch_importable(self):
        """submit agent 依赖的 tag_questions_batch 必须可导入"""
        from app.routers.submit import tag_questions_batch
        assert callable(tag_questions_batch)

    def test_profile_router_importable(self):
        """asgi.py 依赖的 profile.router 必须可导入"""
        from app.routers.profile import router
        assert router is not None

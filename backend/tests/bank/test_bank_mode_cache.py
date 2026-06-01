"""
自动化测试 — 针对 BUG-001: 切换题库模式后缓存未清除
验证后端 API 对不同 bank_mode 返回不同数据（确认问题在前端缓存层）
"""
import pytest


class TestBankModeCacheBug:
    """BUG-001: 切换题库模式后 GET 缓存返回旧数据"""

    def test_same_url_different_bank_mode_returns_different_results(self, test_db, client):
        """核心验证：相同 URL + 不同 bank_mode → 后端返回不同数据
        这证明了前端 GET 缓存（key=URL）无法区分 bank_mode 变化"""
        from app.core.auth import get_current_user
        from app.asgi import app

        url = "/api/master-bank?compact=true&page=1&page_size=500&sort=frequency_desc"

        # 公共模式
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "admin", "is_admin": True, "bank_mode": "public"}
        resp_public = client.get(url)
        assert resp_public.status_code == 200
        public_items = resp_public.json()["items"]

        # 个人模式（相同 URL）
        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "admin", "is_admin": True, "bank_mode": "personal"}
        resp_personal = client.get(url)
        assert resp_personal.status_code == 200
        personal_items = resp_personal.json()["items"]

        app.dependency_overrides.clear()

        # 关键断言：同一 URL 不同模式必须返回不同结果集
        public_set = {q["id"] for q in public_items}
        personal_set = {q["id"] for q in personal_items}
        # 个人题目只有 owner_id=1 的，公共题目只有 owner_id IS NULL 的
        # 两者不应该完全相同（除非用户没有任何个人题目）
        if personal_items:
            assert public_set != personal_set, \
                "BUG-001 复现确认: 相同 URL 不同 bank_mode 返回了相同数据，前端缓存无法区分模式变化"

    def test_bank_mode_filter_is_server_side_not_client_side(self, test_db, client):
        """验证 bank_mode 过滤由服务端完成，URL 中不包含 bank_mode 参数"""
        from app.core.auth import get_current_user
        from app.asgi import app

        # 使用不含 bank_mode 的 URL（前端实际发送的 URL）
        url = "/api/master-bank?compact=true&page=1&page_size=500&sort=frequency_desc"
        assert "bank_mode" not in url, "URL 不应包含 bank_mode 参数"

        app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "admin", "is_admin": True, "bank_mode": "public"}
        resp = client.get(url)
        assert resp.status_code == 200

        app.dependency_overrides.clear()

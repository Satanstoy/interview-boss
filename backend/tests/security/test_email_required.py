"""
测试：注册强制绑定邮箱 + 登录检测邮箱绑定

TDD 测试文件 — 覆盖：
- T-001~004: 注册必须提供合法且唯一的邮箱
- T-005~006: 登录时检测用户是否绑定邮箱
- T-007~010: 临时 token 绑定邮箱流程
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException


def _mock_request():
    """创建 mock request 对象（满足 slowapi rate limiter）"""
    from starlette.requests import Request as StarletteRequest
    req = MagicMock(spec=StarletteRequest)
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"user-agent": "test"}
    return req


# =========================================================
# T-001: 注册无邮箱被拒绝
# =========================================================
class TestRegisterRequiresEmail:
    """注册必须提供邮箱"""

    async def test_register_without_email_returns_400(self):
        """无邮箱的注册请求应被 Pydantic 拒绝（email 是必填字段）"""
        from app.routers.auth import RegisterRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(username="testuser", password="Pass1234")
        assert "email" in str(exc_info.value).lower()

    # =========================================================
    # T-002: 注册邮箱格式错误
    # =========================================================
    async def test_register_with_invalid_email_returns_validation_error(self):
        """邮箱格式错误应被 Pydantic 拒绝"""
        from app.routers.auth import RegisterRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError) as exc_info:
            RegisterRequest(username="testuser", password="Pass1234", email="not-an-email")
        assert "邮箱" in str(exc_info.value)

    # =========================================================
    # T-003: 注册邮箱已被占用
    # =========================================================
    async def test_register_with_taken_email_returns_409(self):
        """邮箱已被其他用户占用应返回 409"""
        from app.routers.auth import register, RegisterRequest
        req = RegisterRequest(username="newuser", password="Pass1234", email="taken@example.com")
        resp = MagicMock()
        # run_db 内部的 _create 检测到邮箱已占用，抛出 HTTPException(409)
        async def _mock_run_db(func):
            raise HTTPException(status_code=409, detail="该邮箱已被注册")
        with patch('app.routers.auth.run_db', side_effect=_mock_run_db):
            with pytest.raises(HTTPException) as exc_info:
                await register(_mock_request(), req, resp)
            assert exc_info.value.status_code == 409
            assert "邮箱" in exc_info.value.detail

    # =========================================================
    # T-004: 注册有邮箱成功
    # =========================================================
    async def test_register_with_email_success(self):
        """提供合法邮箱应注册成功并返回 token"""
        from app.routers.auth import register, RegisterRequest
        mock_user = {"id": 1, "username": "newuser", "is_admin": False, "bank_mode": "public"}
        req = RegisterRequest(username="newuser", password="Pass1234", email="valid@example.com")
        resp = MagicMock()
        async def _mock_run_db(func):
            return 1
        with patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth._issue_token_pair', return_value={"token": "fake", "user": mock_user}):
            result = await register(_mock_request(), req, resp)
            assert "token" in result


# =========================================================
# T-005 / T-006: 登录检测邮箱
# =========================================================
class TestLoginChecksEmail:
    """登录时检查用户是否绑定邮箱"""

    async def test_login_user_with_email_normal_response(self):
        """用户有邮箱 → 正常返回 token"""
        from app.routers.auth import login, LoginRequest
        mock_user_row = {
            "id": 1, "username": "testuser", "password_hash": "$2b$12$hash",
            "is_admin": 0, "bank_mode": "public", "current_position_id": None,
            "email": "test@example.com"
        }
        req = LoginRequest(username="testuser", password="Pass1234")
        resp = MagicMock()
        async def _mock_run_db(func):
            return mock_user_row
        with patch('app.routers.auth._check_lockout'), \
             patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth.verify_password', return_value=True), \
             patch('app.routers.auth._issue_token_pair', return_value={"token": "fake", "user": {"id": 1}}), \
             patch('app.routers.auth._clear_failures'):
            result = await login(_mock_request(), req, resp)
            assert "token" in result
            assert "need_email_bind" not in result

    async def test_login_user_without_email_returns_need_bind(self):
        """用户无邮箱 → 返回 need_email_bind + 临时 token"""
        from app.routers.auth import login, LoginRequest
        mock_user_row = {
            "id": 2, "username": "olduser", "password_hash": "$2b$12$hash",
            "is_admin": 0, "bank_mode": "public", "current_position_id": None,
            "email": None
        }
        req = LoginRequest(username="olduser", password="Pass1234")
        resp = MagicMock()
        async def _mock_run_db(func):
            return mock_user_row
        with patch('app.routers.auth._check_lockout'), \
             patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth.verify_password', return_value=True), \
             patch('app.routers.auth._clear_failures'):
            result = await login(_mock_request(), req, resp)
            assert result.get("need_email_bind") is True
            assert "temp_token" in result
            assert "token" not in result


# =========================================================
# T-007 ~ T-010: 临时 token 绑定邮箱
# =========================================================
class TestBindEmailWithToken:
    """用临时 token 绑定邮箱"""

    async def test_bind_email_with_valid_temp_token_success(self):
        """有效的临时 token + 正确验证码 → 绑定成功并返回正式 token"""
        from app.routers.auth import bind_email_with_token, BindEmailWithTokenRequest
        req = BindEmailWithTokenRequest(email="new@example.com", code="123456")
        resp = MagicMock()
        mock_temp_payload = {"user_id": 2, "username": "olduser", "type": "email_bind"}
        mock_user = {"id": 2, "username": "olduser", "is_admin": False, "bank_mode": "public"}
        async def _mock_run_db(func):
            return True
        with patch('app.routers.auth.decode_email_bind_token', return_value=mock_temp_payload), \
             patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.auth._check_email_exists', return_value=False), \
             patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth._issue_token_pair', return_value={"token": "real_token", "user": mock_user}):
            result = await bind_email_with_token(_mock_request(), req, resp, temp_token="fake_temp")
            assert result.get("token") == "real_token"

    async def test_bind_email_with_wrong_code_returns_400(self):
        """验证码错误 → 返回 400"""
        from app.routers.auth import bind_email_with_token, BindEmailWithTokenRequest
        req = BindEmailWithTokenRequest(email="new@example.com", code="000000")
        resp = MagicMock()
        mock_temp_payload = {"user_id": 2, "username": "olduser", "type": "email_bind"}
        with patch('app.routers.auth.decode_email_bind_token', return_value=mock_temp_payload), \
             patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await bind_email_with_token(_mock_request(), req, resp, temp_token="fake_temp")
            assert exc_info.value.status_code == 400

    async def test_bind_email_with_expired_temp_token_returns_401(self):
        """过期的临时 token → 返回 401"""
        from app.routers.auth import bind_email_with_token, BindEmailWithTokenRequest
        req = BindEmailWithTokenRequest(email="new@example.com", code="123456")
        resp = MagicMock()
        with patch('app.routers.auth.decode_email_bind_token', side_effect=HTTPException(status_code=401, detail="临时令牌已过期，请重新登录")):
            with pytest.raises(HTTPException) as exc_info:
                await bind_email_with_token(_mock_request(), req, resp, temp_token="expired_token")
            assert exc_info.value.status_code == 401

    async def test_email_bind_token_cannot_access_other_api(self):
        """临时 token (type=email_bind) 不能通过 get_current_user 认证"""
        from app.core.auth import decode_token, get_current_user
        with patch('app.core.auth.decode_token') as mock_decode:
            mock_decode.return_value = {"user_id": 2, "type": "email_bind"}
            mock_req = MagicMock()
            mock_req.headers = {"authorization": "Bearer fake_temp_token"}
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(mock_req)
            assert exc_info.value.status_code == 401

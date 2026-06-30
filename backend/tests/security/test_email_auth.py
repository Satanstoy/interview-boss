"""
自动化测试 — 邮箱验证码登录系统
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timedelta
from uuid import uuid4


class TestVerificationCodeGeneration:
    """验证码生成逻辑"""

    def test_generate_code_returns_6_digits(self):
        """验证码应为6位数字字符串"""
        from app.services.email_service import generate_verification_code
        code = generate_verification_code()
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_code_is_random(self):
        """连续生成的验证码应不同（概率上）"""
        from app.services.email_service import generate_verification_code
        codes = {generate_verification_code() for _ in range(20)}
        # 20次生成至少应有2个不同值
        assert len(codes) > 1


class TestSendVerificationCode:
    """发送验证码逻辑"""

    @pytest.mark.asyncio
    async def test_send_code_success(self):
        """正常发送验证码应返回成功"""
        from app.services.email_service import send_verification_code
        mock_config = {"host": "smtp.test.com", "port": 465, "username": "u", "password": "p", "from_addr": "u@test.com", "use_tls": True}
        with patch('app.services.email_service._get_smtp_config', return_value=mock_config), \
             patch('app.services.email_service._smtp_send', new_callable=AsyncMock) as mock_smtp:
            mock_smtp.return_value = True
            result = await send_verification_code(f"send-success-{uuid4().hex}@example.com", "register")
            assert result["success"] is True
            assert "expires_in" in result

    @pytest.mark.asyncio
    async def test_send_code_rate_limit(self):
        """60秒内重复发送应被拒绝"""
        from app.services.email_service import send_verification_code
        mock_config = {"host": "smtp.test.com", "port": 465, "username": "u", "password": "p", "from_addr": "u@test.com", "use_tls": True}
        with patch('app.services.email_service._get_smtp_config', return_value=mock_config), \
             patch('app.services.email_service._smtp_send', new_callable=AsyncMock) as mock_smtp:
            mock_smtp.return_value = True
            # 第一次发送
            await send_verification_code("rate-limit@example.com", "register")
            # 第二次发送（60秒内）
            result = await send_verification_code("rate-limit@example.com", "register")
            assert result["success"] is False
            assert "频繁" in result["message"] or "rate" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_send_code_smtp_not_configured(self):
        """SMTP未配置时应返回503提示"""
        from app.services.email_service import send_verification_code
        with patch('app.services.email_service._get_smtp_config', return_value=None):
            result = await send_verification_code("test@example.com", "register")
            assert result["success"] is False
            assert "未配置" in result["message"] or "not configured" in result["message"].lower()


class TestVerifyCode:
    """验证码校验逻辑"""

    @pytest.mark.asyncio
    async def test_verify_code_correct(self):
        """正确的验证码应校验通过"""
        from app.services.email_service import verify_code, _store_code
        _store_code("test@example.com", "123456", "register", ttl_seconds=300)
        valid = await verify_code("test@example.com", "123456", "register")
        assert valid is True

    @pytest.mark.asyncio
    async def test_verify_code_expired(self):
        """过期的验证码应校验失败"""
        from app.services.email_service import verify_code, _store_code
        # 存储一个已过期的验证码
        with patch('app.services.email_service.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2020, 1, 1, 0, 0, 0)
            mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            _store_code("test@example.com", "123456", "register", ttl_seconds=1)
        # 当前时间已远超过期时间
        valid = await verify_code("test@example.com", "123456", "register")
        assert valid is False

    @pytest.mark.asyncio
    async def test_verify_code_wrong(self):
        """错误的验证码应校验失败"""
        from app.services.email_service import verify_code, _store_code
        _store_code("test@example.com", "123456", "register", ttl_seconds=300)
        valid = await verify_code("test@example.com", "000000", "register")
        assert valid is False

    @pytest.mark.asyncio
    async def test_verify_code_already_used(self):
        """已使用的验证码应校验失败"""
        from app.services.email_service import verify_code, _store_code
        _store_code("test@example.com", "123456", "register", ttl_seconds=300)
        # 第一次验证成功
        await verify_code("test@example.com", "123456", "register")
        # 第二次验证应失败（已使用）
        valid = await verify_code("test@example.com", "123456", "register")
        assert valid is False

    @pytest.mark.asyncio
    async def test_verify_code_no_code_sent(self):
        """未发送验证码时校验应失败"""
        from app.services.email_service import verify_code
        valid = await verify_code("nobody@example.com", "123456", "register")
        assert valid is False


def _mock_request():
    """创建一个 mock Request 对象，满足 slowapi 的要求"""
    from unittest.mock import MagicMock
    from starlette.requests import Request as StarletteRequest
    req = MagicMock(spec=StarletteRequest)
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    req.headers = {"user-agent": "test"}
    return req


class TestEmailRegisterEndpoint:
    """邮箱注册端点测试"""

    @pytest.mark.asyncio
    async def test_register_with_email_success(self):
        """邮箱注册成功应返回token"""
        from app.routers.auth import register_with_email, EmailRegisterRequest
        mock_user = {"id": 99, "username": "newuser", "is_admin": False, "bank_mode": "public"}
        mock_resp = MagicMock()
        req = EmailRegisterRequest(email="new@example.com", code="123456", username="newuser", password="Pass1234")
        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.auth._check_username_available', return_value=True), \
             patch('app.routers.auth._check_email_exists', return_value=False), \
             patch('app.routers.auth._insert_user', return_value=mock_user), \
             patch('app.routers.auth._issue_token_pair', return_value={"token": "fake_access", "user": mock_user}):
            result = await register_with_email(_mock_request(), req, mock_resp)
            assert "token" in result

    @pytest.mark.asyncio
    async def test_register_with_email_wrong_code(self):
        """验证码错误应返回400"""
        from app.routers.auth import register_with_email, EmailRegisterRequest
        from fastapi import HTTPException
        mock_resp = MagicMock()
        req = EmailRegisterRequest(email="new@example.com", code="000000", username="newuser", password="Pass1234")
        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await register_with_email(_mock_request(), req, mock_resp)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_register_with_email_already_exists(self):
        """已注册邮箱应返回409"""
        from app.routers.auth import register_with_email, EmailRegisterRequest
        from fastapi import HTTPException
        mock_resp = MagicMock()
        req = EmailRegisterRequest(email="existing@example.com", code="123456", username="newuser", password="Pass1234")
        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.auth._check_username_available', return_value=True), \
             patch('app.routers.auth._check_email_exists', return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await register_with_email(_mock_request(), req, mock_resp)
            assert exc_info.value.status_code == 409


class TestEmailLoginEndpoint:
    """邮箱登录端点测试"""

    @pytest.mark.asyncio
    async def test_login_with_email_success(self):
        """邮箱登录成功应返回token"""
        from app.routers.auth import login_with_email, EmailLoginRequest
        mock_user = {"id": 1, "username": "testuser", "is_admin": False, "bank_mode": "public"}
        mock_resp = MagicMock()
        req = EmailLoginRequest(email="test@example.com", code="123456")
        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.auth._find_user_by_email', return_value=mock_user), \
             patch('app.routers.auth._issue_token_pair', return_value={"token": "fake_access", "user": mock_user}):
            result = await login_with_email(_mock_request(), req, mock_resp)
            assert "token" in result

    @pytest.mark.asyncio
    async def test_login_with_email_not_found(self):
        """未注册邮箱登录应返回404"""
        from app.routers.auth import login_with_email, EmailLoginRequest
        from fastapi import HTTPException
        mock_resp = MagicMock()
        req = EmailLoginRequest(email="nobody@example.com", code="123456")
        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.auth._find_user_by_email', return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await login_with_email(_mock_request(), req, mock_resp)
            assert exc_info.value.status_code == 404


class TestPasswordResetEndpoint:
    """忘记密码 / 修改密码端点测试"""

    @pytest.mark.asyncio
    async def test_reset_password_success(self):
        """邮箱验证码正确时应更新密码并清除失败计数"""
        from app.routers.auth import reset_password, PasswordResetRequest

        mock_user = {"id": 1, "username": "testuser", "password_hash": "old_hash"}
        req = PasswordResetRequest(email="test@example.com", code="123456", new_password="NewPass123")

        async def _mock_run_db(func):
            return func()

        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.auth._find_user_by_email', return_value=mock_user), \
             patch('app.routers.auth.hash_password', return_value="new_hash"), \
             patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth.get_db_connection') as mock_conn, \
             patch('app.routers.auth._clear_failures') as mock_clear:
            conn = MagicMock()
            mock_conn.return_value.__enter__.return_value = conn

            result = await reset_password(_mock_request(), req)

            assert result["status"] == "success"
            conn.execute.assert_called_once()
            args = conn.execute.call_args.args
            assert "UPDATE users SET password_hash" in args[0]
            assert args[1] == ("new_hash", 1)
            mock_clear.assert_called_once_with("testuser")

    @pytest.mark.asyncio
    async def test_reset_password_wrong_code(self):
        """验证码错误应返回 400"""
        from app.routers.auth import reset_password, PasswordResetRequest
        from fastapi import HTTPException

        req = PasswordResetRequest(email="test@example.com", code="000000", new_password="NewPass123")
        with patch('app.routers.auth.verify_code', new_callable=AsyncMock, return_value=False):
            with pytest.raises(HTTPException) as exc_info:
                await reset_password(_mock_request(), req)
            assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_change_password_success(self):
        """已登录用户提供当前密码后可以修改密码"""
        from app.routers.auth import change_password, ChangePasswordRequest

        current_user = {"id": 1, "username": "testuser"}
        db_user = {"id": 1, "username": "testuser", "password_hash": "old_hash"}
        req = ChangePasswordRequest(current_password="OldPass123", new_password="NewPass123")

        async def _mock_run_db(func):
            return func()

        with patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth.get_db_connection') as mock_conn, \
             patch('app.routers.auth.verify_password', side_effect=[True, False]), \
             patch('app.routers.auth.hash_password', return_value="new_hash"):
            query_conn = MagicMock()
            update_conn = MagicMock()
            query_conn.execute.return_value.fetchone.return_value = db_user
            mock_conn.return_value.__enter__.side_effect = [query_conn, update_conn]

            result = await change_password(_mock_request(), req, current_user=current_user)

            assert result["status"] == "success"
            update_conn.execute.assert_called_once()
            args = update_conn.execute.call_args.args
            assert "UPDATE users SET password_hash" in args[0]
            assert args[1] == ("new_hash", 1)

    @pytest.mark.asyncio
    async def test_change_password_wrong_current_password(self):
        """当前密码错误应返回 400"""
        from app.routers.auth import change_password, ChangePasswordRequest
        from fastapi import HTTPException

        current_user = {"id": 1, "username": "testuser"}
        db_user = {"id": 1, "username": "testuser", "password_hash": "old_hash"}
        req = ChangePasswordRequest(current_password="WrongPass123", new_password="NewPass123")

        async def _mock_run_db(func):
            return func()

        with patch('app.routers.auth.run_db', side_effect=_mock_run_db), \
             patch('app.routers.auth.get_db_connection') as mock_conn, \
             patch('app.routers.auth.verify_password', return_value=False):
            query_conn = MagicMock()
            query_conn.execute.return_value.fetchone.return_value = db_user
            mock_conn.return_value.__enter__.return_value = query_conn

            with pytest.raises(HTTPException) as exc_info:
                await change_password(_mock_request(), req, current_user=current_user)
            assert exc_info.value.status_code == 400


class TestBindEmailEndpoint:
    """绑定邮箱端点测试"""

    @pytest.mark.asyncio
    async def test_bind_email_success(self):
        """绑定邮箱成功"""
        from app.routers.profile_pkg.email import bind_email, BindEmailRequest
        mock_user = {"id": 1, "username": "testuser"}
        req = BindEmailRequest(email="new@example.com", code="123456")
        with patch('app.routers.profile_pkg.email.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.profile_pkg.email._check_email_taken', return_value=False), \
             patch('app.routers.profile_pkg.email._update_user_email', return_value=True):
            result = await bind_email(req, user=mock_user)
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_bind_email_already_taken(self):
        """绑定已被其他用户使用的邮箱应返回409"""
        from app.routers.profile_pkg.email import bind_email, BindEmailRequest
        from fastapi import HTTPException
        mock_user = {"id": 1, "username": "testuser"}
        req = BindEmailRequest(email="taken@example.com", code="123456")
        with patch('app.routers.profile_pkg.email.verify_code', new_callable=AsyncMock, return_value=True), \
             patch('app.routers.profile_pkg.email._check_email_taken', return_value=True):
            with pytest.raises(HTTPException) as exc_info:
                await bind_email(req, user=mock_user)
            assert exc_info.value.status_code == 409

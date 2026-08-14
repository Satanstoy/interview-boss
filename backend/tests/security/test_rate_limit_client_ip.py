"""限速 client-IP 隔离回归测试。

覆盖安全审计发现 #1（D4）：
- auth/email 的 slowapi limiter 原用 get_remote_address（→request.client.host），
  在 Docker nginx 反代下所有客户端折叠为同一 nginx 容器 IP，限速变成全站共享桶，
  per-IP 爆破防护失效、单点可造成整站登录 DoS。
- 修复：auth/email limiter 改用 app.core.request_ip.get_client_ip，
  它仅在可信代理 CIDR 内才信任 X-Forwarded-For，从而按真实客户端 IP 分桶；
  asgi 全局默认 200/min 由 request 中间件强制执行。
"""

from __future__ import annotations


def _fake_request(peer: str, xff: str | None = None):
    """构造带 peer + 可选 XFF 的伪 request（满足 request_ip.get_client_ip）。"""
    class _Client:
        host = peer

    class _Req:
        def __init__(self):
            self.client = _Client()
            self.headers = {}
            if xff is not None:
                self.headers["x-forwarded-for"] = xff

    return _Req()


class TestGetClientIPFromTrustedProxy:
    """代理头仅在可信对端时被采用；非可信对端不信任 XFF。"""

    def test_trusted_proxy_returns_xff_client_ip(self):
        from app.core.request_ip import get_client_ip

        req = _fake_request(peer="172.18.0.3", xff="203.0.113.7")
        assert get_client_ip(req) == "203.0.113.7"

    def test_untrusted_peer_ignores_xff(self):
        from app.core.request_ip import get_client_ip

        req = _fake_request(peer="8.8.8.8", xff="203.0.113.9")
        # 非信任对端：不能接受客户端自报的 XFF，回退到对端 IP
        assert get_client_ip(req) == "8.8.8.8"

    def test_trusted_proxy_tail_hop_wins(self):
        from app.core.request_ip import get_client_ip

        # 形如 "client, proxy1, proxy2"：从右往左取第一个非可信地址
        req = _fake_request(
            peer="172.18.0.3",
            xff="203.0.113.11, 172.18.0.2, 172.18.0.1",
        )
        assert get_client_ip(req) == "203.0.113.11"


class TestAuthLimiterUsesClientIP:
    """登录/注册/刷新/邮箱验证码限速必须按真实客户端 IP 分桶。"""

    def test_auth_limiter_key_is_get_client_ip(self):
        from app.routers import auth as auth_module

        assert auth_module.limiter._key_func is not None
        # 必须是 request_ip.get_client_ip（而非 slowapi get_remote_address）
        assert auth_module.limiter._key_func.__module__ == "app.core.request_ip"

    def test_email_limiter_key_is_get_client_ip(self):
        from app.routers.profile_pkg import email as email_module

        assert email_module.limiter._key_func is not None
        assert email_module.limiter._key_func.__module__ == "app.core.request_ip"


class TestAsgiGlobalDefaultWired:
    """全局默认限速（asgi 200/min）必须经中间件强制执行，而非空配置。"""

    def test_asgi_limiter_has_default_and_is_on_app_state(self, client):
        # 经 client fixture 安全导入 asgi（避免在其上跑生产库迁移）
        from app.asgi import app, limiter
        from limits import parse_many

        assert app.state.limiter is limiter
        assert len(limiter._default_limits) >= 1
        # 把全局默认限速解析为 RateLimitItem，确认存在 200 请求/分钟档
        amounts = {
            item.amount
            for group in limiter._default_limits
            for item in parse_many(group._LimitGroup__limit_provider)
        }
        assert 200 in amounts

    def test_global_default_is_enforced_by_middleware(self, client):
        # 全局 200/min 默认必须由请求中间件强制执行：连续快速请求同一端点
        # 不应让任意未单独限速的路由无限请求。此测试只断言中间件确实挂在 app 上。
        from app.asgi import app

        middlewares = [m.cls for m in app.user_middleware]
        assert any(
            m is not None and "rate" in (getattr(m, "__name__", "") or "").lower()
            or (m is not None and m.__name__.lower() == "slowapi")
            for m in middlewares
        )

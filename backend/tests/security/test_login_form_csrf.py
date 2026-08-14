"""login-form 同源校验与锁定 DoS 防护回归测试。

覆盖安全审计发现 #6（D4）：
- /api/auth/login-form 因浏览器密码管理器（隐藏 iframe 表单提交）豁免全局 CSRF。
- 修复：在路由内补 _is_same_origin_request 同源校验，跨源 Origin/Referer 一律 403，
  封堵跨站表单可触发的账号锁定 DoS；同源请求不受影响。
"""

from __future__ import annotations


def _fake_req(headers: dict):
    """构造带指定 headers 的伪 request（满足 _is_same_origin_request）。"""
    from starlette.requests import Request as StarletteRequest
    from unittest.mock import MagicMock

    req = MagicMock(spec=StarletteRequest)
    req.headers.get = lambda key, default=None, **kw: headers.get(key.lower(), default)
    return req


class TestSameOriginRequest:
    def test_same_origin_returns_true(self):
        from app.routers.auth import _is_same_origin_request

        req = _fake_req({"origin": "https://interviewboss.online", "host": "interviewboss.online"})
        assert _is_same_origin_request(req) is True

    def test_cross_origin_https_rejected(self):
        from app.routers.auth import _is_same_origin_request

        req = _fake_req({
            "origin": "https://evil.example.com",
            "host": "interviewboss.online",
        })
        assert _is_same_origin_request(req) is False

    def test_cross_origin_via_referer_rejected(self):
        from app.routers.auth import _is_same_origin_request

        req = _fake_req({
            "referer": "https://evil.example.com/login",
            "host": "interviewboss.online",
        })
        assert _is_same_origin_request(req) is False

    def test_no_origin_or_referer_returns_true(self):
        # 非浏览器客户端（无 Origin/Referer）按同源放行
        from app.routers.auth import _is_same_origin_request

        req = _fake_req({"host": "interviewboss.online"})
        assert _is_same_origin_request(req) is True

    def test_same_origin_port_compared(self):
        from app.routers.auth import _is_same_origin_request

        req = _fake_req({
            "origin": "http://localhost:3000",
            "host": "localhost:3000",
        })
        assert _is_same_origin_request(req) is True


class TestLoginFormCrossOriginRejected:
    """跨源提交 /api/auth/login-form 必须被 403 拒绝，不能触发放失败计数锁定。"""

    def test_cross_origin_login_form_returns_403(self, client):
        r = client.post(
            "/api/auth/login-form",
            data={"username": "victim", "password": "WrongPass1!"},
            headers={
                "Origin": "https://evil.example.com",
                "Host": "testserver",
            },
        )
        assert r.status_code == 403

    def test_same_origin_login_form_not_blocked(self, client):
        # 同源（TestClient 缺省 Host=testserver、不带 Origin）应正常返回（200/密码校验）
        r = client.post(
            "/api/auth/login-form",
            data={"username": "nobody", "password": "WrongPass1!"},
        )
        assert r.status_code in (200,)

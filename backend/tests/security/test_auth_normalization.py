"""认证归一化回归测试。

覆盖 D9/A1 findings：
- users.username 唯一约束 BINARY 大小写敏感且注册不归一化（'Alice'/'alice' 双账户）
- profile_pkg/email.py 绑定邮箱路径未归一化（可绑大小写变体邮箱）
- login_failures.locked_until REAL epoch 与全库 TIMESTAMP 文本混杂（迁移 084 改为 TEXT）
"""

from __future__ import annotations

import re

import pytest


PASSWORD = "Passw0rd!x"


def _register(client, username: str, email: str):
    return client.post(
        "/api/auth/register",
        json={"username": username, "password": PASSWORD, "email": email},
    )


class TestRegisterUsernameNormalization:
    def test_register_lowercases_and_strips_username(self, client, test_db):
        r = _register(client, "  Alice  ", "alice@example.com")
        assert r.status_code == 200
        row = test_db.execute(
            "SELECT username FROM users WHERE email = 'alice@example.com'"
        ).fetchone()
        assert row is not None
        assert row["username"] == "alice"

    def test_register_case_variant_conflicts(self, client):
        assert _register(client, "Alice", "alice1@example.com").status_code == 200
        r2 = _register(client, "alice", "alice2@example.com")
        assert r2.status_code == 409
        assert "用户名已存在" in r2.json()["detail"]

    def test_register_still_rejects_invalid_chars(self, client):
        # 归一化后再校验：'A B' 含空格 → 422
        r = _register(client, "A B", "ab@example.com")
        assert r.status_code == 422


class TestLoginCaseInsensitive:
    def test_login_accepts_any_case(self, client):
        assert _register(client, "Carol", "carol@example.com").status_code == 200
        for name in ("carol", "CAROL", "cArOl"):
            r = client.post(
                "/api/auth/login", json={"username": name, "password": PASSWORD}
            )
            assert r.status_code == 200, f"login with {name} failed"


class TestBindEmailNormalization:
    def test_bind_email_request_normalizes(self):
        from app.routers.profile_pkg.email import BindEmailRequest

        req = BindEmailRequest(email="  User@Example.COM  ", code="123456")
        assert req.email == "user@example.com"

    def test_send_bind_code_request_normalizes(self):
        from app.routers.profile_pkg.email import SendBindCodeRequest

        req = SendBindCodeRequest(email="User@Example.COM")
        assert req.email == "user@example.com"


class TestLockoutTextFormat:
    def test_lockout_writes_text_timestamp_and_blocks(self, client, test_db):
        for _ in range(5):
            client.post(
                "/api/auth/login", json={"username": "nobody", "password": "WrongPass1!"}
            )
        row = test_db.execute(
            "SELECT locked_until, failure_count FROM login_failures WHERE username = 'nobody'"
        ).fetchone()
        assert row is not None
        assert row["failure_count"] == 5
        locked = row["locked_until"]
        assert isinstance(locked, str)
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", locked), locked
        # 第 6 次被锁定拦截
        r = client.post(
            "/api/auth/login", json={"username": "nobody", "password": "WrongPass1!"}
        )
        assert r.status_code == 429

    def test_unlocked_rows_use_empty_string(self, client, test_db):
        client.post(
            "/api/auth/login", json={"username": "newbie", "password": "WrongPass1!"}
        )
        row = test_db.execute(
            "SELECT locked_until FROM login_failures WHERE username = 'newbie'"
        ).fetchone()
        assert row is not None
        assert row["locked_until"] == ""

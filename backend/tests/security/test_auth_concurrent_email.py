"""
审计 D14：并发重复 email 注册/绑定返回 500 而非 409。

根因：register/_insert_user/bind_email_with_token 都是 check-then-write 的非原子流程，
并发下两个请求同时通过检查，一个写操作撞 users.email 唯一索引抛 sqlite3.IntegrityError，
被外层泛 except 捕获 → 500；_record_failure 的 SELECT-then-INSERT 同型竞态也会漏 IntegrityError。

期望：所有 IntegrityError 映射为 HTTPException(409)，_record_failure 改为原子 upsert。
"""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from unittest.mock import patch

import pytest


def _register_payload(username: str, email: str) -> dict:
    return {"username": username, "password": "Passw0rd!x", "email": email}


class TestRegisterEmailRace:
    """register 的 _create() 为 check-then-insert，并发撞 email 唯一索引必须 409 而非 500。"""

    def test_register_email_race_returns_409_not_500(self, client, test_db):
        """"确定性复现并发竞态：SELECT 检查通过后、INSERT 前，另一个请求已插入同 email。

        patch hash_password 在「检查邮箱」与「INSERT」之间注入竞争行，绕开预先存在的
        邮箱检查，逼 INSERT 撞 users.email 唯一索引。修复前 IntegrityError 冒泡成 500，
        修复后应返回 409。
        """
        email = "race@example.com"
        injected = False

        def racing_hash(pw):
            nonlocal injected
            if not injected:
                # 模拟并发请求在检查与 INSERT 之间抢先提交了同 email 的用户
                test_db.execute(
                    "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                    "VALUES (?, ?, ?, 0, 'private')",
                    ("racer_a", "hash", email),
                )
                test_db.commit()
                injected = True
            return "hash"

        with patch("app.routers.auth.hash_password", side_effect=racing_hash):
            resp = client.post(
                "/api/auth/register",
                json=_register_payload("racer_b", email),
            )
        assert resp.status_code == 409, f"期望 409，实际 {resp.status_code}: {resp.text}"
        assert "该邮箱已被注册" in resp.json()["detail"]

    def test_concurrent_register_same_email_one_success_one_409(self, client):
        """并发 register 同 email：恰好一个成功，另一个 409，绝不允许 500。"""
        email = "concurrent-race@example.com"
        payloads = [
            _register_payload("conc01", email),
            _register_payload("conc02", email),
        ]

        def _register(payload):
            return client.post("/api/auth/register", json=payload)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(_register, payloads))

        codes = sorted(r.status_code for r in results)
        assert codes[0] == 200, f"应恰好一个成功，实际 {codes}: {[r.text for r in results]}"
        assert codes[1] == 409, f"应恰好一个 409，实际 {codes}: {[r.text for r in results]}"


class TestRegisterWithEmailRace:
    """_insert_user() 裸 INSERT 无 try，撞 email 唯一索引必须 409 而非 500。"""

    def test_register_with_email_race_returns_409(self, client, test_db):
        """register-with-email 的 _check_email_exists 检查通过后、_insert_user 插入时撞唯一索引。"""
        email = "wemail-race@example.com"
        test_db.execute(
            "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
            "VALUES (?, ?, ?, 0, 'private')",
            ("wexisting", "hash", email),
        )
        test_db.commit()

        # 模拟竞态：检查时假装邮箱可用，但实际已存在 → INSERT 撞唯一索引
        with patch("app.routers.auth.verify_code", return_value=True),              patch("app.routers.auth._check_email_exists", return_value=False):
            resp = client.post(
                "/api/auth/register-with-email",
                json={
                    "username": "wnewuser",
                    "password": "Passw0rd!x",
                    "email": email,
                    "code": "123456",
                },
            )
        assert resp.status_code == 409, f"期望 409，实际 {resp.status_code}: {resp.text}"
        assert "该邮箱已注册" in resp.json()["detail"]


class TestBindEmailWithTokenRace:
    """bind_email_with_token 的 UPDATE users SET email 撞唯一索引必须 409 而非 500。"""

    def test_bind_email_update_race_returns_409(self, client, test_db):
        """绑定邮箱时另一个用户已抢占该邮箱，UPDATE 撞唯一索引 → 409。"""
        from app.routers import auth as auth_module

        target_email = "bind-race@example.com"
        test_db.execute(
            "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
            "VALUES (?, ?, ?, 0, 'private')",
            ("bind_target", "hash", None),
        )
        test_db.commit()
        target_id = test_db.execute(
            "SELECT id FROM users WHERE username = 'bind_target'"
        ).fetchone()["id"]

        real_conn = test_db

        class _RacingConn:
            """代理连接：检查 SELECT 正常返回，UPDATE email 时模拟并发抢占撞唯一索引。"""

            def __init__(self, real):
                self._real = real

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                if sql.strip().upper().startswith("UPDATE USERS SET EMAIL"):
                    raise sqlite3.IntegrityError("UNIQUE constraint failed: users.email")
                return self._real.execute(sql, params)

            def commit(self):
                self._real.commit()

        with patch("app.routers.auth.get_db_connection", return_value=_RacingConn(real_conn)), \
             patch("app.routers.auth.verify_code", return_value=True), \
             patch.object(
                 auth_module,
                 "decode_email_bind_token",
                 return_value={"user_id": target_id, "username": "bind_target"},
             ):
            resp = client.post(
                "/api/auth/bind-email-with-token",
                headers={"authorization": "Bearer fake-token"},
                json={"email": target_email, "code": "123456"},
            )
        assert resp.status_code == 409, f"期望 409，实际 {resp.status_code}: {resp.text}"
        assert "该邮箱已被其他用户绑定" in resp.json()["detail"]


class TestRecordFailureAtomic:
    """_record_failure 为 SELECT-then-INSERT，改为原子 upsert 后不因竞态丢计数/漏 IntegrityError。"""

    def test_record_failure_increments_via_upsert(self, client, test_db):
        from app.routers.auth import _record_failure

        username = "upsert_user"
        for _ in range(3):
            _record_failure(username)

        row = test_db.execute(
            "SELECT failure_count, locked_until FROM login_failures WHERE username = ?",
            (username,),
        ).fetchone()
        assert row is not None
        assert row["failure_count"] == 3
        assert row["locked_until"] == ""

    def test_record_failure_locks_at_threshold(self, test_db):
        from app.routers.auth import _record_failure, MAX_LOGIN_FAILURES

        username = "lock_user"
        for _ in range(MAX_LOGIN_FAILURES):
            _record_failure(username)

        row = test_db.execute(
            "SELECT failure_count, locked_until FROM login_failures WHERE username = ?",
            (username,),
        ).fetchone()
        assert row["failure_count"] == MAX_LOGIN_FAILURES
        assert row["locked_until"] != ""

    def test_record_failure_repeated_never_raises(self, test_db):
        """连续失败不会因 SELECT-then-INSERT 竞态抛 IntegrityError（原子 upsert）。"""
        from app.routers.auth import _record_failure, MAX_LOGIN_FAILURES

        username = "repeat_user"
        for _ in range(MAX_LOGIN_FAILURES + 3):
            _record_failure(username)  # 不应抛异常
        row = test_db.execute(
            "SELECT failure_count FROM login_failures WHERE username = ?",
            (username,),
        ).fetchone()
        assert row is not None
        assert row["failure_count"] == MAX_LOGIN_FAILURES + 3

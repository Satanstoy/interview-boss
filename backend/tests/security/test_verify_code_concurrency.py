
"""
自动化测试 — 邮箱验证码竞态修复（audit D14）与每邮箱失败锁定（audit D4）。

覆盖：
- verify_code 的"校验+标记已用"必须是单条原子 UPDATE，同一有效码只能被消费一次；
- 连续失败达到阈值后，该码被作废（即使之后输入正确码也失败）；
- 成功消费 / 重新发送新码都会重置失败计数。

使用内存 SQLite（test_db fixture），不触碰生产库。
"""
import asyncio
import pytest

_LOCKOUT_THRESHOLD = 5


class TestAtomicConsume:
    """verify_code 原子消费（D14：check-then-act 竞态）。"""

    @pytest.mark.asyncio
    async def test_concurrent_verify_consumes_exactly_once(self, test_db):
        """并发校验同一有效码时，结果必须恰好一次成功。"""
        from app.services.email_service import verify_code, _store_code

        email = "race@example.com"
        code = "123456"
        _store_code(email, code, "register", ttl_seconds=300)

        results = await asyncio.gather(
            verify_code(email, code, "register"),
            verify_code(email, code, "register"),
        )
        assert sum(results) == 1, f"同一验证码被并发消费 {sum(results)} 次"

        # 消费后该码必须被置为已用，无法再通过
        assert await verify_code(email, code, "register") is False

    def test_atomic_update_consume_guard(self, test_db):
        """同一原子 UPDATE 连续执行两次，第二次必须影响 0 行（used=0 门）。"""
        from datetime import datetime
        from app.services.email_service import verify_code, _store_code, _normalize_email

        email = "atomic@example.com"
        code = "123456"
        _store_code(email, code, "register", ttl_seconds=300)

        conn = test_db
        now_iso = datetime.now().isoformat()
        sql = (
            "UPDATE email_verification_codes "
            "SET used = 1 "
            "WHERE email = ? AND purpose = ? AND used = 0 AND code = ? "
            "AND expires_at > ?"
        )
        cur = conn.execute(sql, (_normalize_email(email), "register", code, now_iso))
        conn.commit()
        assert cur.rowcount == 1

        # 第二次执行同一原子 UPDATE：used 已为 1，影响 0 行
        cur2 = conn.execute(sql, (_normalize_email(email), "register", code, now_iso))
        conn.commit()
        assert cur2.rowcount == 0


class TestFailureLockout:
    """每邮箱失败锁定（D4：连续失败 N 次作废该码）。"""

    @pytest.mark.asyncio
    async def test_less_than_threshold_failures_then_success(self, test_db):
        """失败次数未达阈值时，输入正确码仍应成功。"""
        from app.services.email_service import verify_code, _store_code

        email = "lockout-ok@example.com"
        code = "123456"
        _store_code(email, code, "register", ttl_seconds=300)

        for wrong in ("000000", "111111", "222222", "333333"):
            assert await verify_code(email, wrong, "register") is False

        # 第 5 次输入正确码应成功（前 4 次失败未达阈值）
        assert await verify_code(email, code, "register") is True

    @pytest.mark.asyncio
    async def test_threshold_failures_invalidate_code(self, test_db):
        """连续失败达阈值后，即使输入正确码也应失败（码被作废）。"""
        from app.services.email_service import verify_code, _store_code

        email = "lockout-locked@example.com"
        code = "123456"
        _store_code(email, code, "register", ttl_seconds=300)

        wrong = "000000"
        for _ in range(_LOCKOUT_THRESHOLD):
            assert await verify_code(email, wrong, "register") is False

        # 已达阈值，正确码也被拒绝
        assert await verify_code(email, code, "register") is False

    @pytest.mark.asyncio
    async def test_lockout_is_per_email(self, test_db):
        """锁定按邮箱隔离，不影响其他邮箱的验证码。"""
        from app.services.email_service import verify_code, _store_code

        victim_email = "lockout-victim@example.com"
        other_email = "lockout-other@example.com"
        code = "123456"
        _store_code(victim_email, code, "register", ttl_seconds=300)
        _store_code(other_email, code, "register", ttl_seconds=300)

        for _ in range(_LOCKOUT_THRESHOLD):
            await verify_code(victim_email, "000000", "register")

        # victim 被锁定
        assert await verify_code(victim_email, code, "register") is False
        # 其他邮箱不受影响
        assert await verify_code(other_email, code, "register") is True

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, test_db):
        """一次成功消费应重置失败计数。"""
        from app.services.email_service import verify_code, _store_code

        email = "lockout-reset@example.com"
        code = "123456"
        _store_code(email, code, "register", ttl_seconds=300)

        assert await verify_code(email, "000000", "register") is False
        assert await verify_code(email, "111111", "register") is False
        assert await verify_code(email, code, "register") is True

        # 成功后再发新码，失败计数从 0 重新累计
        code2 = "654321"
        _store_code(email, code2, "register", ttl_seconds=300)
        # 前 _LOCKOUT_THRESHOLD - 1 次失败不锁定
        for _ in range(_LOCKOUT_THRESHOLD - 1):
            assert await verify_code(email, "000000", "register") is False
        assert await verify_code(email, code2, "register") is True

    @pytest.mark.asyncio
    async def test_send_new_code_resets_failure_count(self, test_db):
        """重新发送新码应重置失败计数（旧码作废、计数清零）。"""
        from app.services.email_service import verify_code, _store_code

        email = "lockout-newcode@example.com"
        _store_code(email, "111111", "register", ttl_seconds=300)
        for _ in range(_LOCKOUT_THRESHOLD - 1):
            await verify_code(email, "000000", "register")

        # 重新发送新码 → 失败计数清零，新码前 N-1 次失败不锁定
        _store_code(email, "222222", "register", ttl_seconds=300)
        for _ in range(_LOCKOUT_THRESHOLD - 1):
            assert await verify_code(email, "000000", "register") is False
        assert await verify_code(email, "222222", "register") is True

"""LLM per-user daily quota tests.

- first call within the limit passes and records usage
- calls beyond the daily limit fail (check_and_record returns False)
- usage resets the next day (per-user per-day granularity)
- router wiring: over-quota requests are rejected with 429 on LLM entry points
"""

from unittest.mock import patch

import pytest

import app.services.llm_quota as quota


@pytest.fixture
def sync_db(test_db):
    """Run run_db synchronously in the test thread so it sees the test connection."""
    with patch.object(quota, "run_db", side_effect=lambda f: f()):
        yield test_db


def _insert_usage(test_db, user_id, day, call_count, total_tokens):
    test_db.execute(
        "INSERT INTO llm_usage (user_id, day, call_count, total_tokens) "
        "VALUES (?, ?, ?, ?)",
        (user_id, day, call_count, total_tokens),
    )
    test_db.commit()


async def test_first_call_passes_and_records_usage(sync_db):
    with patch.object(quota, "_today", return_value="2026-08-10"):
        assert await quota.check_and_record(1) is True

    row = sync_db.execute(
        "SELECT call_count, total_tokens FROM llm_usage WHERE user_id = 1 AND day = '2026-08-10'"
    ).fetchone()
    assert row is not None
    assert row["call_count"] == 1


async def test_calls_accumulate_until_reaching_limit(sync_db):
    with patch.object(quota, "_today", return_value="2026-08-10"):
        # limit 3: first two calls pass
        assert await quota.check_and_record(1, limit=3) is True
        assert await quota.check_and_record(1, limit=3) is True
        # third call reaches the limit and still passes
        assert await quota.check_and_record(1, limit=3) is True
        # fourth call exceeds the limit and is rejected
        assert await quota.check_and_record(1, limit=3) is False

    row = sync_db.execute(
        "SELECT call_count FROM llm_usage WHERE user_id = 1 AND day = '2026-08-10'"
    ).fetchone()
    assert row["call_count"] == 3


async def test_default_limit_constant_is_used_when_no_limit_passed(sync_db):
    # seed usage at the default limit so the next call is rejected
    _insert_usage(sync_db, 5, "2026-08-10", quota.DAILY_LLM_CALL_LIMIT, 0)
    with patch.object(quota, "_today", return_value="2026-08-10"):
        assert await quota.check_and_record(5) is False


async def test_usage_resets_across_days(sync_db):
    with patch.object(quota, "_today", return_value="2026-08-10"):
        assert await quota.check_and_record(2, limit=1) is True
        assert await quota.check_and_record(2, limit=1) is False
    # next day the quota resets
    with patch.object(quota, "_today", return_value="2026-08-11"):
        assert await quota.check_and_record(2, limit=1) is True


async def test_accumulates_total_tokens(sync_db):
    with patch.object(quota, "_today", return_value="2026-08-10"):
        assert await quota.check_and_record(3, tokens=120) is True
        assert await quota.check_and_record(3, tokens=80) is True

    row = sync_db.execute(
        "SELECT total_tokens FROM llm_usage WHERE user_id = 3 AND day = '2026-08-10'"
    ).fetchone()
    assert row["total_tokens"] == 200


async def test_quota_is_per_user(sync_db):
    with patch.object(quota, "_today", return_value="2026-08-10"):
        assert await quota.check_and_record(10, limit=1) is True
        assert await quota.check_and_record(10, limit=1) is False
        # a different user is unaffected by user 10's usage
        assert await quota.check_and_record(11, limit=1) is True


# ── Router wiring smoke tests ──────────────────────────────────────────────


def _make_user(client, test_db, seq):
    """Create a test user and return (Bearer token, user_id)."""
    from app.core.auth import create_access_token

    username = f"test_quota_user_{seq}"
    cursor = test_db.execute(
        "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
        "VALUES (?, ?, ?, 0, 'private')",
        (username, "test-hash", f"{username}@example.com"),
    )
    test_db.commit()
    user_id = cursor.lastrowid
    token = create_access_token({"user_id": user_id, "type": "access"})
    return token, user_id


_USER_SEQ = {"n": 0}


def test_evaluate_answer_returns_429_when_quota_exceeded(client, test_db):
    """Over-quota user is rejected with 429 on the evaluate-answer LLM endpoint."""
    _USER_SEQ["n"] += 1
    token, user_id = _make_user(client, test_db, _USER_SEQ["n"])
    with patch.object(quota, "_today", return_value="2026-08-10"):
        _insert_usage(test_db, user_id, "2026-08-10", quota.DAILY_LLM_CALL_LIMIT, 0)
        resp = client.post(
            "/api/evaluate-answer",
            json={
                "question_id": 1,
                "question_text": "Q?",
                "user_answer": "answer",
                "reference_answer": "ref",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 429
    assert "上限" in resp.json()["detail"]


def test_coding_submit_returns_429_when_quota_exceeded(client, test_db):
    """Over-quota user is rejected with 429 on the coding review endpoint."""
    _USER_SEQ["n"] += 1
    token, user_id = _make_user(client, test_db, _USER_SEQ["n"])
    with patch.object(quota, "_today", return_value="2026-08-10"):
        _insert_usage(test_db, user_id, "2026-08-10", quota.DAILY_LLM_CALL_LIMIT, 0)
        resp = client.post(
            "/api/coding/submit",
            json={
                "problem_id": 1,
                "language": "python",
                "code": "print(1)",
                "mode": "full_review",
                "coding_mode": "leetcode",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 429
    assert "上限" in resp.json()["detail"]

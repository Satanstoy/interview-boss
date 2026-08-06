"""
招聘偏好 API 测试 — GET/PUT /api/profile/recruitment

用户创建与 token 签发复用 repo 既有模式（test_authz_unification.py 同款：
直插 users 表 + create_access_token），避免 /api/auth/register 的 slowapi
5/min 限流在进程内耗尽；user_id 从插入结果读取，禁止硬编码。
"""

import pytest


def _make_user(client, test_db):
    """创建测试用户并返回 (Bearer token, user_id)"""
    from app.core.auth import create_access_token

    cursor = test_db.execute(
        "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
        "VALUES (?, ?, ?, 0, 'private')",
        ("test_pref_user", "test-hash", "test_pref_user@example.com"),
    )
    test_db.commit()
    user_id = cursor.lastrowid
    token = create_access_token({"user_id": user_id, "type": "access"})
    return token, user_id


def test_get_recruitment_pref_returns_windows_and_pace(client, test_db):
    token, user_id = _make_user(client, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
        "VALUES (?, 2027, 'autumn', 30, 'hard')",
        (user_id,),
    )
    test_db.commit()
    resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pace"] == "hard"
    assert len(data["windows"]) == 4
    assert data["windows"][0]["name"] == "暑期实习"
    assert "current_window" in data
    assert "next_window" in data
    assert "urgency" in data


def test_get_recruitment_pref_defaults_when_unset(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["graduation_year"] is None
    assert data["batch"] == ""
    assert data["windows"] == []
    assert data["urgency"] == pytest.approx(0.2)
    assert data["pace"] == "standard"
    assert data["current_window"] is None
    assert data["next_window"] is None
    assert data["daily_capacity"] == 30


def test_put_recruitment_pref_validates_batch(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "not-a-batch", "daily_capacity": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_rejects_bad_pace(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "autumn", "daily_capacity": 30, "pace": "insane"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_rejects_year_out_of_range(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 1999, "batch": "autumn", "daily_capacity": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_rejects_non_numeric_year(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": "abc", "batch": "autumn", "daily_capacity": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_rejects_bad_capacity(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "autumn", "daily_capacity": 9999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_saves(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "daily", "daily_capacity": 25, "pace": "easy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "windows" in body
    assert "current_window" in body
    assert "urgency" in body
    get_resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = get_resp.json()
    assert data["batch"] == "daily"
    assert data["daily_capacity"] == 25
    assert data["pace"] == "easy"

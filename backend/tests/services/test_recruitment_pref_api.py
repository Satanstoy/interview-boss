"""
招聘偏好 API 测试 — GET/PUT /api/profile/recruitment

用户创建与 token 签发复用 repo 既有模式（test_authz_unification.py 同款：
直插 users 表 + create_access_token），避免 /api/auth/register 的 slowapi
5/min 限流在进程内耗尽；user_id 从插入结果读取，禁止硬编码。
"""


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


def test_get_recruitment_pref_returns_urgency(client, test_db):
    token, user_id = _make_user(client, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity) "
        "VALUES (?, ?, ?, ?)",
        (user_id, 2027, "autumn", 30),
    )
    test_db.commit()
    resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch"] == "autumn"
    assert data["graduation_year"] == 2027
    assert data["daily_capacity"] == 30
    assert "urgency" in data
    assert "milestones" in data
    assert len(data["milestones"]) == 3


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
    assert data["urgency"] == 0
    assert data["daily_capacity"] == 30


def test_put_recruitment_pref_validates_batch(client, test_db):
    token, _ = _make_user(client, test_db)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "not-a-batch", "daily_capacity": 30},
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
        json={"graduation_year": 2027, "batch": "daily", "daily_capacity": 25},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "milestones" in body
    assert "urgency" in body
    get_resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = get_resp.json()
    assert data["batch"] == "daily"
    assert data["daily_capacity"] == 25
    assert data["urgency"] == 0  # daily 无里程碑

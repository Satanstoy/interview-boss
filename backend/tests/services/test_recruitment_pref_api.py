"""
招聘偏好 API 测试 — GET/PUT /api/profile/recruitment

注册走 routers/auth.py 的 /api/auth/register 接口，使用明显的测试占位凭证；
user_id 从注册响应读取（注册用户不一定是 id 1，禁止硬编码）。
"""


def _make_user(client):
    """按 routers/auth.py 注册接口创建测试用户，返回 (token, user_id)"""
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "test_pref_user",
            "password": "TEST_PASSWORD_PLACEHOLDER_2026",
            "email": "test_pref_user@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["token"], data["user"]["id"]


def test_get_recruitment_pref_returns_urgency(client, test_db):
    token, user_id = _make_user(client)
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


def test_get_recruitment_pref_defaults_when_unset(client):
    token, _ = _make_user(client)
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


def test_put_recruitment_pref_validates_batch(client):
    token, _ = _make_user(client)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "not-a-batch", "daily_capacity": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


def test_put_recruitment_pref_saves(client):
    token, _ = _make_user(client)
    resp = client.put(
        "/api/profile/recruitment",
        json={"graduation_year": 2027, "batch": "daily", "daily_capacity": 25},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    get_resp = client.get(
        "/api/profile/recruitment",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = get_resp.json()
    assert data["batch"] == "daily"
    assert data["daily_capacity"] == 25
    assert data["urgency"] == 0  # daily 无里程碑

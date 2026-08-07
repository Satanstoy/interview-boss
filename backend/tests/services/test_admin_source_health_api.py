"""admin_source_health API 测试：重复组列表 / 合并。

admin 身份用 Bearer token（同 test_admin_quality_api.py 模式）。
只处理公共面经，私有面经不展示、不合并。
"""

import pytest


def _admin_headers(user_id=1, is_admin=True):
    from app.core.auth import create_access_token

    token = create_access_token({"user_id": user_id, "type": "access", "is_admin": is_admin})
    return {"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"}


def _ensure_admin_user(test_db, user_id=1):
    test_db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,))
    test_db.commit()


def _insert_user(conn, user_id):
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, email, password_hash) "
        "VALUES (?, ?, ?, 'x')",
        (user_id, f"user{user_id}", f"u{user_id}@test.com"),
    )


def _insert_interview(conn, url, sig, owner_id=None):
    if owner_id is not None:
        _insert_user(conn, owner_id)
    conn.execute(
        "INSERT INTO interview (url, url_signature, company, round, owner_id, status) "
        "VALUES (?, ?, '测试公司', '一面', ?, 'approved')",
        (url, sig, owner_id),
    )


# ── GET /duplicate-groups ──


def test_list_requires_admin(client, test_db):
    resp = client.get("/api/admin/source-health/duplicate-groups")
    assert resp.status_code == 401


def test_list_returns_duplicate_groups(client, test_db):
    _ensure_admin_user(test_db)
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    resp = client.get(
        "/api/admin/source-health/duplicate-groups", headers=_admin_headers(user_id=1)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["signature"] == "nc:1"
    assert data[0]["count"] == 2
    assert data[0]["keep_id"] == 1
    assert len(data[0]["records"]) == 2


def test_list_excludes_private(client, test_db):
    _ensure_admin_user(test_db)
    _insert_interview(test_db, "http://p.com/x?a=1", "nc:2", owner_id=99)
    _insert_interview(test_db, "https://p.com/x?a=2", "nc:2", owner_id=99)
    resp = client.get(
        "/api/admin/source-health/duplicate-groups", headers=_admin_headers(user_id=1)
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_jd_table(client, test_db):
    _ensure_admin_user(test_db)
    test_db.execute(
        "INSERT INTO jd (url, url_signature, owner_id, status) VALUES "
        "('http://b.com/j', 'generic:b.com/j', NULL, 'approved'),"
        "('http://b.com/j?p=2', 'generic:b.com/j', NULL, 'approved')"
    )
    test_db.commit()
    resp = client.get(
        "/api/admin/source-health/duplicate-groups?table=jd", headers=_admin_headers(user_id=1)
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["signature"] == "generic:b.com/j"


# ── POST /duplicate-groups/merge ──


def test_merge_requires_admin(client, test_db):
    resp = client.post(
        "/api/admin/source-health/duplicate-groups/merge",
        json={"signature": "nc:1", "table": "interview", "dry_run": False},
    )
    assert resp.status_code == 401


def test_merge_executes(client, test_db):
    _ensure_admin_user(test_db)
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    resp = client.post(
        "/api/admin/source-health/duplicate-groups/merge",
        headers=_admin_headers(user_id=1),
        json={"signature": "nc:1", "table": "interview", "dry_run": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged_count"] == 1
    assert data["keep_id"] == 1
    # drop 软删，keep 保留
    assert test_db.execute("SELECT deleted_at FROM interview WHERE id = 2").fetchone()[0] is not None
    assert test_db.execute("SELECT deleted_at FROM interview WHERE id = 1").fetchone()[0] is None


def test_merge_dry_run_no_change(client, test_db):
    _ensure_admin_user(test_db)
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    _insert_interview(test_db, "https://a.com/x?a=2", "nc:1")
    resp = client.post(
        "/api/admin/source-health/duplicate-groups/merge",
        headers=_admin_headers(user_id=1),
        json={"signature": "nc:1", "table": "interview", "dry_run": True},
    )
    assert resp.status_code == 200
    assert resp.json()["dry_run"] is True
    assert test_db.execute("SELECT COUNT(*) FROM interview WHERE deleted_at IS NULL").fetchone()[0] == 2


def test_merge_empty_signature_400(client, test_db):
    _ensure_admin_user(test_db)
    resp = client.post(
        "/api/admin/source-health/duplicate-groups/merge",
        headers=_admin_headers(user_id=1),
        json={"signature": "", "table": "interview", "dry_run": False},
    )
    assert resp.status_code == 400


def test_merge_already_merged_404(client, test_db):
    _ensure_admin_user(test_db)
    _insert_interview(test_db, "http://a.com/x?a=1", "nc:1")
    resp = client.post(
        "/api/admin/source-health/duplicate-groups/merge",
        headers=_admin_headers(user_id=1),
        json={"signature": "nc:999", "table": "interview", "dry_run": False},
    )
    assert resp.status_code == 404

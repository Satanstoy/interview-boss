"""AC-002 / UR-002：面经列表真实分页与排序（F02 修复）。

契约（contracts.md §4.5）：

- sort 仅 ``created_at_desc``/``created_at_asc``；SQL 稳定次序
  ``created_at DESC, id DESC``（或对应 ASC），同时间戳按 id 稳定；
- ``total`` 与 items 必须同一授权/筛选口径；筛选排序都在 SQL LIMIT 之前；
- 默认 page_size=20，范围 1..100；scope 仅 all/public/mine，授权先于筛选；
- 不得只取前 100 条再前端排序。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations


def _db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    run_migrations(conn)
    for uid, is_admin in ((101, 0), (102, 0), (201, 1)):
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin) VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", is_admin),
        )
    conn.commit()
    return conn


def _seed_interviews(conn, count=121):
    """121 条同时间戳的授权面经 + U2 私人 + P2 记录。"""

    for uid, is_admin in ((101, 0), (102, 0), (201, 1)):
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", is_admin),
        )

    for i in range(count):
        conn.execute(
            "INSERT INTO interview (id, url, company, round, questions_list, owner_id, "
            "status, job_position, season, created_at) "
            "VALUES (?, ?, '公司', '一面', '1.x', ?, 'approved', 'P1', '2026春招', "
            "'2026-09-29 10:00:00')",
            (1000 + i, f"https://a.example.com/{1000 + i}", 101),
        )
    # U2 私人面经（U1 不可见）
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, "
        "status, job_position, season, created_at) "
        "VALUES (2000, 'https://b.example.com/2000', 'U2私有', '一面', '1.y', 102, "
        "'approved', 'P1', '2026春招', '2026-09-29 10:00:00')"
    )
    # P2 记录（岗位筛选排除）
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, "
        "status, job_position, season, created_at) "
        "VALUES (2001, 'https://b.example.com/2001', 'P2岗', '一面', '1.z', 101, "
        "'approved', 'P2', '2026春招', '2026-09-29 10:00:00')"
    )
    conn.commit()


@pytest.fixture
def api(client):
    """复用 conftest 的隔离 client，注入 U1 身份。"""

    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "id": 101,
        "is_admin": 0,
        "username": "u101",
    }
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_page_one_has_latest_and_full_total(api, test_db):
    _seed_interviews(test_db)
    resp = api.get(
        "/api/data/interview?file_type=interview&page=1&page_size=20&sort=created_at_desc&position_id=P1"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 121, "total 必须是完整授权范围，而不是本页数量"
    assert len(body["items"]) == 20
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids, reverse=True), "同时间戳必须按 id 稳定排序"
    # 不得出现 U2 私人或 P2 记录
    assert 2000 not in ids and 2001 not in ids


def test_second_page_does_not_duplicate_or_skip(api, test_db):
    _seed_interviews(test_db)
    page1 = api.get(
        "/api/data/interview?file_type=interview&page=1&page_size=20&sort=created_at_desc&position_id=P1"
    ).json()
    page2 = api.get(
        "/api/data/interview?file_type=interview&page=2&page_size=20&sort=created_at_desc&position_id=P1"
    ).json()
    ids1 = [item["id"] for item in page1["items"]]
    ids2 = [item["id"] for item in page2["items"]]
    assert not set(ids1) & set(ids2)
    assert page1["total"] == page2["total"] == 121
    # 覆盖 121 条：第 7 页应有 1 条
    page7 = api.get(
        "/api/data/interview?file_type=interview&page=7&page_size=20&sort=created_at_desc&position_id=P1"
    ).json()
    assert len(page7["items"]) == 1


def test_sort_asc_returns_oldest_first(api, test_db):
    _seed_interviews(test_db, count=5)
    body = api.get(
        "/api/data/interview?file_type=interview&page=1&page_size=20&sort=created_at_asc&position_id=P1"
    ).json()
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids)


def test_scope_filters_are_server_side(api, test_db):
    _seed_interviews(test_db, count=5)
    mine = api.get(
        "/api/data/interview?file_type=interview&page=1&page_size=20&scope=mine&position_id=P1"
    ).json()
    assert mine["total"] == 5
    assert all(item["owner_id"] == 101 for item in mine["items"])

    public = api.get(
        "/api/data/interview?file_type=interview&page=1&page_size=20&scope=public&position_id=P1"
    ).json()
    assert public["total"] == 0


def test_page_size_bounds_and_default(api, test_db):
    _seed_interviews(test_db, count=30)
    default = api.get(
        "/api/data/interview?file_type=interview&sort=created_at_desc&position_id=P1"
    ).json()
    assert default["page_size"] == 20
    assert len(default["items"]) == 20
    bounded = api.get(
        "/api/data/interview?file_type=interview&page_size=1000&position_id=P1"
    ).json()
    assert bounded["page_size"] <= 100


def test_location_endpoint_returns_page_under_same_ordering(api, test_db):
    _seed_interviews(test_db, count=121)
    # R09：location 返回岗位 ID（前端 switchPositionById 需要数字）+ 名称供展示
    test_db.execute("INSERT INTO job_positions (id, name) VALUES (1, 'P1')")
    test_db.commit()
    target_id = 1000 + 60  # 排序后位于中间
    resp = api.get(
        f"/api/data/interview/{target_id}/location?sort=created_at_desc&position_id=P1"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["interview_id"] == target_id
    assert body["page"] == (60 // 20) + 1
    assert body["position_id"] == 1, "必须返回岗位 ID 而不是名称"
    assert body["position_name"] == "P1"


def test_location_for_unauthorized_target_is_404(api, test_db):
    _seed_interviews(test_db, count=5)
    resp = api.get("/api/data/interview/2000/location?sort=created_at_desc&position_id=P1")
    assert resp.status_code == 404, "不得透露他人记录的存在性"

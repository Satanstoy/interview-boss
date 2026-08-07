"""admin 通用更新接口的 URL 协议校验。

回归场景：update_generic_data 白名单允许编辑 interview.url /
questions_detail.url / jd.url，此前无协议校验，管理员可把面经链接
改成 internal:// 等无效值（与 submit 入口同源的"来源错误"风险）。
"""

import pytest


@pytest.fixture
def admin_client(client, test_db):
    """admin 身份 + 一条 interview/jd 记录（共用 /api/data/update 校验入口）。"""
    from app.asgi import app
    from app.core.auth import get_current_user, get_admin_user

    ADMIN = {"id": 1, "is_admin": 1, "username": "admin"}
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[get_admin_user] = lambda: ADMIN

    test_db.execute(
        "INSERT INTO interview (url, company, round, owner_id, status) "
        "VALUES ('https://x.com/a', '测试公司', '一面', NULL, 'approved')"
    )
    test_db.execute(
        "INSERT INTO jd (url, owner_id, status) VALUES ('https://x.com/jd', NULL, 'approved')"
    )
    test_db.commit()
    yield client

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_admin_user, None)


def _update(client, table_name, record_id, update_data):
    return client.put(
        "/api/data/update",
        headers={"X-Requested-With": "XMLHttpRequest"},
        json={
            "table_name": table_name,
            "record_id": record_id,
            "update_data": update_data,
        },
    )


def test_update_interview_url_rejects_internal(admin_client):
    """interview.url 改为 internal:// → 400"""
    resp = _update(admin_client, "interview", 1, {"url": "internal://xxx"})
    assert resp.status_code == 400
    assert "链接" in resp.json()["detail"]


def test_update_questions_detail_url_rejects_internal(admin_client):
    """questions_detail.url 改为 internal:// → 400"""
    resp = _update(
        admin_client, "questions_detail", 1, {"url": "internal://xxx"}
    )
    assert resp.status_code == 400


def test_update_jd_url_rejects_random_text(admin_client):
    """jd.url 改为无协议文本 → 400"""
    resp = _update(admin_client, "jd", 1, {"url": "not-a-url"})
    assert resp.status_code == 400


def test_update_interview_url_accepts_https(admin_client):
    """interview.url 改为合法 https → 通过校验"""
    resp = _update(
        admin_client, "interview", 1, {"url": "https://x.com/b"}
    )
    assert resp.status_code == 200


def test_update_question_bank_url_field_still_blocked(admin_client):
    """question_bank 不允许直接改 url 字段（白名单不变，回归确认）"""
    resp = _update(admin_client, "question_bank", 1, {"url": "https://x.com"})
    assert resp.status_code == 400
    assert "不允许更新字段" in resp.json()["detail"]

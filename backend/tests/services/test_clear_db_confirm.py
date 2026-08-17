"""Test clear_db confirmation mechanism."""

import pytest

ADMIN = {"id": 1, "is_admin": 1, "username": "admin"}
CSRF_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _override_admin(app):
    from app.core.auth import get_current_user, get_admin_user

    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[get_admin_user] = lambda: ADMIN


def _clear_overrides(app):
    from app.core.auth import get_current_user, get_admin_user

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_admin_user, None)


def test_preview_returns_stats_and_token(client, test_db):
    """preview 接口返回各表行数和 confirm_token"""
    from app.asgi import app

    _override_admin(app)
    try:
        response = client.post("/api/analytics/clear-db/preview", headers=CSRF_HEADERS)
    finally:
        _clear_overrides(app)

    assert response.status_code == 200
    data = response.json()
    assert "stats" in data
    assert "confirm_token" in data
    assert isinstance(data["stats"], dict)
    assert len(data["confirm_token"]) >= 64


def test_preview_requires_admin(client, test_db):
    """preview 接口需要管理员权限"""
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_admin": 0}
    try:
        response = client.post("/api/analytics/clear-db/preview", headers=CSRF_HEADERS)
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 403


def test_clear_without_token_returns_400(client, test_db):
    """无 token 调用 clear_db 返回 400"""
    from app.asgi import app

    _override_admin(app)
    try:
        response = client.post("/api/clear-db", headers=CSRF_HEADERS)
    finally:
        _clear_overrides(app)

    assert response.status_code == 400


def test_clear_with_valid_token_succeeds(client, test_db):
    """正确 token 清空成功"""
    from app.asgi import app

    _override_admin(app)
    try:
        preview = client.post("/api/analytics/clear-db/preview", headers=CSRF_HEADERS)
        assert preview.status_code == 200
        token = preview.json()["confirm_token"]

        response = client.post(
            f"/api/clear-db?confirm_token={token}", headers=CSRF_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
    finally:
        _clear_overrides(app)


def test_clear_with_short_token_returns_400(client, test_db):
    """过短的 token 返回 400"""
    from app.asgi import app

    _override_admin(app)
    try:
        response = client.post(
            "/api/clear-db?confirm_token=short", headers=CSRF_HEADERS
        )
        assert response.status_code == 400
    finally:
        _clear_overrides(app)

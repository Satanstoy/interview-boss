"""全局 LLM 测试连接端点。"""
import pytest
from unittest.mock import patch

from app.core.auth import create_access_token
from app.db.connection import get_db_connection


@pytest.fixture
def seed_admin_users(test_db):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM users")
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, bank_mode) "
            "VALUES (1, 'admin', 'hash', 1, 'public')"
        )
        conn.execute(
            "INSERT INTO users (id, username, password_hash, is_admin, bank_mode) "
            "VALUES (2, 'user', 'hash', 0, 'public')"
        )
        conn.commit()


def _admin_headers():
    token = create_access_token({"user_id": 1, "type": "access"})
    return {"Authorization": f"Bearer {token}"}


def _user_headers():
    token = create_access_token({"user_id": 2, "type": "access"})
    return {"Authorization": f"Bearer {token}"}


def test_test_global_llm_requires_auth(client, test_db):
    resp = client.post("/api/profile/llm/test-global", json={})
    assert resp.status_code == 401


def test_test_global_llm_requires_admin(client, test_db, seed_admin_users):
    resp = client.post("/api/profile/llm/test-global", json={}, headers=_user_headers())
    assert resp.status_code == 403


def test_test_global_llm_connected(client, test_db, seed_admin_users):
    with patch(
        "app.services.llm.check_global_llm_status",
        return_value={"configured": True, "connected": True, "error": None, "model": "gpt-4o"},
    ):
        resp = client.post("/api/profile/llm/test-global", json={}, headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["connected"] is True
    assert resp.json()["model"] == "gpt-4o"


def test_test_global_llm_not_configured(client, test_db, seed_admin_users):
    with patch(
        "app.services.llm.check_global_llm_status",
        return_value={"configured": False, "connected": False, "error": None, "model": None},
    ):
        resp = client.post("/api/profile/llm/test-global", json={}, headers=_admin_headers())
    assert resp.status_code == 200
    assert resp.json()["configured"] is False

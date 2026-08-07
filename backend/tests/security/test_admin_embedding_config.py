"""管理员 embedding 配置端点：权限、校验、掩码、热加载。"""
import pytest
from unittest.mock import patch

from app.core.auth import create_access_token
from app.db.connection import get_db_connection


@pytest.fixture
def seed_admin_users(test_db):
    """确保已知 id 的 admin（1）与普通用户（2）存在，避免依赖 seed 自增 id。"""
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


def _admin_headers(admin_user_id=1):
    token = create_access_token({"user_id": admin_user_id, "type": "access"})
    return {"Authorization": f"Bearer {token}"}


def _user_headers(user_id=2):
    token = create_access_token({"user_id": user_id, "type": "access"})
    return {"Authorization": f"Bearer {token}"}


def test_embedding_config_get_requires_auth(client, test_db):
    resp = client.get("/api/profile/embedding")
    assert resp.status_code == 401


def test_embedding_config_requires_admin_user(client, test_db, seed_admin_users):
    resp = client.get("/api/profile/embedding", headers=_user_headers())
    assert resp.status_code == 403


def test_embedding_config_roundtrip_with_mask(client, test_db, seed_admin_users):
    resp = client.put(
        "/api/profile/embedding",
        json={
            "backend": "siliconflow",
            "api_key": "sk-secret-1234",
            "api_model": "BAAI/bge-m3",
            "dimension": 1024,
        },
        headers=_admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    resp = client.get("/api/profile/embedding", headers=_admin_headers())
    data = resp.json()["settings"]
    assert data["backend"] == "siliconflow"
    assert data["api_model"] == "BAAI/bge-m3"
    assert data["dimension"] == "1024"
    assert data["api_key_set"] is True
    assert "sk-secret" not in data["api_key"]
    assert data["api_key"].startswith("sk-")


def test_embedding_config_rejects_bad_backend(client, test_db, seed_admin_users):
    resp = client.put(
        "/api/profile/embedding",
        json={"backend": "bogus", "api_model": "x"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


def test_embedding_config_siliconflow_requires_model(client, test_db, seed_admin_users):
    resp = client.put(
        "/api/profile/embedding",
        json={"backend": "siliconflow"},
        headers=_admin_headers(),
    )
    assert resp.status_code == 400


def test_embedding_config_put_calls_reload(client, test_db, seed_admin_users):
    with patch("app.services.embedding_service.reload_embedding_config") as mock_reload:
        resp = client.put(
            "/api/profile/embedding",
            json={"backend": "onnx", "dimension": 512},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        mock_reload.assert_called_once()


def test_embedding_config_put_preserves_api_key_when_blank(client, test_db, seed_admin_users):
    with patch("app.services.embedding_service.reload_embedding_config"):
        client.put(
            "/api/profile/embedding",
            json={"backend": "siliconflow", "api_key": "sk-secret-1234", "api_model": "BAAI/bge-m3", "dimension": 1024},
            headers=_admin_headers(),
        )
        # 第二次保存不带 api_key → 保留旧 key
        resp2 = client.put(
            "/api/profile/embedding",
            json={"backend": "siliconflow", "api_model": "BAAI/bge-m3", "dimension": 1024},
            headers=_admin_headers(),
        )
        assert resp2.status_code == 200

    resp = client.get("/api/profile/embedding", headers=_admin_headers())
    assert resp.json()["settings"]["api_key_set"] is True

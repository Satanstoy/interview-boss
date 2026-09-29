"""AC-018 / UR-018：私人正文隔离与运维白名单。

契约（contracts.md §4.2）：

- 非本人访问根任务正文一律 404（管理员也不例外）；
- 运维端点只返回白名单字段：不返回 payload、题干、公司、来源 URL、文件名、
  原始错误；直接检查序列化全文中 marker 不存在；
- 私有 HTTP 错误不回显原稿。
"""

from __future__ import annotations

import json

import pytest

MARKER = "SECRET-MARKER-9f3a2b7c"


@pytest.fixture
def _no_dispatch():
    from unittest.mock import AsyncMock, patch

    with patch("app.worker.enqueue_submit_import_job", new=AsyncMock()) as enq:
        yield enq


def _login(client, user):
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _seed_users(test_db):
    for uid in (101, 102, 201):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash, is_admin) "
            "VALUES (?, ?, 'x', ?)",
            (uid, f"u{uid}", 1 if uid == 201 else 0),
        )
    test_db.commit()


def _create_private_root(client, test_db):
    _seed_users(test_db)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post(
            "/api/submit-jobs",
            headers={"Idempotency-Key": "privacy-1", "X-Requested-With": "XMLHttpRequest"},
            data={"text": f"{MARKER} 的私人面经原文", "target": "private"},
        )
        assert resp.status_code == 202, resp.text
        return resp.json()


def test_non_owner_cannot_read_root_snapshot(client, monkeypatch, _no_dispatch, test_db):
    monkeypatch.setattr("app.core.config.UPLOAD_RECOVERY_V2", True)
    created = _create_private_root(client, test_db)

    for viewer in (
        {"id": 102, "is_admin": 0, "username": "u102"},
        {"id": 201, "is_admin": 1, "username": "u201"},
    ):
        for _ in _login(client, viewer):
            resp = client.get(f"/api/upload-imports/{created['import_id']}")
            assert resp.status_code == 404
            assert MARKER not in resp.text
            # by-key 同样不可越权
            resp_key = client.get("/api/upload-imports/by-key/privacy-1")
            assert resp_key.status_code == 404
            assert MARKER not in resp_key.text


def test_owner_can_read_own_snapshot_without_leaking_to_others(
    client, monkeypatch, _no_dispatch, test_db
):
    monkeypatch.setattr("app.core.config.UPLOAD_RECOVERY_V2", True)
    created = _create_private_root(client, test_db)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.get(f"/api/upload-imports/{created['import_id']}")
        assert resp.status_code == 200
        assert resp.json()["import_id"] == created["import_id"]


def test_admin_operations_endpoint_uses_allowlist(client, monkeypatch, _no_dispatch, test_db):
    monkeypatch.setattr("app.core.config.UPLOAD_RECOVERY_V2", True)
    created = _create_private_root(client, test_db)

    allowed_keys = {
        "import_id",
        "job_type",
        "scope",
        "status",
        "stage",
        "attempt_no",
        "duration_ms",
        "error_code",
        "next_retry_at",
        "credential_scope",
        "provider",
        "model",
        "created_at",
        "updated_at",
    }
    for _ in _login(client, {"id": 201, "is_admin": 1, "username": "u201"}):
        resp = client.get("/api/admin/upload-operations")
        assert resp.status_code == 200
        body = resp.text
        assert MARKER not in body, "运维端点不得包含私人原文"
        for item in resp.json()["items"]:
            assert set(item) <= allowed_keys, f"越权字段: {set(item) - allowed_keys}"


def test_admin_operations_endpoint_rejects_non_admin(client, _no_dispatch, test_db):
    _seed_users(test_db)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.get("/api/admin/upload-operations")
        assert resp.status_code in (401, 403)


def test_error_responses_never_echo_raw_text(client, monkeypatch, _no_dispatch, test_db):
    monkeypatch.setattr("app.core.config.UPLOAD_RECOVERY_V2", True)
    _seed_users(test_db)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        # 非法 target 的 400 响应不得回显提交内容
        resp = client.post(
            "/api/submit-jobs",
            headers={"Idempotency-Key": "privacy-err", "X-Requested-With": "XMLHttpRequest"},
            data={"text": f"{MARKER} 原文", "target": "public"},
        )
        assert resp.status_code == 400
        assert MARKER not in resp.text
        assert test_db.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0

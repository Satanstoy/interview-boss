"""上传根任务恢复 API（contracts §4.1 ``POST /api/upload-imports/{id}/retry``）。

- 本人可恢复：返回根任务快照与 ``created_attempt`` 布尔；并发恢复不创建第二个 attempt。
- 非本人一律 404（含管理员），不泄露他人任务存在性（AC-018）。
- 原文已删除：409 SOURCE_DELETED，不复活删除内容（AC-025）。
- 无可靠历史的 job：409 LEGACY_MAPPING_AMBIGUOUS。
"""

from __future__ import annotations

import sqlite3

from unittest.mock import patch

import pytest


@pytest.fixture
def test_db_with_import(test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (102, 'u102', 'x')"
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (201, 'u201', 'x')"
    )
    test_db.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status) "
        "VALUES ('imp-1', 101, 'k1', 'h1', 'private', 'interview', 'v1', 'partial_failed')"
    )
    test_db.commit()
    return test_db


def _login(client, user):
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_owner_retry_returns_snapshot_and_creates_attempt(client, test_db_with_import):
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post("/api/upload-imports/imp-1/retry", json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["import_id"] == "imp-1"
        assert body["created_attempt"] is True
        assert body["attempt_no"] == 1
        assert body["status_url"].endswith("imp-1")
    rows = test_db_with_import.execute(
        "SELECT COUNT(*) FROM upload_attempts WHERE import_id = 'imp-1'"
    ).fetchone()[0]
    assert rows == 1


def test_second_retry_reuses_active_attempt(client, test_db_with_import):
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        first = client.post("/api/upload-imports/imp-1/retry", json={}).json()
        second = client.post("/api/upload-imports/imp-1/retry", json={}).json()
        assert second["created_attempt"] is False
        assert second["attempt_no"] == first["attempt_no"]
    rows = test_db_with_import.execute(
        "SELECT COUNT(*) FROM upload_attempts WHERE import_id = 'imp-1'"
    ).fetchone()[0]
    assert rows == 1


def test_non_owner_and_admin_retry_are_404(client, test_db_with_import):
    for _ in _login(client, {"id": 102, "is_admin": 0, "username": "u102"}):
        resp = client.post("/api/upload-imports/imp-1/retry", json={})
        assert resp.status_code == 404
    for _ in _login(client, {"id": 201, "is_admin": 1, "username": "u201"}):
        resp = client.post("/api/upload-imports/imp-1/retry", json={})
        assert resp.status_code == 404, "管理员也不能读他人私人任务（AC-018）"
    rows = test_db_with_import.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0]
    assert rows == 0


def test_retry_unknown_import_is_404(client, test_db_with_import):
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post("/api/upload-imports/does-not-exist/retry", json={})
        assert resp.status_code == 404


def test_retry_deleted_source_returns_409(client, test_db_with_import):
    test_db_with_import.execute(
        "INSERT INTO interview (id, url, company, questions_list, owner_id, status, "
        "deleted_at, job_position) "
        "VALUES (700, 'https://src.example.com/1', 'S', '1.题', 101, 'approved', "
        "CURRENT_TIMESTAMP, '后端')"
    )
    test_db_with_import.execute(
        "UPDATE upload_imports SET interview_id = 700 WHERE id = 'imp-1'"
    )
    test_db_with_import.commit()
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post("/api/upload-imports/imp-1/retry", json={})
        assert resp.status_code == 409, resp.text
        assert "SOURCE_DELETED" in resp.text


def test_retry_ambiguous_legacy_job_returns_409(client, test_db_with_import):
    import app.routers.upload_imports as upload_imports_module
    from app.services.upload_lifecycle import UploadRestoreError

    def _fail(*args, **kwargs):
        raise UploadRestoreError("LEGACY_MAPPING_AMBIGUOUS", "该历史任务没有可解析的业务根任务")

    with patch.object(upload_imports_module, "restore_upload", side_effect=_fail):
        for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
            resp = client.post("/api/upload-imports/imp-1/retry", json={})
            assert resp.status_code == 409, resp.text
            assert "LEGACY_MAPPING_AMBIGUOUS" in resp.text
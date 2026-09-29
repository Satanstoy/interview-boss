"""接受入口 API（AC-003/021/022 的接口面）。

- `POST /api/submit-jobs`（v2 开关开启时）返回稳定 import_id/status_url/幂等键；
  同键同 hash 复用，不同 hash 409。
- 非法 target 400、超限 413，且不产生幽灵 job。
- `GET /api/upload-imports/by-key/{key}` 只能查到本人的任务。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def _no_dispatch():
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


def _v2_on(monkeypatch):
    monkeypatch.setattr("app.core.config.UPLOAD_RECOVERY_V2", True)


def _post(client, *, text="面经：解释 TCP 三次握手", target="private", key="k-1", files=None):
    data = {"text": text, "target": target, "url": "", "season": "2026春招"}
    if files:
        data["url"] = ""
    return client.post(
        "/api/submit-jobs",
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Idempotency-Key": key,
        },
        data=data,
        files=files,
    )


@pytest.mark.parametrize(
    "entry_user,is_admin,target",
    [
        ({"id": 101, "is_admin": 0, "username": "u101"}, 0, "private"),
        ({"id": 101, "is_admin": 0, "username": "u101"}, 0, "share"),
        ({"id": 201, "is_admin": 1, "username": "u201"}, 1, "private"),
        ({"id": 201, "is_admin": 1, "username": "u201"}, 1, "share"),
    ],
)
def test_submit_jobs_v2_returns_stable_import_id(
    client, monkeypatch, _no_dispatch, entry_user, is_admin, target, test_db
):
    for uid in (101, 201):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    test_db.commit()
    _v2_on(monkeypatch)
    for login in _login(client, entry_user):
        resp = _post(client, target=target, key=f"k-{is_admin}-{target}")
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["import_id"]
        assert body["status_url"].endswith(body["import_id"])
        assert body["job_id"]
        assert body["idempotency_key"] == f"k-{is_admin}-{target}"
        # 同键重发：复用同一根任务
        again = _post(client, target=target, key=f"k-{is_admin}-{target}")
        assert again.status_code == 202
        assert again.json()["import_id"] == body["import_id"]
        assert again.json()["created"] is False


def test_submit_jobs_v2_conflict_on_same_key_different_content(
    client, monkeypatch, _no_dispatch, test_db
):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        first = _post(client, text="第一篇面经", key="same")
        assert first.status_code == 202
        conflict = _post(client, text="完全不同的第二篇面经", key="same")
        assert conflict.status_code == 409
        assert conflict.json()["detail"]


def test_by_key_returns_only_own_import(client, monkeypatch, _no_dispatch, test_db):
    for uid in (101, 102):
        test_db.execute(
            "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (uid, f"u{uid}"),
        )
    test_db.commit()
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        created = _post(client, key="mine-only").json()
    for _ in _login(client, {"id": 102, "is_admin": 0, "username": "u102"}):
        assert client.get("/api/upload-imports/by-key/mine-only").status_code == 404
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        found = client.get("/api/upload-imports/by-key/mine-only")
        assert found.status_code == 200
        assert found.json()["import_id"] == created["import_id"]


def test_invalid_target_returns_400_without_ghost_job(client, monkeypatch, _no_dispatch, test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    _v2_on(monkeypatch)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = _post(client, target="public")
        assert resp.status_code == 400
    jobs = test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    assert jobs == 0
    assert test_db.execute("SELECT COUNT(*) FROM upload_imports").fetchone()[0] == 0


def test_oversize_file_returns_413_without_ghost_job(client, monkeypatch, _no_dispatch, test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    _v2_on(monkeypatch)
    monkeypatch.setattr("app.services.upload_lifecycle.MAX_FILE_SIZE", 64)
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post(
            "/api/submit-jobs",
            headers={"Idempotency-Key": "big-file", "X-Requested-With": "XMLHttpRequest"},
            data={"text": "x", "target": "private"},
            files=[("files", ("big.png", b"\x89PNG" + b"0" * 200, "image/png"))],
        )
        assert resp.status_code == 413
    assert test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_legacy_sse_entry_rejects_invalid_target(client, monkeypatch, test_db):
    test_db.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash) VALUES (101,'u101','x')"
    )
    test_db.commit()
    for _ in _login(client, {"id": 101, "is_admin": 0, "username": "u101"}):
        resp = client.post(
            "/api/submit-stream-v2",
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={"text": "面经正文", "target": "public"},
        )
        assert resp.status_code == 400
    assert test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

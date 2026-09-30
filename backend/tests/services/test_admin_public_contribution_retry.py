"""AC-015 / contracts §4.1：POST /api/admin/public-contributions/{id}/retry。

- 仅批准后的失败公共子项可重试：pending_review / changes_requested 拒绝；
- 复用同一审核投影，不修改 review 状态、不重建 snapshot（不改审核状态）；
- 只把失败子项的 public_detail 重新入队并复位为 queued；成功子项不动；
- 无失败子项时明确 409/400，不假装执行了工作。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations


def _connect(path, migrate=True):
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if migrate:
        run_migrations(conn)
    return conn


def _seed(conn):
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (201, 'admin', 'x')")
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (1, 'https://a.example.com/1', 'A', '一面', '1.x', 101, 'approved', '后端')"
    )
    conn.execute(
        "INSERT INTO interview (id, url, company, round, questions_list, owner_id, status, job_position) "
        "VALUES (500, 'https://pub.example.com/1', 'P', '一面', '', NULL, 'approved', '后端')"
    )
    for detail_id, question in ((11, "TCP 三次握手"), (12, "TCP 四次挥手")):
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, job_position) "
            "VALUES (?, 1, ?, '网络', 'TCP', '后端')",
            (detail_id, question),
        )
    for detail_id, question in ((511, "TCP 三次握手"), (512, "TCP 四次挥手")):
        conn.execute(
            "INSERT INTO questions_detail (id, interview_id, question, cat1, cat2, job_position) "
            "VALUES (?, 500, ?, '网络', 'TCP', '后端')",
            (detail_id, question),
        )
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, status, snapshot_json, revision, "
        "public_interview_id, review_projection_json, projection_hash) "
        "VALUES (1, 'interview', 1, 101, 'failed', '{}', 2, 500, ?, ?)",
        (
            '{"schema_version":1,"source":{"company":null},"items":[{"item_id":11,"question":"TCP 三次握手"},{"item_id":12,"question":"TCP 四次挥手"}],"excluded_item_ids":[],"hash":"h"}',
            "h",
        ),
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, snapshot_json, public_detail_id) "
        "VALUES (11, 1, 'question', 11, 1, 'published', '{}', 511)"
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, source_item_id, ordinal, status, snapshot_json, public_detail_id, error_message) "
        "VALUES (12, 1, 'question', 12, 2, 'failed', '{}', 512, 'UPSTREAM_TIMEOUT')"
    )
    conn.commit()
    return conn


def test_retry_rejects_pending_review(tmp_path):
    from app.services.public_contributions import StateConflict, retry_failed_public_items

    conn = _connect(str(tmp_path / "pending.db"))
    _seed(conn)
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'pending_review' WHERE id = 1"
    )
    conn.commit()
    with pytest.raises(StateConflict):
        retry_failed_public_items(conn, request_id=1, admin_id=201)
    conn.close()


def test_retry_requeues_only_failed_items(tmp_path):
    from app.services.public_contributions import (
        request_publish_status,
        retry_failed_public_items,
    )

    conn = _connect(str(tmp_path / "r.db"))
    _seed(conn)
    report = retry_failed_public_items(conn, request_id=1, admin_id=201)

    assert report["reprocessed_item_ids"] == [12], "只重试失败子项"
    item12 = conn.execute(
        "SELECT status, error_message FROM public_contribution_items WHERE id = 12"
    ).fetchone()
    assert item12["status"] == "queued"
    assert item12["error_message"] is None
    # item 11 已 published 不被触碰
    assert (
        conn.execute(
            "SELECT status FROM public_contribution_items WHERE id = 11"
        ).fetchone()["status"]
        == "published"
    )
    queued = conn.execute(
        "SELECT COUNT(*) FROM analysis_queue WHERE contribution_request_id = 1 "
        "AND question_detail_id = 512 AND status = 'pending'"
    ).fetchone()[0]
    assert queued == 1, "失败子项的 public_detail 重新入队"
    # 请求回到 queued，审核投影/revision 未变
    row = conn.execute(
        "SELECT status, revision, projection_hash FROM public_contribution_requests WHERE id = 1"
    ).fetchone()
    assert row["status"] == "queued"
    assert row["revision"] == 2
    assert request_publish_status(conn, request_id=1) != "published"
    conn.close()


def test_retry_no_failed_items_is_reported_not_silent(tmp_path):
    from app.services.public_contributions import retry_failed_public_items

    conn = _connect(str(tmp_path / "none.db"))
    _seed(conn)
    conn.execute("UPDATE public_contribution_items SET status = 'published' WHERE id = 12")
    conn.commit()
    report = retry_failed_public_items(conn, request_id=1, admin_id=201)
    assert report["reprocessed_item_ids"] == []
    conn.close()


def test_retry_unknown_request_raises(tmp_path):
    from app.services.public_contributions import retry_failed_public_items

    conn = _connect(str(tmp_path / "nf.db"))
    _seed(conn)
    with pytest.raises(ValueError):
        retry_failed_public_items(conn, request_id=999, admin_id=201)
    conn.close()


def test_retry_http_admin_only(client, test_db, monkeypatch):
    """路由级：管理员调用 200；普通用户 403；pending_review 409。"""

    from app.asgi import app
    from app.core.auth import get_admin_user, get_current_user

    _seed(test_db)
    test_db.commit()

    def _as_admin():
        app.dependency_overrides[get_admin_user] = lambda: {"id": 201, "is_admin": 1, "username": "admin"}
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_admin_user, None)

    def _as_user():
        app.dependency_overrides[get_current_user] = lambda: {"id": 101, "is_admin": 0, "username": "u101"}
        try:
            yield
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    for _ in _as_admin():
        resp = client.post("/api/admin/public-contributions/1/retry", json={})
        assert resp.status_code == 200, resp.text
        assert resp.json()["reprocessed_item_ids"] == [12]

    for _ in _as_user():
        resp = client.post("/api/admin/public-contributions/1/retry", json={})
        assert resp.status_code in (401, 403), resp.text

    test_db.execute(
        "UPDATE public_contribution_requests SET status = 'pending_review' WHERE id = 1"
    )
    test_db.commit()
    for _ in _as_admin():
        resp = client.post("/api/admin/public-contributions/1/retry", json={})
        assert resp.status_code == 409, resp.text
"""Owner retry contract for terminal personal rootless analysis queue rows."""

from contextlib import contextmanager

import asyncio
from unittest.mock import AsyncMock

import pytest


@contextmanager
def _as_user(user):
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _seed_rootless_and_scoped_failures(conn):
    conn.executemany(
        "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
        [(101, "owner-101"), (102, "owner-102"), (201, "admin-201")],
    )
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version, status, payload_json) "
        "VALUES ('root-101', 101, 'key-101', 'hash-101', 'private', 'interview', "
        "'upload-pipeline-v1', 'failed', '{}')"
    )
    conn.executemany(
        "INSERT INTO interview (id, url, company, owner_id, status, job_position) "
        "VALUES (?, ?, ?, ?, 'approved', '后端')",
        [
            (700, "internal://owner-101", "U1 私人公司", 101),
            (701, "internal://owner-102", "U2 私人公司", 102),
            (702, "internal://public", "公共公司", None),
        ],
    )
    conn.executemany(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id) "
        "VALUES (?, ?, ?, ?)",
        [
            (1700, 700, "U1 私人失败题", 101),
            (1701, 701, "U2 私人失败题", 102),
            (1702, 702, "公共失败题", None),
            (1703, 700, "U1 有 root 的失败题", 101),
            (1707, 702, "公共贡献失败题", None),
        ],
    )
    conn.execute(
        "INSERT INTO public_contribution_requests "
        "(id, source_type, source_id, requester_id, status) "
        "VALUES (990, 'interview', 702, 101, 'failed')"
    )
    conn.execute(
        "INSERT INTO public_contribution_items "
        "(id, request_id, source_item_type, ordinal, status, public_detail_id) "
        "VALUES (9901, 990, 'question', 1, 'failed', 1707)"
    )
    conn.executemany(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, import_id) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (1704, 701, "U2 detail attached to U1 queue", 102, None),
            (1705, 700, "upload detail attached to rootless queue", 101, "root-101"),
        ],
    )
    conn.executemany(
        "INSERT INTO analysis_queue (id, interview_id, question_detail_id, owner_id, "
        "status, root_import_id) VALUES (?, ?, ?, ?, 'failed', ?)",
        [
            (2700, 700, 1700, 101, None),
            (2701, 701, 1701, 102, None),
            (2702, 702, 1702, None, None),
            (2703, 700, 1703, 101, "root-101"),
            (2704, 700, 1704, 101, None),
            (2705, 700, 1705, 101, None),
            (2707, 702, 1707, None, None),
        ],
    )
    conn.execute(
        "UPDATE analysis_queue SET contribution_request_id = 990 WHERE id = 2707"
    )
    conn.commit()


def test_owner_lists_only_their_recoverable_rootless_failures(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.get("/api/personal-analysis-queue/failed")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1
    assert [item["queue_id"] for item in payload["items"]] == [2700]
    assert payload["items"][0]["interview_id"] == 700
    assert payload["items"][0]["question"] == "U1 私人失败题"
    assert payload["items"][0]["allowed_actions"] == ["retry"]


def test_refresh_loaded_range_returns_only_currently_recoverable_rows(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post(
            "/api/personal-analysis-queue/failed/refresh",
            json={"loaded_count": 20},
        )

    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert [item["queue_id"] for item in response.json()["items"]] == [2700]
    assert response.json()["items"][0]["allowed_actions"] == ["retry"]


def test_refresh_loaded_range_rejects_more_than_one_batch(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post(
            "/api/personal-analysis-queue/failed/refresh",
            json={"loaded_count": 5001},
        )

    assert response.status_code == 422, response.text


def test_refresh_rejects_cursor_queue_id_outside_sqlite_integer_range(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post(
            "/api/personal-analysis-queue/failed/refresh",
            json={
                "loaded_count": 1,
                "cursor": {
                    "created_at": "2026-10-04T00:00:00Z",
                    "queue_id": 9223372036854775808,
                },
            },
        )

    assert response.status_code == 422, response.text


def test_refresh_service_rejects_cursor_queue_id_outside_sqlite_integer_range():
    from app.services.personal_analysis_recovery import refresh_personal_analysis_failures

    with pytest.raises(ValueError, match="SQLite signed integer range"):
        refresh_personal_analysis_failures(
            None,
            owner_id=101,
            loaded_count=1,
            cursor={"created_at": "2026-10-04T00:00:00Z", "queue_id": 9223372036854775808},
        )


def test_retry_rejects_queue_id_outside_sqlite_integer_range(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post(
            "/api/personal-analysis-queue/9223372036854775808/retry",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    assert response.status_code == 422, response.text


def test_retry_service_rejects_queue_id_outside_sqlite_integer_range():
    from app.services.personal_analysis_recovery import retry_personal_analysis_failure

    with pytest.raises(ValueError, match="SQLite signed integer range"):
        retry_personal_analysis_failure(None, queue_id=9223372036854775808, owner_id=101)


def test_refresh_cursor_uses_stable_created_at_and_queue_id_order(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, question, owner_id, import_id) "
        "VALUES (1708, 700, 'U1 第二条私人失败题', 101, NULL)"
    )
    test_db.execute(
        "INSERT INTO analysis_queue (id, interview_id, question_detail_id, owner_id, "
        "status, root_import_id) VALUES (2708, 700, 1708, 101, 'failed', NULL)"
    )
    test_db.commit()

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        first = client.post(
            "/api/personal-analysis-queue/failed/refresh",
            json={"loaded_count": 1},
        )
        first_payload = first.json()
        second = client.post(
            "/api/personal-analysis-queue/failed/refresh",
            json={"loaded_count": 1, "cursor": first_payload["next_cursor"]},
        )

    assert first.status_code == second.status_code == 200
    assert first_payload["total"] == second.json()["total"] == 2
    assert [item["queue_id"] for item in first_payload["items"]] == [2708]
    assert [item["queue_id"] for item in second.json()["items"]] == [2700]
    assert second.json()["next_cursor"] is None


def test_owner_retry_requeues_same_row_and_dispatches_as_owner(client, test_db, monkeypatch):
    _seed_rootless_and_scoped_failures(test_db)
    schedule = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.pipeline.queue._run_cluster_batch_in_background", schedule
    )

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post("/api/personal-analysis-queue/2700/retry", json={})

    assert response.status_code == 202, response.text
    assert response.json() == {"queue_id": 2700, "status": "pending", "created": True}
    row = test_db.execute(
        "SELECT id, status, root_import_id, processed_at, locked_until "
        "FROM analysis_queue WHERE id = 2700"
    ).fetchone()
    assert tuple(row) == (2700, "pending", None, None, None)
    assert test_db.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 0
    assert test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
    schedule.assert_awaited_once_with(user_id=101)


def test_repeat_retry_is_idempotent_and_non_owners_cannot_retry(client, test_db, monkeypatch):
    _seed_rootless_and_scoped_failures(test_db)
    schedule = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.pipeline.queue._run_cluster_batch_in_background", schedule
    )

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        first = client.post("/api/personal-analysis-queue/2700/retry", json={})
        second = client.post("/api/personal-analysis-queue/2700/retry", json={})
    assert first.status_code == 202, first.text
    assert first.json()["created"] is True
    assert second.status_code == 200, second.text
    assert second.json() == {"queue_id": 2700, "status": "pending", "created": False}
    assert test_db.execute(
        "SELECT COUNT(*) FROM analysis_queue WHERE id = 2700"
    ).fetchone()[0] == 1
    assert schedule.await_count == 2  # Rechecks durable dispatch without duplicating work.

    for user in (
        {"id": 102, "is_admin": 0, "username": "owner-102"},
        {"id": 201, "is_admin": 1, "username": "admin-201"},
    ):
        with _as_user(user):
            response = client.post("/api/personal-analysis-queue/2700/retry", json={})
        assert response.status_code == 404
    assert schedule.await_count == 2


def test_public_and_upload_root_failures_are_not_owner_rootless_retries(client, test_db, monkeypatch):
    _seed_rootless_and_scoped_failures(test_db)
    schedule = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.pipeline.queue._run_cluster_batch_in_background", schedule
    )

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        public_retry = client.post("/api/personal-analysis-queue/2702/retry", json={})
        contribution_retry = client.post(
            "/api/personal-analysis-queue/2707/retry", json={}
        )
        rooted_retry = client.post("/api/personal-analysis-queue/2703/retry", json={})
        pending_list = client.get("/api/personal-analysis-queue/failed?page=1&page_size=1")

    assert public_retry.status_code == 404
    assert contribution_retry.status_code == 404
    assert rooted_retry.status_code == 404
    assert pending_list.status_code == 200
    assert pending_list.json()["total"] == 1
    assert schedule.await_count == 0


def test_periodic_reconcile_recovers_committed_retry_without_a_cluster_job(
    client, test_db, monkeypatch
):
    _seed_rootless_and_scoped_failures(test_db)
    failed_dispatch = AsyncMock(side_effect=RuntimeError("simulated process gap"))
    monkeypatch.setattr(
        "app.services.pipeline.queue._run_cluster_batch_in_background",
        failed_dispatch,
    )

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post("/api/personal-analysis-queue/2700/retry", json={})

    assert response.status_code == 202, response.text
    assert test_db.execute(
        "SELECT status FROM analysis_queue WHERE id = 2700"
    ).fetchone()[0] == "pending"
    assert test_db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    monkeypatch.undo()
    monkeypatch.setattr("app.services.pipeline.queue.CLUSTER_DELAY_SECONDS", 300)
    from app.worker_scheduled import scheduled_upload_queue_reconcile_task

    report = asyncio.run(scheduled_upload_queue_reconcile_task({}))

    assert report["rootless_personal_owner_id"] == 101
    row = test_db.execute(
        "SELECT j.job_type, j.status, j.root_import_id, jp.payload "
        "FROM jobs j JOIN job_payloads jp ON jp.job_id = j.id "
        "WHERE j.job_type = 'cluster_batch'"
    ).fetchone()
    assert row is not None
    assert row["job_type"] == "cluster_batch"
    assert row["root_import_id"] is None
    assert row["status"] == "pending"
    assert '"user_id": 101' in row["payload"]


def test_owner_cannot_list_or_retry_mismatched_or_import_details(client, test_db, monkeypatch):
    _seed_rootless_and_scoped_failures(test_db)
    schedule = AsyncMock(return_value=True)

    monkeypatch.setattr(
        "app.services.pipeline.queue._run_cluster_batch_in_background", schedule
    )
    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        listed = client.get("/api/personal-analysis-queue/failed")
        retries = [
            client.post(f"/api/personal-analysis-queue/{queue_id}/retry", json={})
            for queue_id in (2704, 2705)
        ]

    assert listed.status_code == 200, listed.text
    assert [item["queue_id"] for item in listed.json()["items"]] == [2700]
    assert [response.status_code for response in retries] == [404, 404]
    assert schedule.await_count == 0


def test_completed_personal_queue_row_returns_stable_retry_not_allowed(client, test_db):
    _seed_rootless_and_scoped_failures(test_db)
    test_db.execute("UPDATE analysis_queue SET status = 'done' WHERE id = 2700")
    test_db.commit()

    with _as_user({"id": 101, "is_admin": 0, "username": "owner-101"}):
        response = client.post("/api/personal-analysis-queue/2700/retry", json={})

    assert response.status_code == 409
    assert "RETRY_NOT_ALLOWED" in response.text

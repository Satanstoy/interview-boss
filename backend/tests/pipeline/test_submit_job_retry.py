from unittest.mock import AsyncMock, MagicMock, patch


def _override_user():
    from app.asgi import app
    from app.core.auth import get_current_user

    user = {"id": 1, "is_admin": True, "username": "sj"}
    app.dependency_overrides[get_current_user] = lambda: user
    return app, get_current_user


def _create_failed_submit_job(test_db):
    cursor = test_db.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
        "available_at, error) VALUES ('submit_import', 'failed', 6, 1, "
        "CURRENT_TIMESTAMP, '模拟失败')"
    )
    job_id = cursor.lastrowid
    test_db.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, '{"raw_text":"待重试的面经","target":"personal","user_id":1}'),
    )
    test_db.commit()
    return job_id


def test_failed_submit_job_is_visible_and_retry_creates_new_attempt(
    client, test_db
):
    app, dependency = _override_user()
    try:
        failed_id = _create_failed_submit_job(test_db)

        response = client.get("/api/submit-jobs/active")
        assert response.status_code == 200
        assert response.json()[0]["id"] == failed_id
        assert response.json()[0]["status"] == "failed"
        assert response.json()[0]["retryable"] is True

        arq_job = MagicMock(job_id="arq-retry-1")
        with patch(
            "app.worker.enqueue_submit_import_job",
            new=AsyncMock(return_value=arq_job),
        ):
            retry_response = client.post(f"/api/submit-jobs/{failed_id}/retry", json={})

        assert retry_response.status_code == 200
        retry_id = retry_response.json()["job_id"]
        assert retry_id != failed_id

        original = test_db.execute(
            "SELECT status FROM jobs WHERE id = ?", (failed_id,)
        ).fetchone()
        retry = test_db.execute(
            "SELECT status, parent_job_id, arq_job_id FROM jobs WHERE id = ?",
            (retry_id,),
        ).fetchone()
        assert original["status"] == "failed"
        assert retry["status"] == "queued"
        assert retry["parent_job_id"] == failed_id
        assert retry["arq_job_id"] == "arq-retry-1"

        visible = client.get("/api/submit-jobs/active").json()
        assert [item["id"] for item in visible] == [retry_id]
    finally:
        app.dependency_overrides.pop(dependency, None)

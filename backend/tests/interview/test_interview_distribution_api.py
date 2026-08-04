"""HTTP contracts for system defaults and per-user distribution preferences."""

import pytest


@pytest.fixture
def distribution_client(client):
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_admin": 0}
    yield client
    app.dependency_overrides.pop(get_current_user, None)


def _seed_default(test_db):
    from app.services.interview_distribution import refresh_distribution_scope

    interview_id = test_db.execute(
        """
        INSERT INTO interview (url, company, round, focus, questions_list, difficulty, owner_id, status, job_position)
        VALUES ('https://example.test/default', '', '', '', '', '', NULL, 'approved', 'Agent开发')
        """
    ).lastrowid
    for index in range(5):
        test_db.execute(
            """
            INSERT INTO questions_detail (interview_id, url, question, question_type, dimension, job_position)
            VALUES (?, 'https://example.test/default', ?, 'knowledge_probe', 'knowledge_probe', 'Agent开发')
            """,
            (interview_id, f"知识题 {index}"),
        )
    refresh_distribution_scope(test_db, "public_job_position", "Agent开发")
    test_db.commit()


def test_default_endpoint_returns_one_complete_stats_version(distribution_client, test_db):
    _seed_default(test_db)

    response = distribution_client.get("/api/interview/distribution/default?job_position=Agent开发")

    assert response.status_code == 200
    body = response.json()["data"]
    assert set(body["distribution"]) == {
        "project_followup", "knowledge_probe", "algorithm_coding", "system_design", "behavioral"
    }
    assert sum(body["distribution"].values()) == pytest.approx(1.0)


def test_preference_put_rejects_non_normalized_distribution(distribution_client):
    response = distribution_client.put(
        "/api/profile/interview-distribution-preference?job_position=Agent开发",
        json={
            "mode": "custom",
            "target_question_count": 10,
            "custom_distribution": {
                "project_followup": 0.5,
                "knowledge_probe": 0.5,
                "algorithm_coding": 0.5,
                "system_design": 0,
                "behavioral": 0,
            },
        },
    )

    assert response.status_code == 422


def test_preference_round_trip_preserves_all_five_custom_types(distribution_client):
    payload = {
        "mode": "custom",
        "target_question_count": 8,
        "custom_distribution": {
            "project_followup": 0.25,
            "knowledge_probe": 0.25,
            "algorithm_coding": 0.25,
            "system_design": 0.125,
            "behavioral": 0.125,
        },
        "style_strength": "normal",
    }

    saved = distribution_client.put(
        "/api/profile/interview-distribution-preference?job_position=Agent开发", json=payload
    )
    fetched = distribution_client.get(
        "/api/profile/interview-distribution-preference?job_position=Agent开发"
    )

    assert saved.status_code == 200
    assert fetched.json()["data"]["custom_distribution"] == payload["custom_distribution"]

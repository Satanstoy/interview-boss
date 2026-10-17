"""Clear-db operations must leave a durable administrative audit trail."""

import json
import sqlite3


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


def _audit_events(test_db):
    return [
        dict(row)
        for row in test_db.execute(
            "SELECT event_type, status, actor_id, metadata FROM admin_audit_log "
            "WHERE event_type LIKE 'clear_db%' ORDER BY id"
        ).fetchall()
    ]


def test_clear_db_success_is_audited_and_survives_business_table_cleanup(
    client, test_db, tmp_path, monkeypatch
):
    from app.asgi import app
    import app.core.config as config

    db_source = tmp_path / "test.db"
    with sqlite3.connect(db_source) as conn:
        conn.execute("CREATE TABLE marker (value TEXT)")
    monkeypatch.setattr(config, "DB_PATH", str(db_source))

    _override_admin(app)
    try:
        preview = client.post("/api/analytics/clear-db/preview", headers=CSRF_HEADERS)
        response = client.post(
            f"/api/clear-db?confirm_token={preview.json()['confirm_token']}",
            headers=CSRF_HEADERS,
        )
    finally:
        _clear_overrides(app)

    assert response.status_code == 200
    events = _audit_events(test_db)
    assert [event["status"] for event in events[-2:]] == ["started", "success"]
    assert all(event["actor_id"] == 1 for event in events[-2:])
    success_metadata = json.loads(events[-1]["metadata"])
    assert success_metadata["target_scope"] == "all_database_tables"
    assert success_metadata["backup_sha256"]
    assert success_metadata["affected_rows"] == {}


def test_clear_db_confirmation_failure_is_audited(client, test_db):
    from app.asgi import app

    _override_admin(app)
    try:
        response = client.post("/api/clear-db", headers=CSRF_HEADERS)
    finally:
        _clear_overrides(app)

    assert response.status_code == 400
    assert _audit_events(test_db)[-1]["status"] == "rejected"


def test_clear_db_backup_failure_is_audited(client, test_db, monkeypatch):
    from app.asgi import app

    def fail_copy(*_args, **_kwargs):
        raise OSError("backup unavailable")

    import app.routers.analytics as analytics

    monkeypatch.setattr(analytics, "_backup_sqlite_online", fail_copy)
    _override_admin(app)
    try:
        preview = client.post("/api/analytics/clear-db/preview", headers=CSRF_HEADERS)
        response = client.post(
            "/api/clear-db?confirm_token=" + preview.json()["confirm_token"],
            headers=CSRF_HEADERS,
        )
    finally:
        _clear_overrides(app)

    assert response.status_code == 500
    assert _audit_events(test_db)[-1]["status"] == "failure"


def test_clear_db_stops_before_backup_when_started_audit_fails(
    client, test_db, monkeypatch
):
    from app.asgi import app
    import app.routers.analytics as analytics

    called = False

    async def fail_audit(*_args, **_kwargs):
        return False

    def backup_should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(analytics, "_record_clear_db_audit", fail_audit)
    monkeypatch.setattr(analytics, "_backup_sqlite_online", backup_should_not_run)
    _override_admin(app)
    try:
        preview = client.post("/api/analytics/clear-db/preview", headers=CSRF_HEADERS)
        response = client.post(
            f"/api/clear-db?confirm_token={preview.json()['confirm_token']}",
            headers=CSRF_HEADERS,
        )
    finally:
        _clear_overrides(app)

    assert response.status_code == 503
    assert not called


def test_clear_db_online_backup_includes_wal_frames(tmp_path):
    import app.routers.analytics as analytics

    source = tmp_path / "source.db"
    backup = tmp_path / "backup.db"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('wal-value')")
        conn.commit()

        analytics._backup_sqlite_online(str(source), str(backup))

    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT value FROM marker").fetchone()[0] == "wal-value"

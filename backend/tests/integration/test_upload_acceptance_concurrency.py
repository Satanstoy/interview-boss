"""Real JWT/HTTP uploads over independent SQLite WAL connections."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import sys
import threading

import pytest

from app.core.auth import create_access_token


@pytest.fixture
def acceptance_db(client, test_db, monkeypatch, tmp_path):
    path = str(tmp_path / "acceptance.sqlite3")
    primary = sqlite3.connect(path, check_same_thread=False)
    primary.row_factory = sqlite3.Row
    test_db.backup(primary)
    primary.execute("PRAGMA journal_mode=WAL")
    primary.execute("PRAGMA foreign_keys=ON")
    position = primary.execute(
        "INSERT INTO job_positions(name) VALUES ('acceptance-concurrency')"
    ).lastrowid
    for uid in (9701, 9702):
        primary.execute(
            "INSERT INTO users(id,username,password_hash,current_position_id) "
            "VALUES (?,?,'TEST_HASH',?)",
            (uid, f"acceptance-{uid}", position),
        )
    primary.commit()
    local = threading.local()
    connections = []
    before_insert = [None]

    def connection():
        if not hasattr(local, "conn"):
            conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")

            def trace(sql):
                if sql.upper().startswith("INSERT INTO UPLOAD_IMPORTS") and before_insert[0]:
                    callback = before_insert[0]
                    before_insert[0] = None
                    callback()

            conn.set_trace_callback(trace)
            local.conn = conn
            connections.append(conn)
        return local.conn

    for name, module in list(sys.modules.items()):
        if name.startswith("app.") and module and hasattr(module, "get_db_connection"):
            monkeypatch.setattr(module, "get_db_connection", connection)
    monkeypatch.setattr(client._transport, "raise_server_exceptions", False)
    yield primary, path, before_insert
    for conn in connections:
        conn.close()
    primary.close()


def headers(uid, key):
    return {
        "Authorization": "Bearer " + create_access_token({"user_id": uid, "type": "access"}),
        "X-Requested-With": "XMLHttpRequest",
        "Idempotency-Key": key,
    }


@pytest.mark.parametrize("endpoint,code", [
    ("/api/submit-jobs", 202),
    ("/api/submit-stream-v2", 200),
])
def test_upload_acceptance_survives_competing_writer(client, acceptance_db, endpoint, code):
    db, path, hook = acceptance_db
    attempts = []

    def competing_writer():
        # Interleave a real second connection after the route's idempotency read.
        # WAL permits this commit under a deferred read transaction, invalidating
        # its snapshot. An immediate write transaction reserves the writer first.
        with sqlite3.connect(path, timeout=0) as other:
            try:
                other.execute("UPDATE users SET username=username WHERE id=9702")
                other.commit()
                attempts.append("committed")
            except sqlite3.OperationalError as exc:
                attempts.append(exc.sqlite_errorcode & 0xFF)

    hook[0] = competing_writer
    response = client.post(endpoint, headers=headers(9701, "writer-interleave"), data={
        "text": "面经：解释事务隔离", "target": "private", "content_type": "interview",
    })
    assert attempts in (["committed"], [sqlite3.SQLITE_BUSY]), attempts
    assert response.status_code == code, response.text
    roots = db.execute("SELECT id,requester_id FROM upload_imports").fetchall()
    assert len(roots) == 1 and roots[0]["requester_id"] == 9701
    assert db.execute("SELECT count(*) FROM upload_attempts").fetchone()[0] == 1


@pytest.mark.parametrize("same_owner", [False, True])
def test_simultaneous_uploads_preserve_owner_and_idempotency(client, acceptance_db, same_owner):
    db, _, _ = acceptance_db
    barrier = threading.Barrier(2)

    def submit(uid):
        barrier.wait(timeout=10)
        return client.post("/api/submit-jobs", headers=headers(uid, "concurrent-key"), data={
            "text": "面经：解释事务隔离", "target": "private", "content_type": "interview",
        })

    uids = [9701, 9701 if same_owner else 9702]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(submit, uids))
    assert [r.status_code for r in responses] == [202, 202], [r.text for r in responses]
    ids = [r.json()["import_id"] for r in responses]
    assert len(set(ids)) == (1 if same_owner else 2)
    for uid, import_id in zip(uids, ids):
        assert db.execute("SELECT requester_id FROM upload_imports WHERE id=?", (import_id,)).fetchone()[0] == uid
    assert db.execute("SELECT count(*) FROM upload_attempts").fetchone()[0] == len(set(ids))
    if not same_owner:
        denied = client.get(f"/api/upload-imports/{ids[1]}", headers=headers(9701, "read"))
        missing = client.get("/api/upload-imports/missing", headers=headers(9701, "read"))
        assert denied.status_code == missing.status_code == 404
        assert denied.json() == missing.json()

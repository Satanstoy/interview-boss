"""AC-017 / UR-017：跨代与并发恢复。

契约（contracts.md §2.4）：

- 任何历史 job（A→B→C 链）发起恢复都先解析到**同一根任务**；
- 根任务至多一个 active attempt：并发恢复只创建一个，另一方返回 ``created_attempt=False``；
- 恢复不重置已成功阶段；同一 ``work_key`` 至多一个活跃 job。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import run_migrations
from app.services.upload_lifecycle import resolve_root_job, restore_upload


def _connect(path, migrate=True):
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if migrate:
        run_migrations(conn)
    return conn


def _seed(conn):
    conn.execute("INSERT INTO users (id, username, password_hash) VALUES (101, 'u101', 'x')")
    conn.execute(
        "INSERT INTO upload_imports (id, requester_id, idempotency_key, request_hash, "
        "target_intent, source_type, pipeline_version) "
        "VALUES ('imp-1', 101, 'k1', 'h1', 'private', 'interview', 'v1')"
    )
    conn.commit()


def _db(tmp_path=None):
    conn = _connect(":memory:")
    _seed(conn)
    return conn


def _job(conn, *, job_id=None, parent=None, work_key, status="failed"):
    cur = conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, work_key, parent_job_id) "
        "VALUES ('submit_import', ?, 101, 'imp-1', ?, ?)",
        (status, work_key, parent),
    )
    return cur.lastrowid


def test_retry_on_any_link_of_chain_resolves_root(tmp_path):
    conn = _db(tmp_path)
    a = _job(conn, work_key="extract:document:v1")
    b = _job(conn, work_key="classify:document:v1", parent=a, status="failed")
    c = _job(conn, work_key="persist:document:v1", parent=b, status="running")
    assert resolve_root_job(conn, a)["id"] == a
    assert resolve_root_job(conn, b)["id"] == a
    assert resolve_root_job(conn, c)["id"] == a
    conn.close()


def test_restore_returns_existing_active_attempt(tmp_path):
    conn = _db(tmp_path)
    first = restore_upload(conn, actor_id=101, import_id="imp-1")
    assert first["created_attempt"] is True
    assert first["attempt_no"] == 1

    again = restore_upload(conn, actor_id=101, import_id="imp-1")
    assert again["created_attempt"] is False
    assert again["attempt_id"] == first["attempt_id"]
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()


def test_restore_from_legacy_job_resolves_same_root(tmp_path):
    conn = _db(tmp_path)
    first = restore_upload(conn, actor_id=101, import_id="imp-1")
    a = _job(conn, work_key="extract:document:v1", status="failed")
    b = _job(conn, work_key="classify:document:v1", parent=a, status="failed")

    from_legacy = restore_upload(conn, actor_id=101, job_id=b)
    assert from_legacy["import_id"] == "imp-1"
    assert from_legacy["created_attempt"] is False
    assert from_legacy["attempt_id"] == first["attempt_id"]
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()


def test_concurrent_restore_creates_single_attempt(tmp_path):
    """A→B→C 历史链上的两个 job 并发恢复，只创建一个 active attempt。"""

    import threading

    db_path = str(tmp_path / "race.db")
    setup = _connect(db_path)
    _seed(setup)
    job_a = _job(setup, work_key="extract:document:v1", status="failed")
    job_b = _job(
        setup,
        work_key="classify:document:v1",
        parent=job_a,
        status="failed",
    )
    job_c = _job(
        setup,
        work_key="persist:document:v1",
        parent=job_b,
        status="failed",
    )
    assert resolve_root_job(setup, job_c)["id"] == job_a
    setup.commit()
    setup.close()

    results: dict[int, dict] = {}
    errors: dict[int, Exception] = {}

    legacy_job_ids = {1: job_a, 2: job_b}

    def _run(index):
        conn = _connect(db_path, migrate=False)
        try:
            results[index] = restore_upload(
                conn,
                actor_id=101,
                job_id=legacy_job_ids[index],
            )
            conn.commit()
        except Exception as exc:  # pragma: no cover - 失败时由断言暴露
            errors[index] = exc
        finally:
            conn.close()

    threads = [threading.Thread(target=_run, args=(i,)) for i in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    assert len(results) == 2
    created_flags = sorted(item["created_attempt"] for item in results.values())
    assert created_flags == [False, True]
    assert {item["import_id"] for item in results.values()} == {"imp-1"}
    assert results[1]["attempt_id"] == results[2]["attempt_id"]
    conn = _connect(db_path, migrate=False)
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    duplicate_active_work = conn.execute(
        "SELECT work_key, COUNT(*) AS count FROM jobs "
        "WHERE root_import_id = 'imp-1' AND status IN ('pending','queued','running') "
        "GROUP BY work_key HAVING COUNT(*) > 1"
    ).fetchall()
    assert duplicate_active_work == []
    conn.close()


def test_restore_never_duplicates_active_work_key(tmp_path):
    conn = _db(tmp_path)
    restore_upload(conn, actor_id=101, import_id="imp-1")
    attempt_id = conn.execute("SELECT id FROM upload_attempts").fetchone()["id"]
    conn.execute(
        "INSERT INTO jobs (job_type, status, created_by, root_import_id, "
        "upload_attempt_id, work_key) "
        "VALUES ('submit_import', 'running', 101, 'imp-1', ?, 'answer:public:456:v1')",
        (attempt_id,),
    )
    conn.commit()

    # 恢复不得为同一 work_key 再造一个活跃 job
    restore_upload(conn, actor_id=101, import_id="imp-1")
    active = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE work_key = 'answer:public:456:v1' "
        "AND status IN ('pending','queued','running')"
    ).fetchone()[0]
    assert active == 1
    conn.close()


def test_restore_requires_owner(tmp_path):
    conn = _db(tmp_path)
    restore_upload(conn, actor_id=101, import_id="imp-1")
    with pytest.raises(Exception) as exc:
        restore_upload(conn, actor_id=102, import_id="imp-1")
    assert getattr(exc.value, "code", "") in ("NOT_FOUND", "PERMISSION_REVOKED")
    assert conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0] == 1
    conn.close()

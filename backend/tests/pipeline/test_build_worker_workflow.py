import sqlite3
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def rebuild_job(test_db, monkeypatch, tmp_path):
    import app.worker as worker
    from app.services.pipeline import batch, queue

    conn = test_db
    conn.execute("INSERT INTO jobs (id, job_type, status, created_by) VALUES (1, 'build_master_bank', 'queued', 1)")
    conn.execute("INSERT INTO interview (id, status, job_position) VALUES (100, 'approved', '后端开发')")
    conn.execute(
        "INSERT INTO questions_detail (id, interview_id, question, job_position) "
        "VALUES (200, 100, 'Redis持久化', '后端开发')"
    )
    conn.commit()
    monkeypatch.setattr(queue, "get_db_connection", lambda: conn)
    monkeypatch.setattr(batch, "get_db_connection", lambda: conn)
    monkeypatch.setattr("app.db.connection.get_current_job_position", lambda: "后端开发")
    monkeypatch.setattr("app.core.config.DB_PATH", str(tmp_path / "source.db"))
    monkeypatch.setattr(worker, "_backup_db_online", Mock())
    monkeypatch.setattr(worker, "_schedule_cluster_answer_jobs", AsyncMock())
    monkeypatch.setattr("app.core.cache.invalidate_master_bank_cache", AsyncMock())
    cluster = AsyncMock(return_value={"count": 2, "ids": []})
    monkeypatch.setattr("app.services.pipeline.cluster_batch", cluster)
    return conn, worker, cluster


def test_worker_backup_preserves_committed_wal_data(tmp_path):
    from app.worker import _backup_db_online

    source = tmp_path / "source.db"
    target = tmp_path / "backup.db"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE evidence (value TEXT)")
        conn.execute("INSERT INTO evidence VALUES ('committed')")
        conn.commit()
        _backup_db_online(str(source), str(target))
        with sqlite3.connect(target) as snapshot:
            assert snapshot.execute("SELECT value FROM evidence").fetchall() == [("committed",)]


async def test_worker_clear_preserves_personal_bank(rebuild_job):
    conn, worker, _ = rebuild_job
    conn.execute("INSERT INTO question_bank (id, question, job_position) VALUES (20, '公共旧题', '后端开发')")
    conn.execute("INSERT INTO question_bank (id, question, job_position, owner_id) VALUES (21, '个人旧题', '后端开发', 1)")
    conn.commit()

    result = await worker._build_master_bank_job({}, 1)

    assert result["status"] == "completed"
    assert conn.execute("SELECT deleted_at FROM question_bank WHERE id = 20").fetchone()[0] is not None
    assert conn.execute("SELECT deleted_at FROM question_bank WHERE id = 21").fetchone()[0] is None


async def test_worker_enqueues_and_processes_loaded_questions(rebuild_job):
    conn, worker, cluster = rebuild_job

    result = await worker._build_master_bank_job({}, 1)

    assert result == {"status": "completed", "total_new": 2, "restored": 0}
    cluster.assert_awaited_once()
    assert [item["qd_id"] for item in cluster.await_args.args[0]] == [200]
    assert cluster.await_args.kwargs == {"user_id": 1, "skip_clean": True, "return_new_ids": True}
    assert [tuple(row) for row in conn.execute("SELECT question_detail_id, status FROM analysis_queue")] == [(200, "done")]
    assert conn.execute("SELECT status FROM jobs WHERE id = 1").fetchone()[0] == "completed"


@pytest.mark.parametrize("attempts, expected_status", [(0, "pending"), (3, "failed")])
async def test_worker_retries_or_fails_job_and_releases_batch(rebuild_job, attempts, expected_status):
    conn, worker, cluster = rebuild_job
    conn.execute("UPDATE jobs SET attempts = ? WHERE id = 1", (attempts,))
    conn.commit()
    cluster.side_effect = RuntimeError("mock clustering failure")

    with pytest.raises(RuntimeError, match="mock clustering failure"):
        await worker._build_master_bank_job({}, 1)

    job = conn.execute("SELECT status, last_error, worker_id FROM jobs WHERE id = 1").fetchone()
    assert tuple(job) == (expected_status, "mock clustering failure", None)
    assert conn.execute("SELECT status FROM analysis_queue WHERE question_detail_id = 200").fetchone()[0] == "pending"


async def test_worker_completes_empty_rebuild_without_clustering(rebuild_job):
    conn, worker, cluster = rebuild_job
    conn.execute("DELETE FROM questions_detail")
    conn.commit()

    assert await worker._build_master_bank_job({}, 1) == {"status": "empty"}
    cluster.assert_not_awaited()
    assert conn.execute("SELECT status FROM jobs WHERE id = 1").fetchone()[0] == "completed"

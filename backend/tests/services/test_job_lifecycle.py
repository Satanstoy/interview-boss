import pytest


def _new_job(conn, idempotency_key=None):
    cur = conn.execute(
        "INSERT INTO jobs (job_type, status, idempotency_key) VALUES (?, 'pending', ?)",
        ("submit_import", idempotency_key),
    )
    conn.commit()
    return cur.lastrowid


def test_submit_job_dispatch_claim_and_completion(test_db):
    from app.services.job_lifecycle import (
        claim_dispatch_batch,
        claim_job,
        complete_job,
        mark_job_dispatched,
        touch_job,
    )

    job_id = _new_job(test_db)
    reserved = claim_dispatch_batch(test_db, limit=1)
    assert [row["id"] for row in reserved] == [job_id]
    assert mark_job_dispatched(test_db, job_id, "arq-1")
    test_db.commit()

    claimed = claim_job(test_db, job_id, "worker-a")
    assert claimed["status"] == "running"
    assert claimed["attempts"] == 1
    assert claim_job(test_db, job_id, "worker-b") is None
    assert touch_job(test_db, job_id, "worker-a", 2, 6, "处理中")
    assert complete_job(test_db, job_id, "worker-a", '{"ok": true}')
    test_db.commit()

    row = test_db.execute(
        "SELECT status, result, locked_until, worker_id FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    assert dict(row) == {
        "status": "completed",
        "result": '{"ok": true}',
        "locked_until": None,
        "worker_id": None,
    }


def test_expired_dispatch_lease_is_recovered(test_db):
    from app.services.job_lifecycle import claim_dispatch_batch

    job_id = _new_job(test_db)
    assert claim_dispatch_batch(test_db, limit=1)[0]["id"] == job_id
    test_db.execute(
        "UPDATE jobs SET locked_until = datetime('now', '-1 second') WHERE id = ?",
        (job_id,),
    )
    test_db.commit()

    recovered = claim_dispatch_batch(test_db, limit=1)
    assert [row["id"] for row in recovered] == [job_id]
    assert test_db.execute(
        "SELECT status FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()[0] == "queued"


def test_failed_submit_job_returns_to_pending_with_backoff(test_db):
    from app.services.job_lifecycle import claim_dispatch_batch, claim_job, fail_job

    job_id = _new_job(test_db)
    claim_dispatch_batch(test_db, limit=1)
    test_db.commit()
    claim_job(test_db, job_id, "worker-a")
    outcome = fail_job(test_db, job_id, "worker-a", "temporary LLM timeout")
    test_db.commit()

    assert outcome["status"] == "retrying"
    row = test_db.execute(
        "SELECT status, last_error, locked_until, worker_id FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    assert row["status"] == "pending"
    assert row["last_error"] == "temporary LLM timeout"
    assert row["locked_until"] is None
    assert row["worker_id"] is None


def test_submit_job_idempotency_key_is_unique(test_db):
    _new_job(test_db, "same-request")
    with pytest.raises(Exception):
        _new_job(test_db, "same-request")


def test_answer_jobs_are_idempotent_per_import_question(test_db):
    from app.services.job_lifecycle import create_answer_generation_jobs

    parent_id = _new_job(test_db, "submit-request")
    first = create_answer_generation_jobs(
        test_db,
        parent_id,
        [(101, "什么是幂等性？"), (102, "解释事务隔离级别")],
        user_id=None,
    )
    second = create_answer_generation_jobs(
        test_db,
        parent_id,
        [(101, "什么是幂等性？"), (102, "解释事务隔离级别")],
        user_id=None,
    )
    test_db.commit()

    assert second == first
    rows = test_db.execute(
        "SELECT job_type, status, created_by FROM jobs "
        "WHERE id IN (?, ?) ORDER BY id",
        first,
    ).fetchall()
    assert [dict(row) for row in rows] == [
        {"job_type": "generate_answer", "status": "pending", "created_by": None},
        {"job_type": "generate_answer", "status": "pending", "created_by": None},
    ]
    payload = test_db.execute(
        "SELECT payload FROM job_payloads WHERE job_id = ?", (first[0],)
    ).fetchone()[0]
    assert "什么是幂等性？" in payload

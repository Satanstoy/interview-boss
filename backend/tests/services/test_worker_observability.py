"""Worker heartbeat and cron execution observability contracts."""

import asyncio


def test_worker_heartbeat_records_last_seen_and_status(test_db):
    from app import worker

    record = getattr(worker, "record_worker_heartbeat", None)
    assert callable(record)

    result = record(
        "test-worker",
        status="online",
        queue_name="arq:test",
        metadata={"pid": 123},
        conn=test_db,
    )

    assert result["worker_name"] == "test-worker"
    row = test_db.execute(
        "SELECT status, queue_name, metadata_json FROM worker_heartbeats "
        "WHERE worker_name = 'test-worker'"
    ).fetchone()
    assert tuple(row) == ("online", "arq:test", '{"pid":123}')


def test_cron_observability_distinguishes_success_failure_and_not_run(test_db, monkeypatch):
    from app import worker

    monkeypatch.setattr("app.db.connection.get_db_connection", lambda: test_db)
    observed = getattr(worker, "observed_cron_task", None)
    get_status = getattr(worker, "get_cron_status", None)
    assert callable(observed)
    assert callable(get_status)
    assert get_status("never-ran", conn=test_db)["status"] == "not_run"

    async def succeeds(ctx):
        return {"processed": 2}

    asyncio.run(observed(succeeds)({}))
    assert get_status("succeeds", conn=test_db)["status"] == "succeeded"

    async def fails(ctx):
        raise RuntimeError("redis unavailable")

    try:
        asyncio.run(observed(fails)({}))
    except RuntimeError:
        pass
    else:
        raise AssertionError("observed cron must preserve task failure")

    failed = get_status("fails", conn=test_db)
    assert failed["status"] == "failed"
    assert "redis unavailable" in failed["last_error"]

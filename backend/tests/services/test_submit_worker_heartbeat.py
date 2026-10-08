"""Independent submit heartbeat during an idle graph/model call."""

import asyncio
import json

import pytest


@pytest.mark.parametrize("lose_generation", [False, True, "database_error"])
async def test_idle_submit_worker_renews_or_stops_on_lost_lease(
    app_db_isolation, monkeypatch, lose_generation
):
    from app import worker

    conn = app_db_isolation
    job = conn.execute(
        "INSERT INTO jobs(job_type,status) VALUES('submit_import','pending')"
    ).lastrowid
    conn.execute(
        "INSERT INTO job_payloads(job_id,payload) VALUES(?,?)",
        (job, json.dumps({"user_id": 101, "target": "personal", "job_position": "后端"})),
    )
    conn.commit()
    entered = asyncio.Event()
    gate = asyncio.Event()

    async def idle_graph(*args, **kwargs):
        entered.set()
        await gate.wait()
        if False:
            yield ""

    # The graph is held idle; lease ownership and all SQL remain real.
    monkeypatch.setattr("app.agents.submit.graph.stream_submit_graph", idle_graph)
    monkeypatch.setattr(worker, "SUBMIT_LEASE_HEARTBEAT_SECONDS", 0.01, raising=False)
    task = asyncio.create_task(worker.submit_import_task({}, job))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        conn.execute("UPDATE jobs SET locked_until=datetime('now','+2 seconds') WHERE id=?", (job,))
        if lose_generation is True:
            conn.execute("UPDATE jobs SET lease_generation=lease_generation+1 WHERE id=?", (job,))
        if lose_generation == "database_error":
            conn.execute("CREATE TRIGGER fail_heartbeat BEFORE UPDATE OF locked_until ON jobs WHEN NEW.locked_until > datetime('now','+30 seconds') BEGIN SELECT RAISE(ABORT,'heartbeat unavailable'); END")
        conn.commit()

        async def observed():
            for _ in range(50):
                if lose_generation:
                    if task.done():
                        return True
                elif conn.execute(
                    "SELECT locked_until > datetime('now','+30 seconds') FROM jobs WHERE id=?",
                    (job,),
                ).fetchone()[0]:
                    return True
                await asyncio.sleep(0.01)
            return False

        assert await observed(), (
            "idle worker must independently renew, or stop after lease generation changes"
        )
        if lose_generation:
            with pytest.raises(asyncio.CancelledError):
                await task
        assert conn.execute("SELECT count(*) FROM interview").fetchone()[0] == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

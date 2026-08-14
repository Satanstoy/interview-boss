"""管理员评测控制面 API 契约。"""

import asyncio
import importlib

import pytest
from starlette.requests import Request


def _router():
    try:
        return importlib.import_module("app.routers.admin_evaluation")
    except ModuleNotFoundError:
        pytest.fail("app.routers.admin_evaluation 尚未实现")


def _context(conn):
    service = importlib.import_module("app.services.evaluation_service")

    def release(key, release_type, **kwargs):
        return service.create_release(
            conn,
            release_key=key,
            release_type=release_type,
            version="1.0",
            manifest={"key": key},
            **kwargs,
        )

    target = release("api-agent@1.0", "target", target_type="fixture")
    suite_release = release(
        "api-suite@1.0",
        "benchmark_suite",
        target_type="fixture",
        judge_model="fixed-judge",
    )
    protocol = release("api-protocol@1.0", "eval_protocol")
    judge = release("api-judge@1.0", "judge", judge_model="fixed-judge")
    harness = release("api-harness@1.0", "simulator_harness")
    simulator = release("api-simulator@1.0", "candidate_simulator")
    suite = service.create_benchmark_suite(
        conn,
        release_id=suite_release["id"],
        suite_key="api-suite",
        target_type="fixture",
        judge_model="fixed-judge",
    )
    service.create_benchmark_case(
        conn,
        suite_id=suite["id"],
        case_key="case-1",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"answer": "hello"}},
        contract={"hard_assertions": []},
    )
    conn.commit()
    return target, suite_release, protocol, judge, harness, simulator


def test_admin_router_exposes_control_plane_routes():
    module = _router()
    paths = {route.path for route in module.router.routes}

    assert "/api/admin/evals/overview" in paths
    assert "/api/admin/evals/releases" in paths
    assert "/api/admin/evals/benchmarks" in paths
    assert "/api/admin/evals/runs" in paths
    assert "/api/admin/evals/runs/{run_id}" in paths
    assert "/api/admin/evals/runs/{run_id}/cancel" in paths
    assert "/api/admin/evals/runs/{run_id}/events" in paths


def test_create_run_keeps_run_recoverable_when_queue_dispatch_fails(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)

    async def fail_dispatch(run_id):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(module, "enqueue_eval_run_job", fail_dispatch)
    body = module.CreateEvalRunRequest(
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=3,
    )

    result = asyncio.run(module.create_run(body, {"id": 1, "is_admin": 1}))

    assert result["status"] == "created"
    assert "dispatch_error" in result
    stored = test_db.execute(
        "SELECT status, total_items FROM eval_runs WHERE id = ?", (result["run_id"],)
    ).fetchone()
    assert tuple(stored) == ("created", 1)


def test_cancel_marks_request_and_persists_event(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    service = importlib.import_module("app.services.evaluation_service")
    run = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=4,
    )
    test_db.commit()

    result = asyncio.run(module.cancel_run(run["id"], {"id": 1, "is_admin": 1}))

    assert result["cancel_requested"] is True
    assert test_db.execute(
        "SELECT cancel_requested FROM eval_runs WHERE id = ?", (run["id"],)
    ).fetchone()[0] == 1
    assert test_db.execute(
        "SELECT event_type FROM eval_events WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
        (run["id"],),
    ).fetchone()[0] == "run.cancel_requested"


def test_sse_replays_only_events_after_last_event_id(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)
    service = importlib.import_module("app.services.evaluation_service")
    run = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=5,
    )
    service.append_event(test_db, run["id"], "run.created", {})
    service.append_event(test_db, run["id"], "run.completed", {"score": 0.9})
    test_db.execute("UPDATE eval_runs SET status = 'completed' WHERE id = ?", (run["id"],))
    test_db.commit()

    request = Request({"type": "http", "headers": []})
    response = asyncio.run(
        module.run_events(
            request,
            run["id"],
            after_sequence=1,
            admin={"id": 1, "is_admin": 1},
        )
    )

    async def collect():
        return "".join([chunk async for chunk in response.body_iterator])

    payload = asyncio.run(collect())
    assert "id: 2" in payload
    assert "run.completed" in payload
    assert "run.created" not in payload

"""Eval Worker 执行器的状态推进契约。"""

import asyncio
import importlib

import pytest


def _service():
    return importlib.import_module("app.services.evaluation_service")


def _executor():
    try:
        return importlib.import_module("app.services.evaluation_executor")
    except ModuleNotFoundError:
        pytest.fail("app.services.evaluation_executor 尚未实现")


def _context(conn):
    service = _service()

    def release(key, release_type, **kwargs):
        return service.create_release(
            conn,
            release_key=key,
            release_type=release_type,
            version="1.0",
            manifest={"key": key},
            **kwargs,
        )

    target = release("fixture-agent@1.0", "target", target_type="fixture")
    suite_release = release(
        "fixture-suite@1.0",
        "benchmark_suite",
        target_type="fixture",
        judge_model="fixed-judge",
    )
    protocol = release("protocol@1.0", "eval_protocol")
    judge = release("judge@1.0", "judge", judge_model="fixed-judge")
    harness = release("harness@1.0", "simulator_harness")
    simulator = release("simulator@1.0", "candidate_simulator")
    suite = service.create_benchmark_suite(
        conn,
        release_id=suite_release["id"],
        suite_key="fixture-suite",
        target_type="fixture",
        judge_model="fixed-judge",
    )
    service.create_benchmark_case(
        conn,
        suite_id=suite["id"],
        case_key="case-1",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"answer": "hello"}},
        contract={"hard_assertions": [{"id": "has_answer"}]},
    )
    conn.commit()
    return target, suite_release, protocol, judge, harness, simulator


def test_executor_completes_items_and_persists_attempt_evidence(test_db):
    executor = _executor()
    target, suite, protocol, judge, harness, simulator = _context(test_db)
    run = _service().create_eval_run(
        test_db,
        created_by=None,
        target_release_id=target["id"],
        benchmark_suite_release_id=suite["id"],
        eval_protocol_release_id=protocol["id"],
        judge_release_id=judge["id"],
        simulator_harness_release_id=harness["id"],
        candidate_simulator_release_id=simulator["id"],
        replication_count=1,
        seed=7,
    )
    test_db.commit()

    class FakeAdapter:
        async def prepare(self, case_snapshot, target_release):
            return {"case": case_snapshot, "target": target_release["release_key"]}

        async def run(self, prepared_case, target_release):
            return {"answer": prepared_case["case"]["candidate_view"]["answer"]}

        async def observe(self, raw_result):
            return {
                "status": "succeeded",
                "payload": raw_result,
                "hard_assertions": [{"id": "has_answer", "passed": True}],
            }

    result = asyncio.run(
        executor.execute_eval_run(
            run["id"],
            conn=test_db,
            adapter_resolver=lambda target_type: FakeAdapter(),
        )
    )

    assert result["status"] == "completed"
    assert test_db.execute(
        "SELECT status FROM eval_runs WHERE id = ?", (run["id"],)
    ).fetchone()[0] == "completed"
    item = test_db.execute(
        "SELECT status, selected_attempt_id, hard_gate_status "
        "FROM eval_items WHERE run_id = ?",
        (run["id"],),
    ).fetchone()
    assert tuple(item) == ("completed", 1, "passed")
    attempt = test_db.execute(
        "SELECT status, raw_observation_json FROM eval_attempts WHERE item_id = 1"
    ).fetchone()
    assert attempt[0] == "succeeded"
    assert '"status":"succeeded"' in attempt[1]
    event_types = [
        row[0]
        for row in test_db.execute(
            "SELECT event_type FROM eval_events WHERE run_id = ? ORDER BY sequence",
            (run["id"],),
        ).fetchall()
    ]
    assert event_types == ["run.started", "item.completed", "run.completed"]

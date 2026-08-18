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

def test_executor_writes_transcript_artifact_for_completed_item(test_db):
    """A completed item must materialize a durable eval_artifacts row so the
    evidence index is real (was: table never written, UI index always empty)."""
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
    artifact = test_db.execute(
        "SELECT run_id, item_id, attempt_id, artifact_type, storage_path, digest, size_bytes "
        "FROM eval_artifacts WHERE run_id = ? ORDER BY id",
        (run["id"],),
    ).fetchone()
    assert artifact is not None
    assert artifact[3] == "transcript"
    assert artifact[4]
    assert artifact[5]
    assert int(artifact[6]) > 0


def test_executor_runs_fixed_judge_for_interview_targets(test_db, monkeypatch):
    executor = _executor()
    service = _service()
    target = service.create_release(
        test_db,
        release_key="interview-agent@1.0",
        release_type="target",
        version="1.0",
        target_type="interview",
        manifest={"component": "interview-agent"},
    )
    suite_release = service.create_release(
        test_db,
        release_key="interview-suite@1.0",
        release_type="benchmark_suite",
        version="1.0",
        target_type="interview",
        judge_model="fixed-judge-model",
        manifest={"component": "suite"},
    )
    protocol = service.create_release(
        test_db,
        release_key="interview-protocol@1.0",
        release_type="eval_protocol",
        version="1.0",
        manifest={},
    )
    judge = service.create_release(
        test_db,
        release_key="interview-judge@1.0",
        release_type="judge",
        version="1.0",
        judge_model="fixed-judge-model",
        manifest={"model": "fixed-judge-model"},
    )
    harness = service.create_release(
        test_db,
        release_key="interview-harness@1.0",
        release_type="simulator_harness",
        version="1.0",
        target_type="interview",
        manifest={},
    )
    simulator = service.create_release(
        test_db,
        release_key="interview-simulator@1.0",
        release_type="candidate_simulator",
        version="1.0",
        target_type="interview",
        manifest={"model": "candidate-model"},
    )
    suite = service.create_benchmark_suite(
        test_db,
        release_id=suite_release["id"],
        suite_key="interview-suite",
        target_type="interview",
        judge_model="fixed-judge-model",
    )
    service.create_benchmark_case(
        test_db,
        suite_id=suite["id"],
        case_key="case-1",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"opening": "hello"}},
        contract={"hard_assertions": [{"id": "has_answer"}], "rubric": {"flow": {"weight": 1}}},
    )
    run = service.create_eval_run(
        test_db,
        created_by=None,
        target_release_id=target["id"],
        benchmark_suite_release_id=suite_release["id"],
        eval_protocol_release_id=protocol["id"],
        judge_release_id=judge["id"],
        simulator_harness_release_id=harness["id"],
        candidate_simulator_release_id=simulator["id"],
        replication_count=1,
        seed=11,
    )
    test_db.commit()

    class FakeAdapter:
        async def prepare(self, case_snapshot, target_release):
            return case_snapshot

        async def run(self, prepared_case, target_release):
            return {"status": "succeeded", "turns": [{"assistant": "answer"}]}

        async def observe(self, raw_result):
            return {
                "status": "succeeded",
                "payload": raw_result,
                "hard_assertions": [{"id": "has_answer", "passed": False}],
            }

    async def fake_judge(**kwargs):
        assert kwargs["judge_model"] == "fixed-judge-model"
        return {
            "judge_status": "succeeded",
            "judge_model": "fixed-judge-model",
            "score": 0.8,
            "dimensions": {"flow": {"score": 4}},
        }

    monkeypatch.setattr(executor, "judge_observation", fake_judge)
    result = asyncio.run(
        executor.execute_eval_run(
            run["id"],
            conn=test_db,
            adapter_resolver=lambda target_type: FakeAdapter(),
        )
    )

    assert result["status"] == "completed"
    item = test_db.execute(
        "SELECT judge_status, score, result_json FROM eval_items WHERE run_id = ?",
        (run["id"],),
    ).fetchone()
    assert item[0:2] == ("succeeded", 0.8)
    assert '"judge_model":"fixed-judge-model"' in item[2]


def test_executor_marks_failed_target_observation_as_failed_item(test_db):
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
        seed=12,
    )
    test_db.commit()

    class FailedAdapter:
        async def prepare(self, case_snapshot, target_release):
            return case_snapshot

        async def run(self, prepared_case, target_release):
            return {"error": "pipeline unavailable"}

        async def observe(self, raw_result):
            return {
                "status": "failed",
                "payload": {"errors": [raw_result["error"]]},
                "hard_assertions": [],
            }

    result = asyncio.run(
        executor.execute_eval_run(
            run["id"],
            conn=test_db,
            adapter_resolver=lambda target_type: FailedAdapter(),
        )
    )

    assert result["status"] == "failed"
    item = test_db.execute(
        "SELECT status FROM eval_items WHERE run_id = ?", (run["id"],)
    ).fetchone()
    assert item[0] == "failed"


def test_executor_retry_creates_next_attempt_and_replaces_failed_item(test_db):
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
        seed=14,
    )
    test_db.commit()

    class FailedAdapter:
        async def prepare(self, case_snapshot, target_release):
            return case_snapshot

        async def run(self, prepared_case, target_release):
            return {"error": "temporary failure"}

        async def observe(self, raw_result):
            return {"status": "failed", "payload": {"errors": [raw_result["error"]]}}

    first = asyncio.run(executor.execute_eval_run(run["id"], conn=test_db, adapter_resolver=lambda _: FailedAdapter()))
    assert first["status"] == "failed"

    item_id = test_db.execute("SELECT id FROM eval_items WHERE run_id = ?", (run["id"],)).fetchone()[0]
    test_db.execute(
        "UPDATE eval_items SET status = 'pending', result_json = '{}', contract_status = 'pending', hard_gate_status = 'pending', judge_status = 'pending', finished_at = NULL WHERE id = ?",
        (item_id,),
    )
    test_db.execute(
        "UPDATE eval_runs SET status = 'created', completed_items = 0, failed_items = 0, finished_at = NULL WHERE id = ?",
        (run["id"],),
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'created', completed_items = 0, failed_items = 0, finished_at = NULL WHERE id = ?",
        (run["batch_id"],),
    )
    test_db.commit()

    class SuccessfulAdapter:
        async def prepare(self, case_snapshot, target_release):
            return case_snapshot

        async def run(self, prepared_case, target_release):
            return {"answer": "recovered"}

        async def observe(self, raw_result):
            return {
                "status": "succeeded",
                "payload": raw_result,
                "hard_assertions": [],
            }

    second = asyncio.run(executor.execute_eval_run(run["id"], conn=test_db, adapter_resolver=lambda _: SuccessfulAdapter()))

    assert second["status"] == "completed"
    attempts = test_db.execute(
        "SELECT attempt_index, status FROM eval_attempts WHERE item_id = ? ORDER BY attempt_index",
        (item_id,),
    ).fetchall()
    assert [tuple(attempt) for attempt in attempts] == [(1, "failed"), (2, "succeeded")]


def test_reconcile_interrupted_run_closes_active_items_and_batch(test_db):
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
        seed=13,
    )
    item_id = test_db.execute(
        "SELECT id FROM eval_items WHERE run_id = ?", (run["id"],)
    ).fetchone()[0]
    attempt_id = test_db.execute(
        "INSERT INTO eval_attempts (item_id, attempt_index, attempt_kind) VALUES (?, 1, 'target')",
        (item_id,),
    ).lastrowid
    test_db.execute(
        "UPDATE eval_runs SET status = 'running' WHERE id = ?", (run["id"],)
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'running' WHERE id = ?", (run["batch_id"],)
    )
    test_db.execute(
        "UPDATE eval_items SET status = 'running' WHERE id = ?", (item_id,)
    )
    test_db.commit()

    result = executor.reconcile_interrupted_eval_run(
        run["id"], conn=test_db, reason="worker_timeout"
    )

    assert result["status"] == "failed"
    assert result["failure_class"] == "worker_timeout"
    item = test_db.execute(
        "SELECT status, result_json FROM eval_items WHERE id = ?", (item_id,)
    ).fetchone()
    assert item[0] == "failed"
    assert '"failure_class":"worker_timeout"' in item[1]
    attempt = test_db.execute(
        "SELECT status, failure_class FROM eval_attempts WHERE id = ?", (attempt_id,)
    ).fetchone()
    assert tuple(attempt) == ("failed", "worker_timeout")
    assert test_db.execute(
        "SELECT status FROM eval_runs WHERE id = ?", (run["id"],)
    ).fetchone()[0] == "failed"
    assert test_db.execute(
        "SELECT status FROM eval_batches WHERE id = ?", (run["batch_id"],)
    ).fetchone()[0] == "failed"

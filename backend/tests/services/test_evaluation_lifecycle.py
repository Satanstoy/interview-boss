"""Evaluation expiry, heartbeat and restart contracts."""

import datetime as dt
import importlib
import json


def _service():
    return importlib.import_module("app.services.evaluation_service")


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

    target = release("lifecycle-agent@1.0", "target", target_type="fixture")
    suite_release = release(
        "lifecycle-suite@1.0",
        "benchmark_suite",
        target_type="fixture",
        judge_model="fixed-judge",
    )
    protocol = release("lifecycle-protocol@1.0", "eval_protocol")
    judge = release("lifecycle-judge@1.0", "judge", judge_model="fixed-judge")
    harness = release("lifecycle-harness@1.0", "simulator_harness")
    simulator = release("lifecycle-simulator@1.0", "candidate_simulator")
    suite = service.create_benchmark_suite(
        conn,
        release_id=suite_release["id"],
        suite_key="lifecycle-suite",
        target_type="fixture",
        judge_model="fixed-judge",
    )
    case = service.create_benchmark_case(
        conn,
        suite_id=suite["id"],
        case_key="case-1",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"answer": "hello"}},
        contract={"hard_assertions": []},
    )
    conn.commit()
    return service, (target, suite_release, protocol, judge, harness, simulator), case


def _run(conn):
    service, context, _ = _context(conn)
    return service.create_eval_run(
        conn,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=7,
    )


def test_expire_stale_queued_run_preserves_event_and_marks_batch(test_db):
    module = importlib.import_module("app.services.evaluation_lifecycle")
    run = _run(test_db)
    test_db.execute(
        "UPDATE eval_runs SET status = 'queued', created_at = ?, last_heartbeat_at = ? WHERE id = ?",
        ("2026-08-25 00:00:00", "2026-08-25 00:00:00", run["id"]),
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'queued', created_at = ?, last_heartbeat_at = ? WHERE id = ?",
        ("2026-08-25 00:00:00", "2026-08-25 00:00:00", run["batch_id"]),
    )
    test_db.commit()

    expired = module.expire_stale_eval_runs(
        test_db,
        now=dt.datetime(2026, 8, 25, 1, 0, 0),
        queued_timeout_seconds=900,
        running_timeout_seconds=1800,
    )

    assert expired == [run["id"]]
    stored = test_db.execute(
        "SELECT status, finished_at, summary_json FROM eval_runs WHERE id = ?",
        (run["id"],),
    ).fetchone()
    assert stored["status"] == "expired"
    assert json.loads(stored["summary_json"])["expiration_reason"] == "queued_timeout"
    assert test_db.execute(
        "SELECT status FROM eval_batches WHERE id = ?", (run["batch_id"],)
    ).fetchone()[0] == "expired"
    assert test_db.execute(
        "SELECT event_type FROM eval_events WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
        (run["id"],),
    ).fetchone()[0] == "run.expired"


def test_restart_expired_run_creates_new_immutable_run(test_db):
    module = importlib.import_module("app.services.evaluation_lifecycle")
    run = _run(test_db)
    test_db.execute(
        "UPDATE eval_runs SET status = 'expired', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
        (run["id"],),
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'expired', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
        (run["batch_id"],),
    )
    test_db.commit()

    restarted = module.restart_eval_run(test_db, run["id"], created_by=1)

    assert restarted["id"] != run["id"]
    assert restarted["status"] == "created"
    assert restarted["restart_of_run_id"] == run["id"]
    assert test_db.execute(
        "SELECT status FROM eval_runs WHERE id = ?", (run["id"],)
    ).fetchone()[0] == "expired"
    assert test_db.execute(
        "SELECT COUNT(*) FROM eval_items WHERE run_id = ?", (restarted["id"],)
    ).fetchone()[0] == 1


def test_resume_run_reuses_completed_evidence_and_requeues_interrupted_items(test_db):
    module = importlib.import_module("app.services.evaluation_lifecycle")
    service, context, case = _context(test_db)
    run = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=2,
        seed=7,
    )
    items = test_db.execute(
        "SELECT id FROM eval_items WHERE run_id = ? ORDER BY id", (run["id"],)
    ).fetchall()
    completed_item_id, interrupted_item_id = (row["id"] for row in items)
    attempt_id = test_db.execute(
        """
        INSERT INTO eval_attempts
            (item_id, attempt_index, attempt_kind, status, raw_observation_json, finished_at)
        VALUES (?, 1, 'target', 'succeeded', '{\"observation\":{}}', CURRENT_TIMESTAMP)
        """,
        (completed_item_id,),
    ).lastrowid
    test_db.execute(
        """
        UPDATE eval_items
        SET status = 'completed', selected_attempt_id = ?, contract_status = 'valid',
            hard_gate_status = 'passed', judge_status = 'succeeded', score = 0.9,
            result_json = '{\"observation\":{\"status\":\"succeeded\"}}',
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (attempt_id, completed_item_id),
    )
    test_db.execute(
        "UPDATE eval_items SET status = 'cancelled', result_json = ? WHERE id = ?",
        (json.dumps({"error": "worker_cancelled"}), interrupted_item_id),
    )
    test_db.execute(
        "UPDATE eval_runs SET status = 'failed', completed_items = 1, failed_items = 0, summary_json = ? WHERE id = ?",
        (json.dumps({"failure_class": "worker_cancelled"}), run["id"]),
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'failed', completed_items = 1, failed_items = 0 WHERE id = ?",
        (run["batch_id"],),
    )
    test_db.commit()

    resumed = module.resume_eval_run(test_db, run["id"], created_by=1)

    assert resumed["id"] != run["id"]
    assert resumed["status"] == "created"
    assert resumed["resume_of_run_id"] == run["id"]
    assert resumed["completed_items"] == 1
    assert resumed["failed_items"] == 0
    new_items = test_db.execute(
        "SELECT id, status, selected_attempt_id, result_json FROM eval_items WHERE run_id = ? ORDER BY id",
        (resumed["id"],),
    ).fetchall()
    assert new_items[0]["status"] == "completed"
    assert new_items[0]["selected_attempt_id"] is not None
    assert json.loads(new_items[0]["result_json"])["observation"]["status"] == "succeeded"
    assert new_items[1]["status"] == "pending"
    assert new_items[1]["selected_attempt_id"] is None
    assert test_db.execute(
        "SELECT status, completed_items FROM eval_runs WHERE id = ?", (run["id"],)
    ).fetchone()[0:2] == ("failed", 1)
    assert test_db.execute(
        "SELECT COUNT(*) FROM eval_attempts WHERE item_id = ?", (new_items[0]["id"],)
    ).fetchone()[0] == 1
    event_types = [
        row[0]
        for row in test_db.execute(
            "SELECT event_type FROM eval_events WHERE run_id = ? ORDER BY sequence", (resumed["id"],)
        ).fetchall()
    ]
    assert event_types == ["run.created", "run.items_reused"]


def test_resume_run_is_idempotent_while_continuation_is_active(test_db):
    module = importlib.import_module("app.services.evaluation_lifecycle")
    service, context, case = _context(test_db)
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
        seed=8,
    )
    test_db.execute(
        "UPDATE eval_runs SET status = 'failed' WHERE id = ?", (run["id"],)
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'failed' WHERE id = ?", (run["batch_id"],)
    )
    test_db.commit()

    first = module.resume_eval_run(test_db, run["id"], created_by=1)
    second = module.resume_eval_run(test_db, run["id"], created_by=1)

    assert second["id"] == first["id"]
    assert second["already_exists"] is True
    assert test_db.execute(
        "SELECT COUNT(*) FROM eval_runs WHERE resume_of_run_id = ?", (run["id"],)
    ).fetchone()[0] == 1

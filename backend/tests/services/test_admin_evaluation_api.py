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
    conn.execute("UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP")
    conn.commit()
    return target, suite_release, protocol, judge, harness, simulator


def test_admin_router_exposes_control_plane_routes():
    module = _router()
    paths = {route.path for route in module.router.routes}

    assert "/api/admin/evals/overview" in paths
    assert "/api/admin/evals/capabilities" in paths
    assert "/api/admin/evals/releases" in paths
    assert "/api/admin/evals/benchmarks" in paths
    assert "/api/admin/evals/runs" in paths
    assert "/api/admin/evals/experiments" in paths
    assert "/api/admin/evals/experiments/{experiment_id}" in paths
    assert "/api/admin/evals/experiments/{experiment_id}/cancel" in paths
    assert "/api/admin/evals/experiments/{experiment_id}/events" in paths
    assert "/api/admin/evals/runs/{run_id}" in paths
    assert "/api/admin/evals/runs/{run_id}/items/{item_id}" in paths
    assert "/api/admin/evals/runs/{run_id}/cancel" in paths
    assert "/api/admin/evals/runs/{run_id}/retry-failed" in paths
    assert "/api/admin/evals/runs/{run_id}/events" in paths
    assert "/api/admin/evals/reviews" in paths


def test_capabilities_report_published_target_and_evaluation_pair(test_db, monkeypatch):
    module = _router()
    service = importlib.import_module("app.services.evaluation_service")
    target = service.create_release(
        test_db,
        release_key="capability-agent@1.0",
        release_type="target",
        version="1.0",
        target_type="interview",
        manifest={"model": "target-model"},
    )
    evaluation = service.create_release(
        test_db,
        release_key="capability-eval@1.0",
        release_type="evaluation",
        version="1.0",
        target_type="interview",
        manifest={
            "benchmark": {"suite_key": "capability-suite"},
            "judge": {"model": "judge-model"},
            "simulator_harness": {"version": "1.0"},
            "candidate_simulator": {"model": "candidate-model"},
        },
    )
    suite = service.create_benchmark_suite(
        test_db,
        release_id=evaluation["id"],
        suite_key="capability-suite",
        target_type="interview",
    )
    service.create_benchmark_case(
        test_db,
        suite_id=suite["id"],
        case_key="capability-case",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"opening": "你好"}},
        contract={"hard_assertions": []},
    )
    test_db.execute(
        "UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP"
    )
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)

    result = asyncio.run(module.capabilities({"id": 1, "is_admin": 1}))
    item = next(item for item in result["targets"] if item["target_type"] == "interview")

    assert item["adapter_available"] is True
    assert item["can_run"] is True
    assert item["target_release"]["id"] == target["id"]
    assert item["evaluation_release"]["id"] == evaluation["id"]
    assert item["case_count"] == 1


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


def test_get_run_item_returns_frozen_case_attempt_and_artifacts(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
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
    item = test_db.execute(
        "SELECT id FROM eval_items WHERE run_id = ?", (run["id"],)
    ).fetchone()
    attempt = test_db.execute(
        """
        INSERT INTO eval_attempts
            (item_id, attempt_index, attempt_kind, status, raw_observation_json, finished_at)
        VALUES (?, 1, 'target', 'succeeded', ?, CURRENT_TIMESTAMP)
        """,
        (item["id"], '{"observation":{"status":"succeeded"}}'),
    ).lastrowid
    test_db.execute(
        "UPDATE eval_items SET selected_attempt_id = ?, status = 'completed', result_json = ? WHERE id = ?",
        (attempt, '{"score":{"score":0.8}}', item["id"]),
    )
    test_db.execute(
        """
        INSERT INTO eval_artifacts
            (run_id, item_id, attempt_id, artifact_type, storage_path, digest, size_bytes)
        VALUES (?, ?, ?, 'transcript', 'evals/1/transcript.json', 'digest-1', 42)
        """,
        (run["id"], item["id"], attempt),
    )
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)
    result = asyncio.run(module.get_run_item(run["id"], item["id"], {"id": 1, "is_admin": 1}))

    assert result["item"]["id"] == item["id"]
    assert result["case"]["case_key"] == "case-1"
    assert result["case"]["input_snapshot"]["candidate_view"]["answer"] == "hello"
    assert result["attempts"][0]["raw_observation"]["observation"]["status"] == "succeeded"
    assert result["artifacts"][0]["artifact_type"] == "transcript"


def test_retry_failed_run_requeues_only_failed_items(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
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
    item_id = test_db.execute(
        "SELECT id FROM eval_items WHERE run_id = ?", (run["id"],)
    ).fetchone()[0]
    attempt_id = test_db.execute(
        """
        INSERT INTO eval_attempts
            (item_id, attempt_index, attempt_kind, status, failure_class, error_message, finished_at)
        VALUES (?, 1, 'target', 'failed', 'target_execution', 'timeout', CURRENT_TIMESTAMP)
        """,
        (item_id,),
    ).lastrowid
    test_db.execute(
        "UPDATE eval_items SET status = 'failed', selected_attempt_id = ? WHERE id = ?",
        (attempt_id, item_id),
    )
    test_db.execute(
        "UPDATE eval_runs SET status = 'failed', failed_items = 1 WHERE id = ?", (run["id"],)
    )
    test_db.execute(
        "UPDATE eval_batches SET status = 'failed', failed_items = 1 WHERE id = ?", (run["batch_id"],)
    )
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)
    monkeypatch.setattr(module, "enqueue_eval_run_job", lambda run_id: None)

    async def fake_enqueue(run_id):
        return None

    monkeypatch.setattr(module, "enqueue_eval_run_job", fake_enqueue)
    result = asyncio.run(module.retry_failed_run(run["id"], {"id": 1, "is_admin": 1}))

    assert result["status"] == "queued"
    item = test_db.execute(
        "SELECT status, selected_attempt_id, result_json FROM eval_items WHERE id = ?",
        (item_id,),
    ).fetchone()
    assert item[0] == "pending"
    assert item[1] is None
    assert item[2] == "{}"
    assert test_db.execute(
        "SELECT status FROM eval_runs WHERE id = ?", (run["id"],)
    ).fetchone()[0] == "queued"
    event_types = [
        row[0]
        for row in test_db.execute(
            "SELECT event_type FROM eval_events WHERE run_id = ? ORDER BY sequence",
            (run["id"],),
        ).fetchall()
    ]
    assert event_types[-2:] == ["run.retry_requested", "run.queued"]


def test_create_experiment_creates_child_runs_for_selected_target_types(test_db, monkeypatch):
    module = _router()
    catalog = importlib.import_module("app.evaluation.benchmark_catalog")
    catalog.sync_builtin_benchmarks(test_db)
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)

    async def fake_enqueue(run_id):
        return None

    monkeypatch.setattr(module, "enqueue_eval_run_job", fake_enqueue)
    body = module.CreateEvalExperimentRequest(
        target_types=["interview", "resume_analysis"],
        replication_count=1,
        seed=23,
        environment_fingerprint="frontend-e2e",
        comparison_group="frontend-all-1",
    )

    result = asyncio.run(module.create_experiment(body, {"id": 1, "is_admin": 1}))

    assert result["status"] == "queued"
    assert len(result["runs"]) == 2
    assert {item["target_type"] for item in result["runs"]} == {"interview", "resume_analysis"}
    assert test_db.execute(
        "SELECT COUNT(*) FROM eval_experiment_runs WHERE experiment_id = ?",
        (result["experiment_id"],),
    ).fetchone()[0] == 2


def test_get_experiment_aggregates_child_run_progress(test_db, monkeypatch):
    module = _router()
    catalog = importlib.import_module("app.evaluation.benchmark_catalog")
    catalog.sync_builtin_benchmarks(test_db)
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)
    monkeypatch.setattr(module, "enqueue_eval_run_job", lambda run_id: None)

    async def fake_enqueue(run_id):
        return None

    monkeypatch.setattr(module, "enqueue_eval_run_job", fake_enqueue)
    body = module.CreateEvalExperimentRequest(
        target_types=["interview", "resume_analysis"],
        replication_count=1,
        seed=23,
    )
    created = asyncio.run(module.create_experiment(body, {"id": 1, "is_admin": 1}))
    run_ids = [item["run_id"] for item in created["runs"]]
    test_db.execute(
        "UPDATE eval_runs SET status = 'completed', completed_items = total_items WHERE id = ?",
        (run_ids[0],),
    )
    test_db.execute(
        "UPDATE eval_items SET status = 'completed', contract_status = 'valid', hard_gate_status = 'passed', judge_status = 'succeeded' WHERE run_id = ?",
        (run_ids[0],),
    )
    test_db.execute(
        "UPDATE eval_runs SET status = 'failed', failed_items = total_items WHERE id = ?",
        (run_ids[1],),
    )
    test_db.execute(
        "UPDATE eval_items SET status = 'failed' WHERE run_id = ?",
        (run_ids[1],),
    )
    test_db.commit()

    result = asyncio.run(module.get_experiment(created["experiment_id"], {"id": 1, "is_admin": 1}))

    assert result["status"] == "failed"
    assert result["total_runs"] == 2
    assert result["completed_runs"] == 1
    assert result["failed_runs"] == 1
    assert result["total_items"] == sum(item["total_items"] for item in result["runs"])
    assert result["completed_items"] == result["runs"][0]["total_items"]
    assert result["failed_items"] == result["runs"][1]["total_items"]
    assert result["runs"][0]["quality_status"] == "passed"
    assert result["runs"][1]["quality_status"] == "failed"
    event_types = [
        row[0]
        for row in test_db.execute(
            "SELECT event_type FROM eval_experiment_events WHERE experiment_id = ? ORDER BY sequence",
            (created["experiment_id"],),
        ).fetchall()
    ]
    assert "experiment.progress" in event_types


def test_cancel_experiment_cancels_queued_children(test_db, monkeypatch):
    module = _router()
    catalog = importlib.import_module("app.evaluation.benchmark_catalog")
    catalog.sync_builtin_benchmarks(test_db)
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)

    async def fake_enqueue(run_id):
        return None

    monkeypatch.setattr(module, "enqueue_eval_run_job", fake_enqueue)
    created = asyncio.run(
        module.create_experiment(
            module.CreateEvalExperimentRequest(target_types=["interview"], replication_count=1),
            {"id": 1, "is_admin": 1},
        )
    )

    result = asyncio.run(module.cancel_experiment(created["experiment_id"], {"id": 1, "is_admin": 1}))

    assert result["status"] == "cancelled"
    assert result["runs"][0]["status"] == "cancelled"


def test_create_run_accepts_target_and_evaluation_release(test_db, monkeypatch):
    module = _router()
    service = importlib.import_module("app.services.evaluation_service")
    target = service.create_release(
        test_db,
        release_key="dual-agent@1.0",
        release_type="target",
        version="1.0",
        target_type="interview",
        manifest={"workflow": "v1"},
    )
    evaluation = service.create_release(
        test_db,
        release_key="dual-eval@1.0",
        release_type="evaluation",
        version="1.0",
        target_type="interview",
        manifest={
            "benchmark": {"suite_key": "dual-suite"},
            "judge": {"model": "judge-v1", "temperature": 0},
            "simulator_harness": {"version": "harness-v1"},
            "candidate_simulator": {"model": "candidate-v1"},
        },
    )
    suite = service.create_benchmark_suite(
        test_db,
        release_id=evaluation["id"],
        suite_key="dual-suite",
        target_type="interview",
    )
    service.create_benchmark_case(
        test_db,
        suite_id=suite["id"],
        case_key="dual-case",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"opening": "你好"}},
        contract={"hard_assertions": []},
    )
    test_db.execute(
        "UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP"
    )
    test_db.commit()
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)

    async def sync_run_db(func):
        return func()

    monkeypatch.setattr(module, "run_db", sync_run_db)

    async def fail_dispatch(run_id):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(module, "enqueue_eval_run_job", fail_dispatch)
    body = module.CreateEvalRunRequest(
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        replication_count=1,
        seed=9,
    )

    result = asyncio.run(module.create_run(body, {"id": 1, "is_admin": 1}))

    assert result["status"] == "created"
    stored = test_db.execute(
        "SELECT evaluation_release_id, snapshot_json FROM eval_runs WHERE id = ?",
        (result["run_id"],),
    ).fetchone()
    assert stored[0] == evaluation["id"]
    assert '"release_key":"dual-eval@1.0"' in stored[1]


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


def test_overview_aggregates_human_ab_evidence(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)
    service = importlib.import_module("app.services.evaluation_service")
    run_a = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=30,
        comparison_group="release-ab-1",
    )
    run_b = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=31,
        comparison_group="release-ab-1",
    )
    test_db.execute(
        "UPDATE eval_items SET status = 'completed', score = CASE run_id WHEN ? THEN 0.8 ELSE 0.6 END WHERE run_id IN (?, ?)",
        (run_a["id"], run_a["id"], run_b["id"]),
    )
    for choice in ("a", "a", "b"):
        test_db.execute(
            "INSERT INTO eval_human_reviews "
            "(comparison_group, run_a_id, run_b_id, item_key, reviewer_id, choice) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("release-ab-1", run_a["id"], run_b["id"], f"case-1#{choice}", 1, choice),
        )
    test_db.commit()

    result = asyncio.run(module.overview({"id": 1, "is_admin": 1}))

    summary = result["human_reviews"]
    assert summary["total"] == 3
    assert summary["comparison_groups"][0]["comparison_group"] == "release-ab-1"
    assert summary["comparison_groups"][0]["a_wins"] == 2
    assert summary["comparison_groups"][0]["b_wins"] == 1
    assert summary["comparison_groups"][0]["run_a_avg_score"] == 0.8
    assert summary["comparison_groups"][0]["run_b_avg_score"] == 0.6


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


def test_human_review_persists_ab_choice_and_dimensions(test_db, monkeypatch):
    module = _router()
    context = _context(test_db)
    monkeypatch.setattr(module, "get_db_connection", lambda: test_db)
    service = importlib.import_module("app.services.evaluation_service")
    run_a = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=20,
        comparison_group="release-ab-1",
    )
    run_b = service.create_eval_run(
        test_db,
        created_by=1,
        target_release_id=context[0]["id"],
        benchmark_suite_release_id=context[1]["id"],
        eval_protocol_release_id=context[2]["id"],
        judge_release_id=context[3]["id"],
        simulator_harness_release_id=context[4]["id"],
        candidate_simulator_release_id=context[5]["id"],
        replication_count=1,
        seed=21,
        comparison_group="release-ab-1",
    )
    test_db.execute(
        "UPDATE eval_items SET status = 'completed' WHERE run_id IN (?, ?)",
        (run_a["id"], run_b["id"]),
    )
    test_db.commit()

    body = module.CreateHumanReviewRequest(
        comparison_group="release-ab-1",
        run_a_id=run_a["id"],
        run_b_id=run_b["id"],
        item_key="case-1#1",
        choice="a",
        dimensions={"flow": "a", "evidence": "tie"},
        comment="A 的追问更自然",
    )
    result = asyncio.run(module.create_review(body, {"id": 1, "is_admin": 1}))

    assert result["choice"] == "a"
    assert result["dimensions"]["flow"] == "a"
    assert result["reviewer_id"] == 1
    rows = asyncio.run(
        module.list_reviews(
            comparison_group="release-ab-1",
            limit=20,
            admin={"id": 1, "is_admin": 1},
        )
    )
    assert len(rows["reviews"]) == 1
    assert rows["reviews"][0]["item_key"] == "case-1#1"

    with pytest.raises(module.HTTPException) as exc_info:
        asyncio.run(
            module.create_review(
                module.CreateHumanReviewRequest(
                    comparison_group="release-ab-1",
                    run_a_id=run_a["id"],
                    run_b_id=run_b["id"],
                    item_key="missing-case#1",
                    choice="tie",
                ),
                {"id": 1, "is_admin": 1},
            )
        )
    assert exc_info.value.status_code == 400

"""评测控制平面生命周期服务契约。"""

import importlib
import json

import pytest


def _service():
    try:
        return importlib.import_module("app.services.evaluation_service")
    except ModuleNotFoundError:
        pytest.fail("app.services.evaluation_service 尚未实现")


def _release(conn, key, release_type, version="1.0", **extra):
    return _service().create_release(
        conn,
        release_key=key,
        release_type=release_type,
        version=version,
        manifest={"key": key, "version": version},
        **extra,
    )


def _evaluation_context(conn):
    target = _release(conn, "interview-agent@1.0", "target", target_type="interview")
    suite_release = _release(
        conn,
        "interview-e2e-suite@1.0",
        "benchmark_suite",
        target_type="interview",
        judge_model="judge-fixed-1",
    )
    protocol = _release(conn, "eval-protocol@1.0", "eval_protocol")
    judge = _release(
        conn,
        "judge@1.0",
        "judge",
        judge_model="judge-fixed-1",
    )
    harness = _release(conn, "interview-harness@1.0", "simulator_harness")
    simulator = _release(conn, "candidate-simulator@1.0", "candidate_simulator")
    suite = _service().create_benchmark_suite(
        conn,
        release_id=suite_release["id"],
        suite_key="interview-e2e-suite",
        target_type="interview",
        judge_model="judge-fixed-1",
    )
    case = _service().create_benchmark_case(
        conn,
        suite_id=suite["id"],
        case_key="greeting-role-adherence",
        scenario_key="greeting_role_adherence",
        input_snapshot={"candidate_view": {"name": "Candidate"}},
        contract={
            "facts": ["candidate is interviewing for backend role"],
            "hard_assertions": ["asks first question before closing"],
            "rubric": {"quality": {"weight": 1}},
        },
    )
    conn.commit()
    return {
        "target": target,
        "suite": suite_release,
        "protocol": protocol,
        "judge": judge,
        "harness": harness,
        "simulator": simulator,
        "case": case,
    }


def test_create_eval_run_freezes_context_and_materializes_items(test_db):
    service = _service()
    context = _evaluation_context(test_db)

    run = service.create_eval_run(
        test_db,
        created_by=None,
        target_release_id=context["target"]["id"],
        benchmark_suite_release_id=context["suite"]["id"],
        eval_protocol_release_id=context["protocol"]["id"],
        judge_release_id=context["judge"]["id"],
        simulator_harness_release_id=context["harness"]["id"],
        candidate_simulator_release_id=context["simulator"]["id"],
        replication_count=2,
        seed=17,
    )

    assert run["status"] == "created"
    assert run["total_items"] == 2
    assert run["batch_fingerprint"]
    assert run["judge_release_id"] == context["judge"]["id"]
    assert run["simulator_harness_release_id"] == context["harness"]["id"]

    items = test_db.execute(
        "SELECT case_id, replication_index, seed, status "
        "FROM eval_items WHERE run_id = ? ORDER BY replication_index",
        (run["id"],),
    ).fetchall()
    assert [(row[0], row[1], row[3]) for row in items] == [
        (context["case"]["id"], 1, "pending"),
        (context["case"]["id"], 2, "pending"),
    ]


def test_append_event_allocates_monotonic_sequence_for_resumable_sse(test_db):
    service = _service()
    context = _evaluation_context(test_db)
    run = service.create_eval_run(
        test_db,
        created_by=None,
        target_release_id=context["target"]["id"],
        benchmark_suite_release_id=context["suite"]["id"],
        eval_protocol_release_id=context["protocol"]["id"],
        judge_release_id=context["judge"]["id"],
        simulator_harness_release_id=context["harness"]["id"],
        candidate_simulator_release_id=context["simulator"]["id"],
        replication_count=1,
        seed=17,
    )

    first = service.append_event(test_db, run["id"], "run.created", {"status": "created"})
    second = service.append_event(test_db, run["id"], "run.queued", {"status": "queued"})
    test_db.commit()

    assert (first["sequence"], second["sequence"]) == (1, 2)
    events = service.list_events_after(test_db, run["id"], after_sequence=1)
    assert events == [
        {
            "sequence": 2,
            "event_type": "run.queued",
            "payload": {"status": "queued"},
        }
    ]


def test_release_manifest_digest_is_stable_and_duplicate_key_is_rejected(test_db):
    service = _service()
    manifest = {"target": "interview", "prompt": "fixed", "sampling": {"temperature": 0}}
    first = service.create_release(
        test_db,
        release_key="judge@1.0",
        release_type="judge",
        version="1.0",
        manifest=manifest,
        judge_model="fixed-judge-model",
    )
    test_db.commit()

    assert first["manifest_digest"] == service.manifest_digest(manifest)
    stored = json.loads(
        test_db.execute(
            "SELECT manifest_json FROM eval_releases WHERE id = ?", (first["id"],)
        ).fetchone()[0]
    )
    assert stored == manifest

    with pytest.raises(ValueError, match="release_key 已存在"):
        service.create_release(
            test_db,
            release_key="judge@1.0",
            release_type="judge",
            version="1.0",
            manifest=manifest,
        )

"""双版本轴和模拟面试评测指标的第一批契约测试。"""

import importlib
import asyncio


def _service():
    return importlib.import_module("app.services.evaluation_service")


def test_builtin_catalog_publishes_one_target_and_one_evaluation_release_1_0(test_db):
    catalog = importlib.import_module("app.evaluation.benchmark_catalog")

    result = catalog.sync_builtin_benchmarks(test_db)
    rows = test_db.execute(
        "SELECT release_key, release_type, target_type, version, status "
        "FROM eval_releases ORDER BY release_key"
    ).fetchall()

    assert result["releases"] == 10
    actual = {(row[0], row[1], row[2], row[3], row[4]) for row in rows}
    assert {
        ("interview-agent@1.0", "target", "interview", "1.0", "published"),
        ("interview-eval@1.0", "evaluation", "interview", "1.0", "published"),
        ("experience-extraction@1.0", "target", "experience_extraction", "1.0", "published"),
        ("experience-extraction-eval@1.0", "evaluation", "experience_extraction", "1.0", "published"),
        ("jd-extraction@1.0", "target", "jd_extraction", "1.0", "published"),
        ("jd-extraction-eval@1.0", "evaluation", "jd_extraction", "1.0", "published"),
        ("resume-analysis@1.0", "target", "resume_analysis", "1.0", "published"),
        ("resume-analysis-eval@1.0", "evaluation", "resume_analysis", "1.0", "published"),
        ("question-tagging@1.0", "target", "question_tagging", "1.0", "published"),
        ("question-tagging-eval@1.0", "evaluation", "question_tagging", "1.0", "published"),
    } <= actual
    manifest = _service()._decode_manifest(
        test_db.execute(
            "SELECT manifest_json FROM eval_releases WHERE release_key = 'interview-eval@1.0'"
        ).fetchone()[0]
    )
    assert {"benchmark", "protocol", "judge", "simulator_harness", "candidate_simulator"} <= set(manifest)
    assert all(
        manifest[component]["version"] == "1.0"
        for component in (
            "benchmark",
            "protocol",
            "judge",
            "simulator_harness",
            "candidate_simulator",
            "tool_evaluation",
            "intent_evaluation",
            "retrieval",
            "runtime",
        )
    )
    tool_case = next(
        case for case in manifest["benchmark"]["cases"] if case["case_key"] == "tool_timing"
    )
    assert tool_case["contract"]["tool_expectations"]["required_tools"] == [
        "search_questions"
    ]
    assert tool_case["contract"]["intent_expectations"]


def test_eval_run_binds_evaluation_release_and_resolved_snapshot(test_db):
    service = _service()
    target = service.create_release(
        test_db,
        release_key="interview-agent@1.0",
        release_type="target",
        version="1.0",
        target_type="interview",
        manifest={"model": "target-model", "workflow": "interview"},
    )
    evaluation = service.create_release(
        test_db,
        release_key="interview-eval@1.0",
        release_type="evaluation",
        version="1.0",
        target_type="interview",
        manifest={
            "benchmark": {"suite_key": "interview-e2e"},
            "protocol": {"replication_count": 2},
            "judge": {"model": "judge-model", "temperature": 0},
            "simulator_harness": {"max_turns": 4},
            "candidate_simulator": {"model": "candidate-model"},
        },
    )
    suite = service.create_benchmark_suite(
        test_db,
        release_id=evaluation["id"],
        suite_key="interview-e2e",
        target_type="interview",
        judge_model="judge-model",
    )
    service.create_benchmark_case(
        test_db,
        suite_id=suite["id"],
        case_key="tool-and-intent",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"opening": "你好"}},
        contract={"hard_assertions": [], "rubric": {"quality": {"weight": 1}}},
    )
    service.create_benchmark_case(
        test_db,
        suite_id=suite["id"],
        case_key="not-selected",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"opening": "不应执行"}},
        contract={"hard_assertions": [], "rubric": {"quality": {"weight": 1}}},
    )
    test_db.commit()

    run = service.create_eval_run(
        test_db,
        created_by=None,
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        replication_count=2,
        seed=17,
        case_keys=["tool-and-intent"],
    )

    assert run["evaluation_release_id"] == evaluation["id"]
    snapshot = service._decode_manifest(run["snapshot_json"])
    assert snapshot["target_release"]["release_key"] == "interview-agent@1.0"
    assert snapshot["evaluation_release"]["release_key"] == "interview-eval@1.0"
    assert snapshot["resolved"]["replication_count"] == 2
    assert snapshot["resolved"]["case_ids"] == [snapshot["cases"][0]["id"]]
    assert snapshot["cases"][0]["case_key"] == "tool-and-intent"
    assert snapshot["cases"][0]["contract"]["rubric"]["quality"]["weight"] == 1


def test_interview_trace_scores_tool_calls_and_intent_alignment():
    scoring = importlib.import_module("app.evaluation.tool_scoring")
    turns = [
        {
            "turn": 1,
            "user": "我做过 RAG 系统",
            "assistant": "请具体介绍检索链路。",
            "metadata": {
                "intent": "interview_question",
                "classify_result": {
                    "intent": "interview_question",
                    "should_retrieve": True,
                    "requires_bank_question": True,
                },
                "turn_intent": {
                    "strategy": "deep_dive",
                    "tool_intent": {"requires_question_bank": True},
                },
                "selected_question": {"id": 101, "question": "请具体介绍检索链路。"},
                "question_source": "search",
                "tool_calls_trace": [
                    {
                        "tool_name": "search_questions",
                        "ok": True,
                        "result_count": 3,
                        "elapsed_ms": 42,
                    }
                ],
            },
            "events": [],
        },
    ]
    contract = {
        "tool_expectations": {
            "required_tools": ["search_questions"],
            "min_calls": 1,
            "max_calls": 2,
            "max_failed_calls": 0,
            "require_result_used": True,
        },
        "intent_expectations": [
            {
                "turn": 1,
                "expected_intent": "interview_question",
                "expected_strategy": "deep_dive",
                "requires_question_bank": True,
            }
        ],
    }

    result = scoring.evaluate_interview_trace(turns, contract)

    assert result["tool_metrics"]["call_count"] == 1
    assert result["tool_metrics"]["required_tools_missing"] == []
    assert result["intent_metrics"]["evaluated_count"] == 1
    assert result["intent_metrics"]["failed_count"] == 0
    assert {item["id"] for item in result["assertions"]} == {
        "tool_calls_valid",
        "tool_result_used",
        "intent_trace_complete",
        "intent_alignment",
    }
    assert all(item["passed"] for item in result["assertions"])


def test_interview_adapter_persists_tool_and_intent_metrics_in_observation():
    adapter_module = importlib.import_module("app.evaluation.interview_adapter")
    adapter = adapter_module.InterviewE2EAdapter()
    contract = {
        "tool_expectations": {"required_tools": ["search_questions"], "min_calls": 1},
        "intent_expectations": [
            {"turn": 1, "expected_intent": "interview_question"}
        ],
    }
    raw_result = {
        "status": "succeeded",
        "conversation_id": "eval-conversation",
        "errors": [],
        "turns": [
            {
                "turn": 1,
                "assistant": "继续介绍你的检索方案。",
                "events": [],
                "metadata": {
                    "intent": "interview_question",
                    "classify_result": {"intent": "interview_question"},
                    "tool_calls_trace": [
                        {"tool_name": "search_questions", "ok": True, "result_count": 2}
                    ],
                },
            }
        ],
        "contract": contract,
    }

    observation = asyncio.run(adapter.observe(raw_result))

    assert observation["payload"]["tool_metrics"]["call_count"] == 1
    assert observation["payload"]["intent_metrics"]["failed_count"] == 0
    assert {item["id"] for item in observation["hard_assertions"]} >= {
        "tool_calls_valid",
        "intent_alignment",
    }


def test_interview_adapter_passes_target_model_into_production_pipeline(monkeypatch):
    adapter_module = importlib.import_module("app.evaluation.interview_adapter")
    adapter = adapter_module.InterviewE2EAdapter()
    monkeypatch.setattr(
        adapter_module.chat_service,
        "create_conversation",
        lambda **kwargs: {"id": "eval-conversation"},
    )
    captured = {}

    async def fake_turn(*args, **kwargs):
        captured["model"] = kwargs["model"]
        return {"assistant": "结束", "events": [], "metadata": {}}

    monkeypatch.setattr(adapter, "_run_interviewer_turn", fake_turn)

    result = asyncio.run(
        adapter.run(
            {
                "candidate_view": {"opening": "你好", "max_turns": 1},
                "harness_context": {"max_turns": 1},
                "contract": {},
                "target_release_key": "interview-agent@1.0",
                "behavior_injections": {},
            },
            {"release_key": "interview-agent@1.0", "manifest": {"model": "target-v1"}},
        )
    )

    assert result["status"] == "succeeded"
    assert captured["model"] == "target-v1"


def test_executor_reads_judge_harness_and_simulator_from_run_snapshot(test_db, monkeypatch):
    service = _service()
    executor = importlib.import_module("app.services.evaluation_executor")
    target = service.create_release(
        test_db,
        release_key="interview-agent@1.0",
        release_type="target",
        version="1.0",
        target_type="interview",
        manifest={"workflow": "interview-v1"},
    )
    evaluation = service.create_release(
        test_db,
        release_key="interview-eval@1.0",
        release_type="evaluation",
        version="1.0",
        target_type="interview",
        manifest={
            "benchmark": {"suite_key": "interview-e2e"},
            "protocol": {"replication_count": 1},
            "judge": {"model": "judge-snapshot-v1", "temperature": 0},
            "simulator_harness": {"max_turns": 6, "version": "harness-snapshot-v1"},
            "candidate_simulator": {"model": "candidate-snapshot-v1", "temperature": 0.2},
            "tool_evaluation": {"enabled": True},
            "intent_evaluation": {"enabled": True},
            "retrieval": {"embedding_model": "BAAI/bge-m3"},
        },
    )
    suite = service.create_benchmark_suite(
        test_db,
        release_id=evaluation["id"],
        suite_key="interview-e2e",
        target_type="interview",
        judge_model="judge-snapshot-v1",
    )
    service.create_benchmark_case(
        test_db,
        suite_id=suite["id"],
        case_key="snapshot-case",
        scenario_key="smoke",
        input_snapshot={"candidate_view": {"opening": "你好"}},
        contract={"rubric": {"quality": {"weight": 1}}},
    )
    run = service.create_eval_run(
        test_db,
        created_by=None,
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        replication_count=1,
        seed=23,
    )
    test_db.commit()

    observed_target_release = {}

    class FakeAdapter:
        async def prepare(self, case_snapshot, target_release):
            observed_target_release.update(target_release)
            return case_snapshot

        async def run(self, prepared_case, target_release):
            return {"answer": "snapshot answer"}

        async def observe(self, raw_result):
            return {
                "status": "succeeded",
                "payload": {
                    **raw_result,
                    "tool_metrics": {"call_count": 2, "failed_call_count": 1, "result_used": True},
                    "intent_metrics": {
                        "observed_turn_count": 3,
                        "intent_coverage": 1.0,
                        "accuracy": 0.75,
                    },
                },
                "hard_assertions": [],
            }

    async def fake_judge(**kwargs):
        assert kwargs["judge_model"] == "judge-snapshot-v1"
        return {
            "judge_status": "succeeded",
            "judge_model": kwargs["judge_model"],
            "score": 0.75,
            "dimensions": {"quality": {"score": 4}},
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
    assert observed_target_release["judge_model"] == "judge-snapshot-v1"
    assert observed_target_release["harness_manifest"]["version"] == "harness-snapshot-v1"
    assert observed_target_release["candidate_simulator_manifest"]["model"] == "candidate-snapshot-v1"
    item = test_db.execute(
        "SELECT judge_status, score, result_json FROM eval_items WHERE run_id = ?",
        (run["id"],),
    ).fetchone()
    assert item[0:2] == ("succeeded", 0.75)
    summary = service._decode_manifest(
        test_db.execute("SELECT summary_json FROM eval_runs WHERE id = ?", (run["id"],)).fetchone()[0]
    )
    assert summary["metric_summary"]["tool"]["failed_call_count"] == 1
    assert summary["metric_summary"]["intent"]["accuracy"] == 0.75

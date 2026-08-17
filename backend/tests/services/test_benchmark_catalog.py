"""Git-versioned evals/ Benchmark catalog contract."""

import importlib

import pytest


EXPECTED_CASES = {
    "long_session_mid",
    "long_session_senior",
    "long_session_jd",
    "error_correction",
    "early_close_guard",
    "proper_end",
    "insufficient_evidence",
    "counter_question",
    "greeting_role_adherence",
    "tool_timing",
    "natural_closing",
    "counter_question_flow",
}


def _catalog():
    try:
        return importlib.import_module("app.evaluation.benchmark_catalog")
    except ModuleNotFoundError:
        pytest.fail("app.evaluation.benchmark_catalog 尚未实现")


def test_interview_e2e_suite_1_0_contains_structured_cases():
    catalog = _catalog()
    suite = catalog.load_suite_definition("interview-e2e-suite@1.0")

    assert suite["release_key"] == "interview-e2e-suite@1.0"
    assert suite["target_type"] == "interview"
    assert suite["judge_model"]
    assert {case["case_key"] for case in suite["cases"]} == EXPECTED_CASES

    required = {
        "facts",
        "actions",
        "boundaries",
        "quality_requirements",
        "hard_assertions",
        "rubric",
    }
    for case in suite["cases"]:
        assert required <= set(case["contract"])
        assert case["input_snapshot"]["candidate_view"]
        assert "hard_assertions" not in case["input_snapshot"]["candidate_view"]
        assert "rubric" not in case["input_snapshot"]["candidate_view"]


def test_sync_builtin_suite_uses_configured_model_for_candidate_simulator(test_db, monkeypatch):
    catalog = _catalog()
    monkeypatch.delenv("CANDIDATE_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL_NAME", "mimo-v2.5-pro")

    catalog.sync_builtin_benchmarks(test_db)

    manifest = test_db.execute(
        "SELECT manifest_json FROM eval_releases WHERE release_key = 'candidate-simulator@1.0'"
    ).fetchone()[0]
    assert '"model":"mimo-v2.5-pro"' in manifest


def test_sync_builtin_suite_versions_legacy_placeholder_candidate_simulator(test_db, monkeypatch):
    catalog = _catalog()
    service = importlib.import_module("app.services.evaluation_service")
    legacy = service.create_release(
        test_db,
        release_key="candidate-simulator@1.0",
        release_type="candidate_simulator",
        version="1.0",
        target_type="interview",
        manifest={"component": "candidate-simulator", "version": "1.0", "model": "candidate-simulator-model"},
    )
    test_db.execute(
        "UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP WHERE id = ?",
        (legacy["id"],),
    )
    test_db.commit()
    monkeypatch.delenv("CANDIDATE_LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_MODEL_NAME", "mimo-v2.5-pro")

    catalog.sync_builtin_benchmarks(test_db)

    versions = test_db.execute(
        "SELECT release_key, version, manifest_json FROM eval_releases "
        "WHERE release_type = 'candidate_simulator' ORDER BY version"
    ).fetchall()
    assert [row[0] for row in versions] == ["candidate-simulator@1.0", "candidate-simulator@1.1"]
    assert '"model":"candidate-simulator-model"' in versions[0][2]
    assert '"model":"mimo-v2.5-pro"' in versions[1][2]


def test_sync_builtin_suite_records_judge_model_and_cases(test_db):
    catalog = _catalog()

    result = catalog.sync_builtin_benchmarks(test_db)
    test_db.commit()

    assert result == {"suites": 1, "cases": 12, "releases": 6}
    suite = test_db.execute(
        "SELECT s.judge_model, r.status FROM eval_benchmark_suites s "
        "JOIN eval_releases r ON r.id = s.release_id"
    ).fetchone()
    assert tuple(suite) == ("fixed-judge-model", "published")
    assert test_db.execute("SELECT COUNT(*) FROM eval_benchmark_cases").fetchone()[0] == 12

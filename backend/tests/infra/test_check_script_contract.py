"""Prevent the daily check from hiding already-cleared regressions."""

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "check.sh"


def test_green_regression_suite_is_blocking():
    source = SCRIPT.read_text()

    assert 'run_blocking "backend full tests"' in source
    assert 'run_nonblocking "backend full tests"' not in source
    full_tests = source.split('run_blocking "backend full tests"', 1)[1].split(
        "local schema_source_commit", 1
    )[0]
    assert "backend/tests" in full_tests
    assert "backend/tests/bank backend/tests/chat" not in full_tests


def test_frontend_lint_and_mypy_baseline_are_blocking():
    source = SCRIPT.read_text()

    assert 'run_blocking "frontend eslint"' in source
    assert 'run_blocking "backend mypy baseline"' in source
    assert "check_mypy_baseline.sh" in source


def test_backend_schema_docs_are_checked_in_the_same_runtime():
    source = SCRIPT.read_text()

    assert 'run_blocking "schema docs freshness"' in source
    assert "generate_schema_docs.py" in source

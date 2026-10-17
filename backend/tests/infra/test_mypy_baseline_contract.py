"""Mypy debt is allowed only as a frozen, non-growing baseline."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/check_mypy_baseline.sh"
BASELINE = ROOT / "scripts/mypy_baseline.txt"
CHECK = ROOT / "scripts/check.sh"


def test_mypy_baseline_gate_has_a_numeric_budget_and_failure_path():
    source = SCRIPT.read_text()

    assert BASELINE.read_text().strip().isdigit()
    assert "Found" in source
    assert "MYPY_BASELINE" in source
    assert "exit 1" in source


def test_audit_runs_the_mypy_baseline_gate():
    assert "check_mypy_baseline.sh" in CHECK.read_text()

import subprocess
import sys
import importlib.util
from pathlib import Path


def _load_verifier(monkeypatch):
    monkeypatch.setenv("RUN_REAL_INTERVIEW_DISTRIBUTION_E2E", "1")
    path = Path("backend/scripts/verify_interview_distribution_e2e.py")
    spec = importlib.util.spec_from_file_location("distribution_e2e_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_verifier_refuses_to_run_without_explicit_opt_in():
    result = subprocess.run(
        [sys.executable, "backend/scripts/verify_interview_distribution_e2e.py"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode != 0
    assert "RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1" in result.stderr


def test_runtime_alignment_rejects_unbound_or_mismatched_primary_events(monkeypatch):
    verifier = _load_verifier(monkeypatch)
    plan = {
        "plan_id": "plan-1",
        "target_question_count": 2,
        "soft_target_counts": {"knowledge_probe": 1, "system_design": 1},
    }
    execution = {
        "status": "completed",
        "actual_primary_count": 2,
        "actual_counts": {"knowledge_probe": 1, "system_design": 1},
    }
    messages = [
        {
            "role": "assistant",
            "metadata": {
                "selected_question": {"id": 1},
                "coverage_events": [
                    {
                        "plan_id": "plan-1",
                        "question_type": "knowledge_probe",
                        "counts_toward_target": True,
                        "confidence": "high",
                    }
                ],
            },
        },
        {
            "role": "assistant",
            "metadata": {
                "selected_question": None,
                "coverage_events": [
                    {
                        "plan_id": "plan-1",
                        "question_type": "system_design",
                        "counts_toward_target": True,
                        "confidence": "medium",
                    }
                ],
            },
        },
    ]

    result = verifier._evaluate_runtime_alignment(plan, execution, messages)

    assert result["passed"] is False
    assert "not bank-bound" in result["errors"][0]

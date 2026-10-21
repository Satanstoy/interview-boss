import subprocess
import sys
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


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


@pytest.mark.parametrize("job_position", ["后端开发", "Agent & RAG"])
def test_verifier_encodes_job_position(monkeypatch, tmp_path, job_position):
    verifier = _load_verifier(monkeypatch)
    requested_urls = []

    def request_json(method, url, token):
        requested_urls.append(url)
        return {"distribution": {name: 0.2 for name in verifier._CANONICAL_TYPES}}

    monkeypatch.setattr(verifier, "_request_json", request_json)
    monkeypatch.setattr(sys, "argv", [
        "verifier", "--job-position", job_position,
        "--report", str(tmp_path / "report.json"),
    ])

    assert verifier.main() == 0
    assert requested_urls[0].isascii()
    assert parse_qs(urlsplit(requested_urls[0]).query)["job_position"] == [job_position]


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

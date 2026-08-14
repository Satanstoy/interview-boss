"""Load Git-versioned Benchmark definitions and seed their relational index."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.services.evaluation_service import create_benchmark_case, create_benchmark_suite, create_release

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "evals" / "suites" / "interview-e2e" / "1.0"


def load_suite_definition(release_key: str) -> dict[str, Any]:
    if release_key != "interview-e2e-suite@1.0":
        raise ValueError(f"未知 Benchmark Suite: {release_key}")
    suite = json.loads((SUITE_ROOT / "suite.json").read_text(encoding="utf-8"))
    cases = []
    for filename in suite["case_files"]:
        case_path = SUITE_ROOT / "cases" / filename
        case = json.loads(case_path.read_text(encoding="utf-8"))
        if not case["input_snapshot"].get("candidate_view"):
            raise ValueError(f"Case 缺少 candidate_view: {case['case_key']}")
        cases.append(case)
    suite["cases"] = cases
    return suite


def _baseline_manifest(component: str, version: str = "1.0") -> dict[str, Any]:
    return {
        "component": component,
        "version": version,
        "git_sha": os.environ.get("EVAL_BASELINE_GIT_SHA", "current-code-state"),
        "image_digest": os.environ.get("EVAL_BASELINE_IMAGE_DIGEST", "local-baseline"),
        "config_digest": os.environ.get("EVAL_BASELINE_CONFIG_DIGEST", "baseline-1.0"),
    }


def _ensure_published_release(conn, **kwargs) -> tuple[dict[str, Any], bool]:
    existing = conn.execute(
        "SELECT * FROM eval_releases WHERE release_key = ?", (kwargs["release_key"],)
    ).fetchone()
    if existing:
        return dict(existing), False
    release = create_release(conn, **kwargs)
    conn.execute(
        "UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP WHERE id = ?",
        (release["id"],),
    )
    release["status"] = "published"
    return release, True


def sync_builtin_benchmarks(conn) -> dict[str, int]:
    """Idempotently index the fixed Interview E2E Suite 1.0."""
    suite = load_suite_definition("interview-e2e-suite@1.0")
    judge_model = suite["judge_model"]
    releases = [
        {
            "release_key": "interview-agent@1.0",
            "release_type": "target",
            "version": "1.0",
            "target_type": "interview",
            "manifest": _baseline_manifest("interview-agent"),
        },
        {
            "release_key": suite["release_key"],
            "release_type": "benchmark_suite",
            "version": suite["version"],
            "target_type": suite["target_type"],
            "judge_model": judge_model,
            "manifest": suite,
        },
        {
            "release_key": "eval-protocol@1.0",
            "release_type": "eval_protocol",
            "version": "1.0",
            "manifest": {**_baseline_manifest("eval-protocol"), "replication_count": 5},
        },
        {
            "release_key": "judge@1.0",
            "release_type": "judge",
            "version": "1.0",
            "judge_model": judge_model,
            "manifest": {**_baseline_manifest("judge"), "model": judge_model, "temperature": 0},
        },
        {
            "release_key": "interview-harness@1.0",
            "release_type": "simulator_harness",
            "version": "1.0",
            "target_type": "interview",
            "manifest": _baseline_manifest("interview-harness"),
        },
        {
            "release_key": "candidate-simulator@1.0",
            "release_type": "candidate_simulator",
            "version": "1.0",
            "target_type": "interview",
            "manifest": {
                **_baseline_manifest("candidate-simulator"),
                "model": os.environ.get("CANDIDATE_LLM_MODEL", "candidate-simulator-model"),
            },
        },
    ]
    release_rows = {}
    created_releases = 0
    for release in releases:
        row, created = _ensure_published_release(conn, **release)
        release_rows[release["release_key"]] = row
        created_releases += int(created)

    suite_row = conn.execute(
        "SELECT * FROM eval_benchmark_suites WHERE release_id = ?",
        (release_rows[suite["release_key"]]["id"],),
    ).fetchone()
    if suite_row is None:
        suite_row = create_benchmark_suite(
            conn,
            release_id=release_rows[suite["release_key"]]["id"],
            suite_key="interview-e2e-suite",
            target_type=suite["target_type"],
            judge_model=judge_model,
            description=suite["description"],
        )
    cases_created = 0
    for case in suite["cases"]:
        exists = conn.execute(
            "SELECT id FROM eval_benchmark_cases WHERE suite_id = ? AND case_key = ?",
            (suite_row["id"], case["case_key"]),
        ).fetchone()
        if exists:
            continue
        create_benchmark_case(
            conn,
            suite_id=suite_row["id"],
            case_key=case["case_key"],
            scenario_key=case["scenario_key"],
            input_snapshot=case["input_snapshot"],
            contract=case["contract"],
        )
        cases_created += 1

    return {"suites": 1, "cases": len(suite["cases"]), "releases": len(releases)}

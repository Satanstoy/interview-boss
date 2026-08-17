"""Load Git-versioned Benchmark definitions and seed the 1.0 release axes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.services.evaluation_service import create_benchmark_case, create_benchmark_suite, create_release

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = REPO_ROOT / "evals" / "suites" / "interview-e2e" / "1.0"


EVALUATION_RELEASE_KEY = "interview-eval@1.0"
INTERNAL_SUITE_KEY = "interview-e2e-suite"


def load_suite_definition(release_key: str) -> dict[str, Any]:
    if release_key not in {EVALUATION_RELEASE_KEY, "interview-e2e-suite@1.0"}:
        raise ValueError(f"未知模拟面试评测版本: {release_key}")
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
        if existing["status"] == "draft":
            conn.execute(
                "UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP WHERE id = ?",
                (existing["id"],),
            )
            existing = conn.execute(
                "SELECT * FROM eval_releases WHERE id = ?", (existing["id"],)
            ).fetchone()
        return dict(existing), False
    release = create_release(conn, **kwargs)
    conn.execute(
        "UPDATE eval_releases SET status = 'published', published_at = CURRENT_TIMESTAMP WHERE id = ?",
        (release["id"],),
    )
    release["status"] = "published"
    return release, True


def _candidate_simulator_model() -> str:
    return (
        os.environ.get("CANDIDATE_LLM_MODEL")
        or os.environ.get("LLM_MODEL_NAME")
        or "gpt-4o"
    )


def _judge_model(suite: dict[str, Any]) -> str:
    return (
        os.environ.get("EVAL_JUDGE_MODEL")
        or os.environ.get("LLM_MODEL_NAME")
        or suite.get("judge_model")
        or "gpt-4o"
    )


def sync_builtin_benchmarks(conn) -> dict[str, int]:
    """Idempotently index the complete Interview Evaluation Release 1.0."""
    suite = load_suite_definition(EVALUATION_RELEASE_KEY)
    judge_model = _judge_model(suite)
    candidate_model = _candidate_simulator_model()
    target_model = os.environ.get("LLM_MODEL_NAME") or "gpt-4o"
    target_manifest = {
        **_baseline_manifest("interview-agent"),
        "target_type": "interview",
        "workflow": "chat-interview",
        "model": target_model,
    }
    evaluation_manifest = {
        "schema_version": 1,
        "release_key": EVALUATION_RELEASE_KEY,
        "target_type": "interview",
        "benchmark": {
            "version": "1.0",
            "suite_key": INTERNAL_SUITE_KEY,
            "description": suite["description"],
            "cases": suite["cases"],
        },
        "protocol": {
            "version": "1.0",
            "replication_count": 5,
            "seed_strategy": "sha256(base_seed:case_id:replication)",
            "aggregate": "mean_median_dispersion",
            "max_attempts": 1,
        },
        "judge": {
            "version": "1.0",
            "model": judge_model,
            "temperature": 0,
            "response_format": "json_object",
            "prompt_version": "interview-e2e-judge-v1",
            "credential_ref": "global-llm",
        },
        "simulator_harness": {
            "adapter": "InterviewE2EAdapter",
            "version": "1.0",
            "max_turns": 50,
            "trace_fields": ["tool_calls_trace", "classify_result", "turn_intent"],
        },
        "candidate_simulator": {
            "version": "1.0",
            "model": candidate_model,
            "temperature": 0.7,
            "credential_ref": "global-llm",
        },
        "tool_evaluation": {
            "version": "1.0",
            "enabled": True,
            "source": "metadata.tool_calls_trace",
            "deterministic": True,
        },
        "intent_evaluation": {
            "version": "1.0",
            "enabled": True,
            "source": "metadata.classify_result",
            "strategy_source": "metadata.turn_intent",
            "deterministic": True,
        },
        "retrieval": {
            "version": "1.0",
            "embedding_model": os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
            "credential_ref": "siliconflow-embedding",
        },
        "runtime": _baseline_manifest("interview-evaluation"),
    }
    releases = [
        {
            "release_key": "interview-agent@1.0",
            "release_type": "target",
            "version": "1.0",
            "target_type": "interview",
            "manifest": target_manifest,
            "git_sha": target_manifest["git_sha"],
            "image_digest": target_manifest["image_digest"],
            "config_digest": target_manifest["config_digest"],
        },
        {
            "release_key": EVALUATION_RELEASE_KEY,
            "release_type": "evaluation",
            "version": "1.0",
            "target_type": "interview",
            "judge_model": judge_model,
            "manifest": evaluation_manifest,
        },
    ]
    release_rows = {}
    created_releases = 0
    for release in releases:
        row, created = _ensure_published_release(conn, **release)
        release_rows[release["release_key"]] = row
        created_releases += int(created)

    # Keep historical component rows queryable, but remove them from the
    # published selection surface now that the complete Evaluation Release is
    # the only public evaluation version.
    conn.execute(
        "UPDATE eval_releases SET status = 'archived', archived_at = CURRENT_TIMESTAMP "
        "WHERE release_type IN ('benchmark_suite', 'eval_protocol', 'judge', "
        "'simulator_harness', 'candidate_simulator') AND status = 'published'"
    )

    suite_row = conn.execute(
        "SELECT * FROM eval_benchmark_suites WHERE release_id = ?",
        (release_rows[EVALUATION_RELEASE_KEY]["id"],),
    ).fetchone()
    if suite_row is None:
        suite_row = create_benchmark_suite(
            conn,
            release_id=release_rows[EVALUATION_RELEASE_KEY]["id"],
            suite_key=INTERNAL_SUITE_KEY,
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

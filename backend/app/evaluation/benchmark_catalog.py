"""Load Git-versioned Benchmark definitions and seed the 1.0 release axes."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.services.evaluation_service import create_benchmark_case, create_benchmark_suite, create_release

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITES_ROOT = REPO_ROOT / "evals" / "suites"
EVALUATION_RELEASE_KEY = "interview-eval@1.0"
INTERNAL_SUITE_KEY = "interview-e2e-suite"

BUILTIN_SUITES = (
    {
        "evaluation_key": "interview-eval@1.0",
        "target_key": "interview-agent@1.0",
        "target_type": "interview",
        "target_component": "interview-agent",
        "workflow": "chat-interview",
        "adapter": "InterviewE2EAdapter",
    },
    {
        "evaluation_key": "experience-extraction-eval@1.0",
        "target_key": "experience-extraction@1.0",
        "target_type": "experience_extraction",
        "target_component": "experience-extraction-agent",
        "workflow": "submit-extract-interview",
        "adapter": "ContentExtractionAdapter:interview",
    },
    {
        "evaluation_key": "jd-extraction-eval@1.0",
        "target_key": "jd-extraction@1.0",
        "target_type": "jd_extraction",
        "target_component": "jd-extraction-agent",
        "workflow": "submit-extract-jd",
        "adapter": "ContentExtractionAdapter:jd",
    },
    {
        "evaluation_key": "resume-analysis-eval@1.0",
        "target_key": "resume-analysis@1.0",
        "target_type": "resume_analysis",
        "target_component": "resume-analysis-agent",
        "workflow": "resume-optimize",
        "adapter": "ResumeAnalysisAdapter",
    },
    {
        "evaluation_key": "question-tagging-eval@1.0",
        "target_key": "question-tagging@1.0",
        "target_type": "question_tagging",
        "target_component": "question-tagging-agent",
        "workflow": "submit-classify",
        "adapter": "QuestionTaggingAdapter",
    },
)


def _suite_root(release_key: str) -> Path:
    if release_key == "interview-e2e-suite@1.0":
        release_key = EVALUATION_RELEASE_KEY
    spec = next((item for item in BUILTIN_SUITES if item["evaluation_key"] == release_key), None)
    if spec is None:
        raise ValueError(f"未知评测版本: {release_key}")
    suite_name = release_key.split("-eval@", 1)[0]
    if release_key == EVALUATION_RELEASE_KEY:
        suite_name = "interview-e2e"
    return SUITES_ROOT / suite_name / "1.0"


def load_suite_definition(release_key: str) -> dict[str, Any]:
    suite_root = _suite_root(release_key)
    suite = json.loads((suite_root / "suite.json").read_text(encoding="utf-8"))
    cases = []
    for filename in suite["case_files"]:
        case_path = suite_root / "cases" / filename
        case = json.loads(case_path.read_text(encoding="utf-8"))
        input_snapshot = case.get("input_snapshot") or {}
        if not isinstance(input_snapshot, dict) or not input_snapshot:
            raise ValueError(f"Case 缺少 input_snapshot: {case['case_key']}")
        if suite["target_type"] == "interview" and not input_snapshot.get("candidate_view"):
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


def _evaluation_manifest(
    suite: dict[str, Any], spec: dict[str, str], judge_model: str, candidate_model: str
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "release_key": spec["evaluation_key"],
        "target_type": spec["target_type"],
        "benchmark": {
            "version": "1.0",
            "suite_key": suite.get("suite_key") or spec["evaluation_key"].replace("@1.0", "-suite"),
            "description": suite["description"],
            "cases": suite["cases"],
        },
        "protocol": {
            "version": "1.0",
            "replication_count": 3 if spec["target_type"] != "interview" else 5,
            "seed_strategy": "sha256(base_seed:case_id:replication)",
            "aggregate": "mean_median_dispersion",
            "deterministic_weight": 0.6,
            "judge_weight": 0.4,
            "max_attempts": 1,
        },
        "judge": {
            "version": "1.0",
            "model": judge_model,
            "temperature": 0,
            "response_format": "json_object",
            "prompt_version": f"{spec['target_type']}-judge-v1",
            "credential_ref": "global-llm",
        },
        "simulator_harness": {
            "adapter": spec["adapter"],
            "version": "1.0",
            "trace_fields": ["payload", "hard_assertions", "contract_violations"],
        },
        "runtime": _baseline_manifest(f"{spec['target_component']}-evaluation"),
    }
    if spec["target_type"] == "interview":
        manifest["simulator_harness"].update({"max_turns": 50, "trace_fields": ["tool_calls_trace", "classify_result", "turn_intent"]})
        manifest["candidate_simulator"] = {
            "version": "1.0",
            "model": candidate_model,
            "temperature": 0.7,
            "credential_ref": "global-llm",
        }
        manifest["tool_evaluation"] = {
            "version": "1.0",
            "enabled": True,
            "source": "metadata.tool_calls_trace",
            "deterministic": True,
        }
        manifest["intent_evaluation"] = {
            "version": "1.0",
            "enabled": True,
            "source": "metadata.classify_result",
            "strategy_source": "metadata.turn_intent",
            "deterministic": True,
        }
        manifest["retrieval"] = {
            "version": "1.0",
            "embedding_model": os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"),
            "credential_ref": "siliconflow-embedding",
        }
    elif spec["target_type"] in {"experience_extraction", "jd_extraction"}:
        manifest["structured_evaluation"] = {
            "version": "1.0",
            "scorer": "content_scoring.evaluate_content_trace",
            "deterministic": True,
            "judge_dimensions": "field_grounding,question_or_technology_coverage,format_quality",
        }
    elif spec["target_type"] == "resume_analysis":
        manifest["resume_evaluation"] = {
            "version": "1.0",
            "scorer": "content_scoring.evaluate_resume_trace",
            "deterministic": True,
            "judge_dimensions": "fact_grounding,job_alignment,actionability",
        }
    elif spec["target_type"] == "question_tagging":
        manifest["tagging_evaluation"] = {
            "version": "1.0",
            "scorer": "content_scoring.evaluate_tagging_trace",
            "deterministic": True,
            "judge_dimensions": "taxonomy_accuracy,tag_quality,difficulty",
        }
    return manifest


def sync_builtin_benchmarks(conn) -> dict[str, int]:
    """Idempotently index the complete built-in Evaluation Releases 1.0."""
    candidate_model = _candidate_simulator_model()
    target_model = os.environ.get("LLM_MODEL_NAME") or "gpt-4o"
    release_rows = {}
    created_releases = 0
    total_cases = 0
    for spec in BUILTIN_SUITES:
        suite = load_suite_definition(spec["evaluation_key"])
        judge_model = _judge_model(suite)
        target_manifest = {
            **_baseline_manifest(spec["target_component"]),
            "target_type": spec["target_type"],
            "workflow": spec["workflow"],
            "model": target_model,
        }
        evaluation_manifest = _evaluation_manifest(suite, spec, judge_model, candidate_model)
        releases = [
            {
                "release_key": spec["target_key"],
                "release_type": "target",
                "version": "1.0",
                "target_type": spec["target_type"],
                "manifest": target_manifest,
                "git_sha": target_manifest["git_sha"],
                "image_digest": target_manifest["image_digest"],
                "config_digest": target_manifest["config_digest"],
            },
            {
                "release_key": spec["evaluation_key"],
                "release_type": "evaluation",
                "version": "1.0",
                "target_type": spec["target_type"],
                "judge_model": judge_model,
                "manifest": evaluation_manifest,
            },
        ]
        total_cases += len(suite["cases"])
        for release in releases:
            row, created = _ensure_published_release(conn, **release)
            release_rows[release["release_key"]] = row
            created_releases += int(created)

        suite_row = conn.execute(
            "SELECT * FROM eval_benchmark_suites WHERE release_id = ?",
            (release_rows[spec["evaluation_key"]]["id"],),
        ).fetchone()
        if suite_row is None:
            suite_row = create_benchmark_suite(
                conn,
                release_id=release_rows[spec["evaluation_key"]]["id"],
                suite_key=suite.get("suite_key") or f"{spec['target_type']}-suite",
                target_type=spec["target_type"],
                judge_model=judge_model,
                description=suite["description"],
            )
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

    # Keep historical component rows queryable, but remove them from the
    # published selection surface now that the complete Evaluation Release is
    # the only public evaluation version.
    conn.execute(
        "UPDATE eval_releases SET status = 'archived', archived_at = CURRENT_TIMESTAMP "
        "WHERE release_type IN ('benchmark_suite', 'eval_protocol', 'judge', "
        "'simulator_harness', 'candidate_simulator') AND status = 'published'"
    )

    return {"suites": len(BUILTIN_SUITES), "cases": total_cases, "releases": len(BUILTIN_SUITES) * 2}

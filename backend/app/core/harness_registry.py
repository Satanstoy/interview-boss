"""Authoritative project-level Harness identities.

Eval manifests may describe how a Harness is exercised, but they do not own
the Harness version.  This module is the single application-level source used
by the runtime, the database registry and the admin API.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Any


PROJECT_HARNESS_VERSION = os.environ.get("PROJECT_HARNESS_VERSION", "1.0")
PROJECT_HARNESS_GIT_SHA = os.environ.get(
    "PROJECT_HARNESS_GIT_SHA",
    os.environ.get("EVAL_RUNTIME_GIT_SHA", "current-code-state"),
)
PROJECT_HARNESS_IMAGE_DIGEST = os.environ.get(
    "PROJECT_HARNESS_IMAGE_DIGEST", "local-baseline"
)
PROJECT_HARNESS_CONFIG_DIGEST = os.environ.get(
    "PROJECT_HARNESS_CONFIG_DIGEST", f"project-harness-{PROJECT_HARNESS_VERSION}"
)

_HARNESS_SPECS: dict[str, dict[str, str]] = {
    "interview": {
        "harness_key": "interview-harness",
        "display_name": "面试对话 Harness",
        "component": "app.agents.chat",
        "source_ref": "backend/app/agents/chat",
    },
    "experience_extraction": {
        "harness_key": "experience-extraction-harness",
        "display_name": "面经提取 Harness",
        "component": "app.agents.submit.extract",
        "source_ref": "backend/app/agents/submit",
    },
    "jd_extraction": {
        "harness_key": "jd-extraction-harness",
        "display_name": "JD 提取 Harness",
        "component": "app.agents.submit.extract",
        "source_ref": "backend/app/agents/submit",
    },
    "resume_analysis": {
        "harness_key": "resume-analysis-harness",
        "display_name": "简历分析 Harness",
        "component": "app.evaluation.resume_adapter",
        "source_ref": "backend/app/evaluation/resume_adapter.py",
    },
    "question_tagging": {
        "harness_key": "question-tagging-harness",
        "display_name": "题目分类 Harness",
        "component": "app.agents.submit.classify",
        "source_ref": "backend/app/agents/submit",
    },
}


def harness_spec(target_type: str) -> dict[str, str]:
    try:
        return dict(_HARNESS_SPECS[target_type])
    except KeyError as exc:
        raise ValueError(f"未注册项目 Harness: {target_type}") from exc


def harness_manifest(target_type: str) -> dict[str, Any]:
    spec = harness_spec(target_type)
    return {
        **spec,
        "target_type": target_type,
        "version": PROJECT_HARNESS_VERSION,
        "git_sha": PROJECT_HARNESS_GIT_SHA,
        "image_digest": PROJECT_HARNESS_IMAGE_DIGEST,
        "config_digest": PROJECT_HARNESS_CONFIG_DIGEST,
        "source": "project_runtime",
    }


def harness_manifest_digest(manifest: dict[str, Any]) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sync_project_harnesses(conn: sqlite3.Connection) -> dict[str, int]:
    """Publish the current project Harness identity for every target type."""
    created = 0
    for target_type in _HARNESS_SPECS:
        manifest = harness_manifest(target_type)
        spec = harness_spec(target_type)
        existing = conn.execute(
            "SELECT * FROM harness_releases WHERE harness_key = ? AND version = ?",
            (spec["harness_key"], PROJECT_HARNESS_VERSION),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO harness_releases (
                    harness_key, target_type, version, display_name, status,
                    manifest_json, manifest_digest, source_ref, git_sha,
                    image_digest, config_digest, published_at
                ) VALUES (?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    spec["harness_key"],
                    target_type,
                    PROJECT_HARNESS_VERSION,
                    spec["display_name"],
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    harness_manifest_digest(manifest),
                    spec["source_ref"],
                    PROJECT_HARNESS_GIT_SHA,
                    PROJECT_HARNESS_IMAGE_DIGEST,
                    PROJECT_HARNESS_CONFIG_DIGEST,
                ),
            )
            created += 1
        elif existing["source_ref"] == "legacy_eval_release":
            conn.execute(
                """
                UPDATE harness_releases
                SET display_name = ?, status = 'published', manifest_json = ?,
                    manifest_digest = ?, source_ref = ?, git_sha = ?,
                    image_digest = ?, config_digest = ?, published_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    spec["display_name"],
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    harness_manifest_digest(manifest),
                    spec["source_ref"],
                    PROJECT_HARNESS_GIT_SHA,
                    PROJECT_HARNESS_IMAGE_DIGEST,
                    PROJECT_HARNESS_CONFIG_DIGEST,
                    existing["id"],
                ),
            )
        elif existing["status"] != "published":
            conn.execute(
                "UPDATE harness_releases SET status = 'published', published_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (existing["id"],),
            )
    return {"harnesses": len(_HARNESS_SPECS), "created": created}

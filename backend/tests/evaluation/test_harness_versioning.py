"""Project Harness provenance is independent from the Evaluation Manifest."""

import json


def test_builtin_catalog_registers_project_harness_releases(test_db):
    from app.evaluation.benchmark_catalog import sync_builtin_benchmarks

    sync_builtin_benchmarks(test_db)
    rows = test_db.execute(
        "SELECT harness_key, target_type, version, status FROM harness_releases "
        "ORDER BY harness_key"
    ).fetchall()

    assert rows
    assert {row["target_type"] for row in rows} == {
        "interview",
        "experience_extraction",
        "jd_extraction",
        "resume_analysis",
        "question_tagging",
    }
    assert {row["status"] for row in rows} == {"published"}


def test_eval_run_snapshot_freezes_project_harness_release(test_db):
    from app.evaluation.benchmark_catalog import sync_builtin_benchmarks
    from app.services.evaluation_service import create_eval_run

    sync_builtin_benchmarks(test_db)
    target = test_db.execute(
        "SELECT id FROM eval_releases WHERE release_type = 'target' "
        "AND target_type = 'interview' LIMIT 1"
    ).fetchone()
    evaluation = test_db.execute(
        "SELECT id FROM eval_releases WHERE release_type = 'evaluation' "
        "AND target_type = 'interview' LIMIT 1"
    ).fetchone()

    result = create_eval_run(
        test_db,
        created_by=1,
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        replication_count=1,
        seed=7,
    )
    snapshot = json.loads(
        test_db.execute(
            "SELECT snapshot_json FROM eval_runs WHERE id = ?", (result["id"],)
        ).fetchone()["snapshot_json"]
    )

    harness = snapshot["harness_release"]
    assert harness["harness_key"] == "interview-harness"
    assert harness["version"]
    assert harness["manifest_digest"]


def test_eval_run_can_pin_a_project_harness_release_for_ab(test_db):
    from app.evaluation.benchmark_catalog import sync_builtin_benchmarks
    from app.services.evaluation_service import create_eval_run

    sync_builtin_benchmarks(test_db)
    current = test_db.execute(
        "SELECT * FROM harness_releases WHERE target_type = 'interview' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    test_db.execute(
        """
        INSERT INTO harness_releases (
            harness_key, target_type, version, display_name, status,
            manifest_json, manifest_digest, source_ref, git_sha,
            image_digest, config_digest, published_at
        ) VALUES (?, ?, ?, ?, 'published', ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            current["harness_key"],
            current["target_type"],
            "2.1",
            current["display_name"],
            current["manifest_json"],
            "sha256:harness-v2",
            current["source_ref"],
            "git-harness-v2",
            "sha256:image-v2",
            "sha256:config-v2",
        ),
    )
    harness_v2 = test_db.execute(
        "SELECT * FROM harness_releases WHERE harness_key = ? AND version = '2.1'",
        (current["harness_key"],),
    ).fetchone()
    target = test_db.execute(
        "SELECT id FROM eval_releases WHERE release_key = 'interview-agent@1.0'"
    ).fetchone()
    evaluation = test_db.execute(
        "SELECT id FROM eval_releases WHERE release_key = 'interview-eval@1.2'"
    ).fetchone()

    result = create_eval_run(
        test_db,
        created_by=1,
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        project_harness_release_id=harness_v2["id"],
        replication_count=1,
        seed=23,
    )

    snapshot = json.loads(result["snapshot_json"])
    assert result["harness_release_id"] == harness_v2["id"]
    assert snapshot["harness_release"]["version"] == "2.1"

    default_run = create_eval_run(
        test_db,
        created_by=1,
        target_release_id=target["id"],
        evaluation_release_id=evaluation["id"],
        replication_count=1,
        seed=24,
    )
    default_snapshot = json.loads(default_run["snapshot_json"])
    assert default_snapshot["harness_release"]["version"] == current["version"]

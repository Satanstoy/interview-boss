"""评测领域 v87 迁移契约。"""


def test_evaluation_migration_registers_domain_tables(test_db):
    version = test_db.execute(
        "SELECT version, name FROM schema_version WHERE version = 87"
    ).fetchone()

    assert version is not None
    assert version[1] == "evaluation_control_plane"

    expected_tables = {
        "eval_releases",
        "eval_benchmark_suites",
        "eval_benchmark_cases",
        "eval_batches",
        "eval_runs",
        "eval_items",
        "eval_attempts",
        "eval_events",
        "eval_artifacts",
        "eval_human_reviews",
    }
    actual_tables = {
        row[0]
        for row in test_db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name LIKE 'eval_%'"
        ).fetchall()
    }

    assert expected_tables <= actual_tables


def test_evaluation_tables_keep_release_and_batch_context(test_db):
    release_columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info(eval_releases)").fetchall()
    }
    batch_columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info(eval_batches)").fetchall()
    }
    run_columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info(eval_runs)").fetchall()
    }

    assert {"release_key", "release_type", "manifest_json", "manifest_digest"} <= release_columns
    assert {"batch_fingerprint", "replication_count", "seed"} <= batch_columns
    assert {
        "target_release_id",
        "benchmark_suite_release_id",
        "judge_release_id",
        "simulator_harness_release_id",
        "candidate_simulator_release_id",
        "status",
    } <= run_columns
    assert {"evaluation_release_id", "snapshot_json"} <= batch_columns
    assert {"evaluation_release_id", "snapshot_json"} <= run_columns


def test_dual_axis_migration_is_registered(test_db):
    version = test_db.execute(
        "SELECT version, name FROM schema_version WHERE version = 93"
    ).fetchone()

    assert tuple(version) == (93, "evaluation_dual_axis")


def test_evaluation_migration_is_idempotent(test_db):
    from app.db.migrations.evaluation import _migration_087_evaluation_control_plane

    _migration_087_evaluation_control_plane(test_db)
    test_db.commit()

    assert test_db.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0] == 0

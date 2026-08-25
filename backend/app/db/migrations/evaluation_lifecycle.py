"""Evaluation lifecycle fields and terminal expiry support (migration 115)."""

from __future__ import annotations


def _migration_115_evaluation_lifecycle(conn):
    """Rebuild evaluation parents so ``expired`` is a durable terminal state.

    SQLite cannot alter a CHECK constraint in place. The migration runner
    treats this migration as destructive and temporarily disables foreign keys
    while the three parent tables are rebuilt; all child rows are copied.
    """
    conn.executescript(
        """
        DROP TABLE IF EXISTS eval_batches_new;
        CREATE TABLE eval_batches_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_fingerprint TEXT NOT NULL UNIQUE,
            target_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            evaluation_release_id INTEGER REFERENCES eval_releases(id) ON DELETE RESTRICT,
            benchmark_suite_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            eval_protocol_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            judge_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            simulator_harness_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            candidate_simulator_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            harness_release_id INTEGER REFERENCES harness_releases(id) ON DELETE RESTRICT,
            environment_fingerprint TEXT NOT NULL DEFAULT '',
            seed INTEGER NOT NULL,
            replication_count INTEGER NOT NULL CHECK (replication_count > 0),
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled', 'expired')),
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
            summary_json TEXT NOT NULL DEFAULT '{}',
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            last_heartbeat_at TIMESTAMP
        );
        INSERT INTO eval_batches_new (
            id, batch_fingerprint, target_release_id, evaluation_release_id,
            benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
            simulator_harness_release_id, candidate_simulator_release_id,
            harness_release_id, environment_fingerprint, seed, replication_count,
            status, total_items, completed_items, failed_items, created_by,
            created_at, started_at, finished_at, cancel_requested, summary_json,
            snapshot_json, last_heartbeat_at
        )
        SELECT id, batch_fingerprint, target_release_id, evaluation_release_id,
               benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
               simulator_harness_release_id, candidate_simulator_release_id,
               harness_release_id, environment_fingerprint, seed, replication_count,
               status, total_items, completed_items, failed_items, created_by,
               created_at, started_at, finished_at, cancel_requested, summary_json,
               snapshot_json, NULL
        FROM eval_batches;
        DROP TABLE eval_batches;
        ALTER TABLE eval_batches_new RENAME TO eval_batches;

        DROP TABLE IF EXISTS eval_runs_new;
        CREATE TABLE eval_runs_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL REFERENCES eval_batches(id) ON DELETE RESTRICT,
            target_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            evaluation_release_id INTEGER REFERENCES eval_releases(id) ON DELETE RESTRICT,
            benchmark_suite_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            eval_protocol_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            judge_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            simulator_harness_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            candidate_simulator_release_id INTEGER NOT NULL REFERENCES eval_releases(id) ON DELETE RESTRICT,
            harness_release_id INTEGER REFERENCES harness_releases(id) ON DELETE RESTRICT,
            comparison_group TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled', 'expired')),
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
            snapshot_json TEXT NOT NULL DEFAULT '{}',
            last_heartbeat_at TIMESTAMP,
            restart_of_run_id INTEGER REFERENCES eval_runs(id) ON DELETE SET NULL
        );
        INSERT INTO eval_runs_new (
            id, batch_id, target_release_id, evaluation_release_id,
            benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
            simulator_harness_release_id, candidate_simulator_release_id,
            harness_release_id, comparison_group, idempotency_key, status,
            total_items, completed_items, failed_items, summary_json, created_by,
            created_at, started_at, finished_at, cancel_requested, snapshot_json,
            last_heartbeat_at, restart_of_run_id
        )
        SELECT id, batch_id, target_release_id, evaluation_release_id,
               benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
               simulator_harness_release_id, candidate_simulator_release_id,
               harness_release_id, comparison_group, idempotency_key, status,
               total_items, completed_items, failed_items, summary_json, created_by,
               created_at, started_at, finished_at, cancel_requested, snapshot_json,
               NULL, NULL
        FROM eval_runs;
        DROP TABLE eval_runs;
        ALTER TABLE eval_runs_new RENAME TO eval_runs;

        DROP TABLE IF EXISTS eval_experiments_new;
        CREATE TABLE eval_experiments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled', 'expired')),
            target_types_json TEXT NOT NULL DEFAULT '[]',
            comparison_group TEXT NOT NULL DEFAULT '',
            environment_fingerprint TEXT NOT NULL DEFAULT '',
            seed INTEGER NOT NULL DEFAULT 1,
            replication_count INTEGER NOT NULL CHECK (replication_count > 0),
            total_runs INTEGER NOT NULL DEFAULT 0,
            completed_runs INTEGER NOT NULL DEFAULT 0,
            failed_runs INTEGER NOT NULL DEFAULT 0,
            cancelled_runs INTEGER NOT NULL DEFAULT 0,
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP
        );
        INSERT INTO eval_experiments_new (
            id, experiment_key, status, target_types_json, comparison_group,
            environment_fingerprint, seed, replication_count, total_runs,
            completed_runs, failed_runs, cancelled_runs, summary_json, created_by,
            created_at, started_at, finished_at
        )
        SELECT id, experiment_key, status, target_types_json, comparison_group,
               environment_fingerprint, seed, replication_count, total_runs,
               completed_runs, failed_runs, cancelled_runs, summary_json, created_by,
               created_at, started_at, finished_at
        FROM eval_experiments;
        DROP TABLE eval_experiments;
        ALTER TABLE eval_experiments_new RENAME TO eval_experiments;

        CREATE INDEX IF NOT EXISTS idx_eval_batches_status_created
            ON eval_batches(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eval_runs_status_created
            ON eval_runs(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eval_runs_comparison_group
            ON eval_runs(comparison_group, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eval_runs_evaluation_release
            ON eval_runs(evaluation_release_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eval_runs_harness_release
            ON eval_runs(harness_release_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eval_experiments_status_created
            ON eval_experiments(status, created_at DESC);
        """
    )

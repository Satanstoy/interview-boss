"""Evaluation Experiment orchestration tables (migration 095)."""

from __future__ import annotations


def _migration_095_evaluation_experiment(conn):
    """Store a frontend-launched group of target-scoped Eval Runs."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS eval_experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled')),
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

        CREATE INDEX IF NOT EXISTS idx_eval_experiments_status_created
            ON eval_experiments(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS eval_experiment_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES eval_experiments(id) ON DELETE CASCADE,
            run_id INTEGER NOT NULL UNIQUE REFERENCES eval_runs(id) ON DELETE CASCADE,
            target_type TEXT NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(experiment_id, target_type)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_experiment_runs_experiment
            ON eval_experiment_runs(experiment_id, display_order, id);

        CREATE TABLE IF NOT EXISTS eval_experiment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES eval_experiments(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(experiment_id, sequence)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_experiment_events_sequence
            ON eval_experiment_events(experiment_id, sequence);
        """
    )

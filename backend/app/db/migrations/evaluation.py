"""AI Evaluation System 1.0 domain tables."""


def _migration_087_evaluation_control_plane(conn):
    """Create the durable evaluation control-plane model."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS eval_releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_key TEXT NOT NULL UNIQUE,
            release_type TEXT NOT NULL,
            version TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'published', 'archived')),
            manifest_json TEXT NOT NULL,
            manifest_digest TEXT NOT NULL,
            judge_model TEXT NOT NULL DEFAULT '',
            git_sha TEXT NOT NULL DEFAULT '',
            image_digest TEXT NOT NULL DEFAULT '',
            config_digest TEXT NOT NULL DEFAULT '',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP,
            archived_at TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_eval_releases_type_status
            ON eval_releases(release_type, status);

        CREATE TABLE IF NOT EXISTS eval_benchmark_suites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER NOT NULL UNIQUE
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            suite_key TEXT NOT NULL,
            target_type TEXT NOT NULL,
            judge_model TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS eval_benchmark_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suite_id INTEGER NOT NULL
                REFERENCES eval_benchmark_suites(id) ON DELETE CASCADE,
            case_key TEXT NOT NULL,
            scenario_key TEXT NOT NULL DEFAULT '',
            input_snapshot_json TEXT NOT NULL,
            contract_json TEXT NOT NULL,
            input_digest TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(suite_id, case_key)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_cases_suite_active
            ON eval_benchmark_cases(suite_id, active, id);

        CREATE TABLE IF NOT EXISTS eval_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_fingerprint TEXT NOT NULL UNIQUE,
            target_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            benchmark_suite_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            eval_protocol_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            judge_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            simulator_harness_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            candidate_simulator_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            environment_fingerprint TEXT NOT NULL DEFAULT '',
            seed INTEGER NOT NULL,
            replication_count INTEGER NOT NULL CHECK (replication_count > 0),
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled')),
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
            summary_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_eval_batches_status_created
            ON eval_batches(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS eval_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id INTEGER NOT NULL REFERENCES eval_batches(id) ON DELETE RESTRICT,
            target_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            benchmark_suite_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            eval_protocol_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            judge_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            simulator_harness_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            candidate_simulator_release_id INTEGER NOT NULL
                REFERENCES eval_releases(id) ON DELETE RESTRICT,
            comparison_group TEXT NOT NULL DEFAULT '',
            idempotency_key TEXT,
            status TEXT NOT NULL DEFAULT 'created'
                CHECK (status IN ('created', 'queued', 'running', 'completed', 'failed', 'cancelled')),
            total_items INTEGER NOT NULL DEFAULT 0,
            completed_items INTEGER NOT NULL DEFAULT 0,
            failed_items INTEGER NOT NULL DEFAULT 0,
            summary_json TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK (cancel_requested IN (0, 1)),
            UNIQUE(created_by, idempotency_key)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_runs_status_created
            ON eval_runs(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_eval_runs_comparison_group
            ON eval_runs(comparison_group, created_at DESC);

        CREATE TABLE IF NOT EXISTS eval_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            case_id INTEGER NOT NULL REFERENCES eval_benchmark_cases(id) ON DELETE RESTRICT,
            replication_index INTEGER NOT NULL CHECK (replication_index > 0),
            seed INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
            selected_attempt_id INTEGER,
            contract_status TEXT NOT NULL DEFAULT 'pending',
            hard_gate_status TEXT NOT NULL DEFAULT 'pending',
            judge_status TEXT NOT NULL DEFAULT 'pending',
            score REAL,
            result_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            UNIQUE(run_id, case_id, replication_index)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_items_run_status
            ON eval_items(run_id, status, id);

        CREATE TABLE IF NOT EXISTS eval_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL REFERENCES eval_items(id) ON DELETE CASCADE,
            attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
            attempt_kind TEXT NOT NULL DEFAULT 'target',
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'succeeded', 'failed')),
            failure_class TEXT NOT NULL DEFAULT '',
            raw_observation_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP,
            UNIQUE(item_id, attempt_index)
        );

        CREATE TABLE IF NOT EXISTS eval_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(run_id, sequence)
        );

        CREATE INDEX IF NOT EXISTS idx_eval_events_run_sequence
            ON eval_events(run_id, sequence);

        CREATE TABLE IF NOT EXISTS eval_artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            item_id INTEGER REFERENCES eval_items(id) ON DELETE CASCADE,
            attempt_id INTEGER REFERENCES eval_attempts(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL,
            storage_path TEXT NOT NULL,
            digest TEXT NOT NULL,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            retention_class TEXT NOT NULL DEFAULT 'official',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS eval_human_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comparison_group TEXT NOT NULL,
            run_a_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            run_b_id INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
            item_key TEXT NOT NULL,
            reviewer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            choice TEXT NOT NULL CHECK (choice IN ('a', 'b', 'tie', 'both_fail')),
            dimensions_json TEXT NOT NULL DEFAULT '{}',
            comment TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_eval_reviews_group
            ON eval_human_reviews(comparison_group, created_at DESC);
        """
    )

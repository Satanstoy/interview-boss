CREATE TABLE interview_distribution_refresh_jobs (
            scope TEXT NOT NULL,
            job_position TEXT NOT NULL,
            requested_source_version TEXT NOT NULL,
            published_source_version TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            claimed_by TEXT,
            claimed_at TIMESTAMP,
            last_error TEXT,
            next_retry_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, job_position)
        );

CREATE TABLE interview_distribution_stat_exclusions (
            stats_version INTEGER NOT NULL,
            scope TEXT NOT NULL,
            job_position TEXT NOT NULL,
            interview_id INTEGER NOT NULL,
            exclusion_reason TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (stats_version, scope, job_position, interview_id)
        );

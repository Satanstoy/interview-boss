CREATE TABLE interview_distribution_stats (
            scope TEXT NOT NULL,
            job_position TEXT NOT NULL,
            question_type TEXT NOT NULL,
            stats_version INTEGER NOT NULL,
            posterior_mean_ratio REAL NOT NULL,
            posterior_alpha REAL NOT NULL,
            raw_question_count INTEGER NOT NULL,
            sample_interview_count INTEGER NOT NULL,
            sample_question_count INTEGER NOT NULL,
            recommended_total_count INTEGER NOT NULL,
            dispersion REAL NOT NULL,
            confidence TEXT NOT NULL,
            calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, job_position, question_type, stats_version)
        );

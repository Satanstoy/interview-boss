CREATE TABLE cluster_review_tasks (
            id TEXT PRIMARY KEY,
            cluster_id INTEGER NOT NULL,
            review_version TEXT NOT NULL,
            trigger_reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_until TEXT,
            arq_job_id TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE(cluster_id, review_version),
            FOREIGN KEY (cluster_id) REFERENCES question_bank(id) ON DELETE CASCADE
        );

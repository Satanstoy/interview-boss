CREATE TABLE cluster_review_state (
            cluster_id INTEGER PRIMARY KEY,
            current_version TEXT NOT NULL,
            reviewed_version TEXT,
            status TEXT NOT NULL DEFAULT 'needs_review',
            priority INTEGER NOT NULL DEFAULT 50,
            last_trigger_reason TEXT,
            last_reviewed_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (cluster_id) REFERENCES question_bank(id) ON DELETE CASCADE
        );

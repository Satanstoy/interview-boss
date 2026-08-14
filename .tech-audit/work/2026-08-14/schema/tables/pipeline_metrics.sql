CREATE TABLE pipeline_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            job_position TEXT DEFAULT '',
            owner_id INTEGER,
            questions_in INTEGER DEFAULT 0,
            matched INTEGER DEFAULT 0,
            new_clusters INTEGER DEFAULT 0,
            merged INTEGER DEFAULT 0,
            llm_calls INTEGER DEFAULT 0,
            elapsed_seconds REAL DEFAULT 0,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

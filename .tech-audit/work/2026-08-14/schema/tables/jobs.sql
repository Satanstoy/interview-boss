CREATE TABLE jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            progress_current INTEGER DEFAULT 0,
            progress_total INTEGER DEFAULT 0,
            progress_message TEXT DEFAULT '',
            result TEXT,
            error TEXT,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP, attempts INTEGER NOT NULL DEFAULT 0, available_at TEXT NOT NULL DEFAULT '', locked_until TEXT, arq_job_id TEXT, worker_id TEXT, last_error TEXT, started_at TEXT, idempotency_key TEXT, parent_job_id INTEGER,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

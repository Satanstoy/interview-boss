CREATE TABLE job_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            , updated_at TIMESTAMP, is_deleted INTEGER DEFAULT 0);

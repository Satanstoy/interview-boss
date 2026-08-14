CREATE TABLE interview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            focus TEXT,
            questions_list TEXT,
            difficulty TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , season TEXT DEFAULT '', owner_id INTEGER REFERENCES users(id), status TEXT DEFAULT 'approved', url_signature TEXT DEFAULT '', updated_at TIMESTAMP, job_position TEXT DEFAULT '', deleted_at TIMESTAMP, analysis_status TEXT DEFAULT 'idle', analysis_stage TEXT, analysis_result TEXT, analysis_updated_at TIMESTAMP);

CREATE TABLE jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            job_title TEXT,
            salary TEXT,
            tech_stack TEXT,
            bonus TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , season TEXT DEFAULT '', owner_id INTEGER REFERENCES users(id), status TEXT DEFAULT 'approved', url_signature TEXT DEFAULT '', updated_at TIMESTAMP, deleted_at TIMESTAMP, job_position TEXT DEFAULT '');

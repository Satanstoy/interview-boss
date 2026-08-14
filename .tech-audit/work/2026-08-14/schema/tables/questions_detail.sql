CREATE TABLE questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            round TEXT,
            question TEXT,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            diff_tag TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , updated_at TIMESTAMP, deleted_at TIMESTAMP, job_position TEXT DEFAULT '', interview_id INTEGER, question_type TEXT NOT NULL DEFAULT 'unclassified', dimension TEXT NOT NULL DEFAULT 'unclassified');

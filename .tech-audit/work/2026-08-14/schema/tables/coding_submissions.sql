CREATE TABLE coding_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            problem_id INTEGER NOT NULL,
            language TEXT NOT NULL,
            code TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'full_review',
            hint_round INTEGER DEFAULT 0,
            parent_submission_id INTEGER,
            ai_feedback TEXT DEFAULT '',
            error_categories TEXT DEFAULT '[]',
            is_passed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, scores TEXT DEFAULT '{}', reference_answer TEXT DEFAULT '', total_score REAL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (problem_id) REFERENCES coding_problems(id),
            FOREIGN KEY (parent_submission_id) REFERENCES coding_submissions(id)
        );

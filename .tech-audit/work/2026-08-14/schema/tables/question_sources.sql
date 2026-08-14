CREATE TABLE question_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMP DEFAULT NULL,
            UNIQUE(question_bank_id, url)
        );

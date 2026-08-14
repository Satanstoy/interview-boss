CREATE TABLE question_original_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMP DEFAULT NULL,
            UNIQUE(question_bank_id, question_text)
        );

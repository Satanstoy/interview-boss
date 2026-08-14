CREATE TABLE merge_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merge_history_id INTEGER,
            question_bank_id INTEGER,
            feedback_type TEXT NOT NULL,
            comment TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (merge_history_id) REFERENCES merge_history(id) ON DELETE SET NULL,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        );

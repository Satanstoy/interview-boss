CREATE TABLE user_practice_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            user_answer TEXT,
            evaluation_result TEXT,
            score INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
        );

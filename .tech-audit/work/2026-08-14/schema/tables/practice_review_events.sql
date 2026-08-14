CREATE TABLE practice_review_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            review_id INTEGER NOT NULL,
            rating TEXT NOT NULL,
            score INTEGER,
            source TEXT NOT NULL DEFAULT 'flashcard',
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, before_state_json TEXT, corrected_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            FOREIGN KEY (review_id) REFERENCES user_question_review(id) ON DELETE CASCADE
        );

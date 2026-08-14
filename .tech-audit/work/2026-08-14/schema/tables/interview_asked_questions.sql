CREATE TABLE interview_asked_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            asked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

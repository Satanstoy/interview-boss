CREATE TABLE user_question_view (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                question_bank_id INTEGER NOT NULL,
                is_starred INTEGER DEFAULT 0,
                personal_tags TEXT DEFAULT '',
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, user_answer TEXT DEFAULT '',
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE
            );

CREATE TABLE coding_problem_favorites (
            user_id INTEGER NOT NULL,
            problem_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, problem_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (problem_id) REFERENCES coding_problems(id) ON DELETE CASCADE
        );

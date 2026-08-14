CREATE TABLE user_interview_distribution_preferences (
            user_id INTEGER NOT NULL,
            job_position TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'system_default',
            target_question_count INTEGER,
            custom_distribution TEXT,
            selected_experience_id INTEGER,
            style_strength TEXT NOT NULL DEFAULT 'normal',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, job_position)
        );

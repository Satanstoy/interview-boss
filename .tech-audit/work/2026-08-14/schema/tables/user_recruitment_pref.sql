CREATE TABLE user_recruitment_pref (
            user_id INTEGER PRIMARY KEY,
            graduation_year INTEGER,
            batch TEXT DEFAULT '',
            daily_capacity INTEGER DEFAULT 30,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , pace TEXT NOT NULL DEFAULT 'standard');

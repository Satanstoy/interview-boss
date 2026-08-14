CREATE TABLE coding_problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'medium',
            tags TEXT DEFAULT '[]',
            expected_complexity TEXT DEFAULT '',
            source TEXT DEFAULT '',
            supported_languages TEXT DEFAULT '["python","c","java"]',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , owner_id INTEGER, source_type TEXT DEFAULT 'seed');

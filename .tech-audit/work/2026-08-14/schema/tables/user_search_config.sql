CREATE TABLE user_search_config (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            provider TEXT NOT NULL DEFAULT 'none',
            api_key TEXT NOT NULL DEFAULT '',
            base_url TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

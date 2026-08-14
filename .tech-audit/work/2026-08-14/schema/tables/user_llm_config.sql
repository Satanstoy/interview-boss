CREATE TABLE user_llm_config (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                api_key TEXT NOT NULL DEFAULT '',
                base_url TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT 'gpt-4o',
                timeout INTEGER NOT NULL DEFAULT 120,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            , api_format TEXT DEFAULT 'auto', thinking INTEGER DEFAULT 0);

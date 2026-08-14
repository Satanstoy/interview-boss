CREATE TABLE taxonomy (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_name TEXT NOT NULL,
                categories_json TEXT NOT NULL,
                is_default INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            , source TEXT DEFAULT 'system', owner_id INTEGER DEFAULT NULL, is_public INTEGER DEFAULT 0);

CREATE TABLE practice_decks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_key TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            deck_type TEXT NOT NULL DEFAULT 'system',
            criteria_json TEXT NOT NULL DEFAULT '{}',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        , owner_id INTEGER, visibility TEXT NOT NULL DEFAULT 'private');

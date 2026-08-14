CREATE TABLE question_original_item_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_item_id INTEGER NOT NULL REFERENCES question_original_items(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMP DEFAULT NULL,
            UNIQUE(original_item_id, url)
        );

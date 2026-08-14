CREATE TABLE chat_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            memory_type TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'auto_extract',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, summary TEXT DEFAULT '', source_turn_id TEXT, source_job_id TEXT, memory_schema_version INTEGER NOT NULL DEFAULT 1, expires_at TIMESTAMP, content_hash TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

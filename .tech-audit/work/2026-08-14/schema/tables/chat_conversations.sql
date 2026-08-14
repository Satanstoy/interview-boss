CREATE TABLE chat_conversations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            mode TEXT NOT NULL,
            title TEXT,
            jd_id INTEGER,
            resume_text TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, session_notes TEXT DEFAULT '', metadata TEXT DEFAULT '{}', job_position TEXT DEFAULT '', metadata_version INTEGER NOT NULL DEFAULT 0, session_notes_version INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

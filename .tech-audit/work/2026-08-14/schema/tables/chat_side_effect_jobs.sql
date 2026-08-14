CREATE TABLE chat_side_effect_jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            source_turn_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'running', 'completed', 'failed', 'dead_letter', 'skipped')),
            attempts INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            locked_at TIMESTAMP,
            finished_at TIMESTAMP,
            last_error TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (source_turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE,
            UNIQUE(kind, source_turn_id)
        );

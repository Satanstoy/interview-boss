CREATE TABLE chat_candidate_sets (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            source TEXT NOT NULL,
            source_turn_id TEXT,
            items_json TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'available'
                CHECK (status IN ('available', 'consumed', 'expired', 'invalidated')),
            expires_at TIMESTAMP NOT NULL,
            selected_item_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            consumed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (source_turn_id) REFERENCES chat_turns(id) ON DELETE SET NULL
        );

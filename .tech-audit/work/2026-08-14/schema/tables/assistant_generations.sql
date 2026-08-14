CREATE TABLE assistant_generations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            turn_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            parent_generation_id TEXT,
            source_turn_id TEXT NOT NULL,
            contract_hash TEXT NOT NULL DEFAULT '',
            evidence_refs_json TEXT NOT NULL DEFAULT '[]',
            visible INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(message_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (turn_id) REFERENCES chat_turns(id) ON DELETE CASCADE,
            FOREIGN KEY (message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_generation_id) REFERENCES assistant_generations(id) ON DELETE SET NULL
        );

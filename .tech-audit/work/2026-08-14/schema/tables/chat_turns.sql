CREATE TABLE chat_turns (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            client_request_id TEXT NOT NULL,
            fence INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'cancelled', 'completed', 'failed')),
            user_message_id INTEGER,
            assistant_message_id INTEGER,
            cancel_reason TEXT,
            error_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at TIMESTAMP, request_fingerprint TEXT NOT NULL DEFAULT '', revision_of_message_id INTEGER,
            FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (user_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
            FOREIGN KEY (assistant_message_id) REFERENCES chat_messages(id) ON DELETE SET NULL,
            UNIQUE (conversation_id, client_request_id)
        );

CREATE TABLE chat_tool_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            message_id INTEGER,
            react_step INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            sanitized_args_json TEXT NOT NULL,
            result_summary_json TEXT NOT NULL,
            elapsed_ms INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

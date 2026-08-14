CREATE TABLE merge_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        survivor_id INTEGER NOT NULL,
        merged_ids TEXT NOT NULL,
        merged_questions TEXT NOT NULL,
        pre_snapshot TEXT NOT NULL,
        post_snapshot TEXT NOT NULL,
        operation_type TEXT DEFAULT 'auto',
        phase TEXT DEFAULT '',
        confidence REAL DEFAULT 0,
        cat2 TEXT DEFAULT '',
        operator_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    , is_rolled_back INTEGER DEFAULT 0, rolled_back_at TIMESTAMP, rolled_back_by INTEGER);

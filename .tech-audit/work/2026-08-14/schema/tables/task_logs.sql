CREATE TABLE task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_type TEXT NOT NULL,
    result TEXT,
    elapsed_seconds REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

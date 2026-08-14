CREATE TABLE analysis_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interview_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP, question_detail_id INTEGER, owner_id INTEGER DEFAULT NULL,
                FOREIGN KEY (interview_id) REFERENCES interview(id)
            );

CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                bank_mode TEXT DEFAULT 'public',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            , current_position_id INTEGER REFERENCES job_positions(id), updated_at TIMESTAMP, personal_position TEXT, email TEXT, share_default TEXT DEFAULT 'private');

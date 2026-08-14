CREATE TABLE refresh_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                jti TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, remember INTEGER DEFAULT 0, ip_address TEXT DEFAULT '', user_agent TEXT DEFAULT '', family_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );

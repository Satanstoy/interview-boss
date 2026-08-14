CREATE TABLE coding_playlist_items (
            playlist_id INTEGER NOT NULL,
            problem_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (playlist_id, problem_id),
            FOREIGN KEY (playlist_id) REFERENCES coding_playlists(id) ON DELETE CASCADE,
            FOREIGN KEY (problem_id) REFERENCES coding_problems(id) ON DELETE CASCADE
        );

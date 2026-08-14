CREATE TABLE practice_deck_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (deck_id) REFERENCES practice_decks(id) ON DELETE CASCADE,
            FOREIGN KEY (question_bank_id) REFERENCES question_bank(id) ON DELETE CASCADE,
            UNIQUE (deck_id, question_bank_id)
        );

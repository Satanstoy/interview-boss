CREATE TABLE question_variant_owners (
            normalized_question TEXT PRIMARY KEY,
            question_bank_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
            question_text TEXT NOT NULL,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

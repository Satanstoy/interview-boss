CREATE TABLE question_position (
                question_id INTEGER NOT NULL,
                position_id INTEGER NOT NULL,
                PRIMARY KEY (question_id, position_id),
                FOREIGN KEY (question_id) REFERENCES question_bank(id) ON DELETE CASCADE,
                FOREIGN KEY (position_id) REFERENCES job_positions(id) ON DELETE CASCADE
            );

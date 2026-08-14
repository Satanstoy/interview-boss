CREATE VIRTUAL TABLE question_fts USING fts5(
            question,
            cat1,
            cat2,
            tags,
            ai_answer,
            tokenize='unicode61'
        );

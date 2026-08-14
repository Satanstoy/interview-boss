CREATE TABLE invalidated_families (
                family_id TEXT PRIMARY KEY,
                invalidated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

"""复习提交幂等键（audit D14）。

给 practice_review_events 增加可选 idempotency_key 列，并用部分唯一索引
(user_id, question_bank_id, idempotency_key) 兜底防止重发双写。
"""


def _migration_088_practice_review_idempotency(conn):
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(practice_review_events)")
    }
    if "idempotency_key" not in columns:
        conn.execute(
            "ALTER TABLE practice_review_events ADD COLUMN idempotency_key TEXT"
        )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_practice_events_idempotency "
        "ON practice_review_events(user_id, question_bank_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )

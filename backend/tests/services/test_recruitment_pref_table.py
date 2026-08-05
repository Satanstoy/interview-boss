from app.db.connection import get_db_connection


def test_user_recruitment_pref_table_exists(test_db):
    with get_db_connection() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(user_recruitment_pref)").fetchall()]
    assert "user_id" in cols
    assert "graduation_year" in cols
    assert "batch" in cols
    assert "daily_capacity" in cols


def test_pref_upsert_roundtrip(test_db):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
            "VALUES (7, 2027, 'autumn', 30, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET graduation_year = excluded.graduation_year, "
            "batch = excluded.batch, daily_capacity = excluded.daily_capacity, updated_at = CURRENT_TIMESTAMP"
        )
        row = conn.execute(
            "SELECT graduation_year, batch, daily_capacity FROM user_recruitment_pref WHERE user_id = 7"
        ).fetchone()
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, updated_at) "
            "VALUES (7, 2027, 'spring', 20, CURRENT_TIMESTAMP) "
            "ON CONFLICT(user_id) DO UPDATE SET graduation_year = excluded.graduation_year, "
            "batch = excluded.batch, daily_capacity = excluded.daily_capacity, updated_at = CURRENT_TIMESTAMP"
        )
        updated = conn.execute(
            "SELECT batch, daily_capacity FROM user_recruitment_pref WHERE user_id = 7"
        ).fetchone()
        conn.commit()
    assert row["graduation_year"] == 2027
    assert updated["batch"] == "spring"
    assert updated["daily_capacity"] == 20

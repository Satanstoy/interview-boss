import sqlite3


def test_jd_bonus_migration_adds_column_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE jd (id INTEGER PRIMARY KEY, company TEXT)")

    from app.db.migrations.question_bank import _migration_118_jd_bonus

    _migration_118_jd_bonus(conn)
    _migration_118_jd_bonus(conn)

    columns = {row[1] for row in conn.execute("PRAGMA table_info('jd')")}
    assert "bonus" in columns


def test_jd_bonus_migration_is_registered_after_latest_migration():
    from app.db.migrations import _MIGRATIONS

    versions = [version for version, _, _ in _MIGRATIONS]
    assert 118 in versions
    assert versions.index(118) < versions.index(119)

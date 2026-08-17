"""P0-B: repair historical FK orphans and protect destructive migrations."""

import sqlite3

from app.db import connection as connection_module
from app.db import migrations


def _orphan_fixture() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        CREATE TABLE chat_conversations (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id)
        );
        CREATE TABLE question_bank (id INTEGER PRIMARY KEY);
        CREATE TABLE interview_asked_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            conversation_id TEXT NOT NULL REFERENCES chat_conversations(id),
            question_id INTEGER NOT NULL REFERENCES question_bank(id)
        );
        """
    )
    conn.execute("INSERT INTO users(id) VALUES (1)")
    conn.execute("INSERT INTO chat_conversations(id, user_id) VALUES ('valid', 1)")
    conn.execute("INSERT INTO question_bank(id) VALUES (10)")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO interview_asked_questions(user_id, conversation_id, question_id) "
        "VALUES (1, 'valid', 10)"
    )
    conn.execute(
        "INSERT INTO interview_asked_questions(user_id, conversation_id, question_id) "
        "VALUES (1, 'missing-conversation', 10)"
    )
    conn.execute(
        "INSERT INTO interview_asked_questions(user_id, conversation_id, question_id) "
        "VALUES (1, 'valid', 999)"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def test_migration_091_removes_fk_orphans_and_preserves_valid_rows():
    repair = getattr(migrations, "migration_091_repair_fk_orphans", None)
    assert callable(repair)

    conn = _orphan_fixture()
    repair(conn)

    rows = conn.execute(
        "SELECT conversation_id, question_id FROM interview_asked_questions"
    ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [("valid", 10)]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_migration_090_and_091_are_destructive_and_backed_up():
    assert {90, 91}.issubset(migrations.DESTRUCTIVE_VERSIONS)


def test_migration_connection_enables_foreign_keys_before_running_migrations():
    prepare = getattr(connection_module, "prepare_migration_connection", None)
    assert callable(prepare)

    class FakeConnection:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(statement)

    conn = FakeConnection()
    assert prepare(conn) is conn
    assert conn.statements[0] == "PRAGMA foreign_keys=ON"

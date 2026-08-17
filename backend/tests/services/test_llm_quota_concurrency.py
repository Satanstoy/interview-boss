"""Concurrency contract for the per-user LLM quota."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import app.services.llm_quota as quota


class _GatedConnection:
    """Pause the initial reads so competing callers hit the same boundary."""

    def __init__(self, conn: sqlite3.Connection, gate: threading.Barrier):
        self._conn = conn
        self._gate = gate

    def execute(self, sql, params=()):
        if sql.lstrip().startswith("SELECT call_count"):
            self._gate.wait(timeout=5)
        return self._conn.execute(sql, params)

    def commit(self):
        return self._conn.commit()


def test_concurrent_calls_cannot_both_pass_the_daily_limit(tmp_path):
    db_path = tmp_path / "quota.sqlite3"
    bootstrap = sqlite3.connect(db_path)
    bootstrap.execute("PRAGMA journal_mode=WAL")
    bootstrap.execute(
        "CREATE TABLE llm_usage ("
        "user_id INTEGER NOT NULL, day TEXT NOT NULL, "
        "call_count INTEGER NOT NULL, total_tokens INTEGER NOT NULL, "
        "UNIQUE(user_id, day))"
    )
    bootstrap.commit()
    bootstrap.close()

    gate = threading.Barrier(2)

    def attempt(_):
        conn = sqlite3.connect(db_path, timeout=5, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            return quota._increment_usage(
                _GatedConnection(conn, gate),
                user_id=7,
                day="2026-08-17",
                limit=1,
            )
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))

    assert sorted(results) == [False, True]

    verify = sqlite3.connect(db_path)
    row = verify.execute(
        "SELECT call_count FROM llm_usage WHERE user_id = 7 AND day = '2026-08-17'"
    ).fetchone()
    verify.close()
    assert row[0] == 1

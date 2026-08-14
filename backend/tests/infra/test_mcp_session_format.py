"""MCP session SQLite fallback 时间戳格式测试（迁移 084 后 updated_at 为 TEXT ISO）。"""

from __future__ import annotations

import sqlite3


class TestMcpSessionIsoTimestamps:
    def _make_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE mcp_sessions ("
            "session_id TEXT PRIMARY KEY, data_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        return conn

    def test_save_and_prune_use_iso_text(self, monkeypatch):
        conn = self._make_conn()
        import app.mcp_server.session as s

        monkeypatch.setattr(s, "_sqlite_conn", lambda: conn)

        s._save_to_sqlite("sess-1", {"k": "v"})
        row = conn.execute("SELECT updated_at FROM mcp_sessions WHERE session_id='sess-1'").fetchone()
        assert row is not None
        assert isinstance(row["updated_at"], str)
        assert row["updated_at"].count(" ") == 1  # 'YYYY-MM-DD HH:MM:SS'
        # 未过期：保留
        s._prune_sqlite_sessions(conn)
        assert conn.execute("SELECT count(*) FROM mcp_sessions").fetchone()[0] == 1

    def test_prune_removes_expired_text_rows(self, monkeypatch):
        conn = self._make_conn()
        import app.mcp_server.session as s

        monkeypatch.setattr(s, "_sqlite_conn", lambda: conn)
        conn.execute(
            "INSERT INTO mcp_sessions (session_id, data_json, updated_at) "
            "VALUES ('old', '{}', datetime('now', '-2 hours'))"
        )
        conn.commit()
        s._prune_sqlite_sessions(conn)
        assert conn.execute("SELECT count(*) FROM mcp_sessions").fetchone()[0] == 0

    def test_table_ddl_matches_migration_084(self):
        import app.mcp_server.session as s

        conn = sqlite3.connect(":memory:")
        s._ensure_sqlite_table(conn)
        typ = [r[2] for r in conn.execute("PRAGMA table_info('mcp_sessions')") if r[1] == "updated_at"][0]
        assert typ.upper() == "TEXT"
        conn.close()

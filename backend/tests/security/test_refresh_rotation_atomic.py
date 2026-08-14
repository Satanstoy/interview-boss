"""BUG-D4: refresh token 轮转 check-then-delete 非原子。

并发同 jti 的两个刷新请求都应严格只允许一个成功轮转——
单条原子 DELETE（jti + expires_at > now + user_id）以影响行数判定：
1 行 = 有效并已轮转；0 行 = 已用/过期/用户不匹配，调用方应 401。

测试对象：app.core.auth.consume_refresh_token
"""
import os
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from app.core.auth import consume_refresh_token
from app.db.connection import get_db_connection


def _seed_user(test_db, user_id=1):
    """refresh_tokens.user_id 有 FK 到 users.id，先插入一个有效用户。

    用随机后缀避免与其他测试/迁移 seed 撞 username/email 唯一约束。
    """
    import uuid

    suf = uuid.uuid4().hex[:8]
    with get_db_connection() as conn:
        # users.password_hash 为 NOT NULL，用明显示例占位（禁止硬编码真实密钥）
        conn.execute(
            "INSERT OR IGNORE INTO users "
            "(id, username, password_hash, email, is_admin, share_default) "
            "VALUES (?, ?, ?, ?, 0, 'private')",
            (user_id, f"user_{suf}", "TEST_PASSWORD_PLACEHOLDER", f"user_{suf}@example.test"),
        )
        conn.commit()


def _insert_token(test_db, jti="j1", user_id=1, days=1, expired=False):
    _seed_user(test_db, user_id)
    base = datetime.now(timezone.utc)
    expires = base - timedelta(days=1) if expired else base + timedelta(days=days)
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO refresh_tokens "
            "(user_id, jti, expires_at, created_at, remember, ip_address, user_agent, family_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                jti,
                expires.isoformat(),
                base.isoformat(),
                1,
                "1.2.3.4",
                "test-agent",
                f"fam-{jti}",
            ),
        )
        conn.commit()


def _count(test_db, jti):
    with get_db_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM refresh_tokens WHERE jti = ?", (jti,)
        ).fetchone()[0]


CREATE_REFRESH_TABLE = """
CREATE TABLE refresh_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    jti TEXT UNIQUE NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT,
    remember INTEGER DEFAULT 0,
    ip_address TEXT DEFAULT '',
    user_agent TEXT DEFAULT '',
    family_id TEXT
)
"""


def _atomic_consume_on_conn(conn, jti, user_id):
    """对传入的连接执行生产同款单条原子 DELETE RETURNING。"""
    row = conn.execute(
        "DELETE FROM refresh_tokens WHERE jti = ? AND expires_at > ? AND user_id = ? "
        "RETURNING *",
        (jti, datetime.now(timezone.utc).isoformat(), user_id),
    ).fetchone()
    conn.commit()
    return dict(row) if row else None


class TestAtomicRefreshRotation:
    def test_consume_valid_token_returns_record_and_removes(self, test_db):
        """有效且未过期的 refresh token：一次性消费，1 行删除，返回该记录。"""
        _insert_token(test_db, jti="j-valid")
        record = consume_refresh_token("j-valid", 1)
        assert record is not None
        assert record["user_id"] == 1
        assert record["family_id"] == "fam-j-valid"
        assert record["remember"] == 1
        assert _count(test_db, "j-valid") == 0

    def test_replay_second_consume_returns_none(self, test_db):
        """轮转后重放同 jti：0 行删除，返回 None → 401。"""
        _insert_token(test_db, jti="j-replay")
        first = consume_refresh_token("j-replay", 1)
        assert first is not None
        # 第二次（重放）不能再消费
        assert consume_refresh_token("j-replay", 1) is None
        assert _count(test_db, "j-replay") == 0

    def test_expired_token_returns_none(self, test_db):
        """已过期 token：0 行删除，返回 None（记录留给 retention 清理）。"""
        _insert_token(test_db, jti="j-expired", expired=True)
        assert consume_refresh_token("j-expired", 1) is None
        assert _count(test_db, "j-expired") == 1

    def test_wrong_user_returns_none(self, test_db):
        """token 属于其他用户：不作为本用户轮转对象，返回 None 且不删除。"""
        _insert_token(test_db, jti="j-other", user_id=42)
        assert consume_refresh_token("j-other", 1) is None
        assert _count(test_db, "j-other") == 1

    def test_concurrent_same_jti_only_one_wins(self):
        """并发同 jti 的多个连接（生产同款单条原子 DELETE）恰有一个成功。

        用临时文件 SQLite + 每线程独立连接 + WAL，模拟生产并发：SQLite 写锁
        保证只有一个 DELETE 匹配到该行，其余 0 行 → 失败（None）。
        """
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn0 = sqlite3.connect(path, timeout=30)
            conn0.execute("PRAGMA journal_mode=WAL")
            conn0.execute("PRAGMA foreign_keys=ON")
            conn0.execute("PRAGMA busy_timeout=10000")
            conn0.execute(CREATE_REFRESH_TABLE)
            now = datetime.now(timezone.utc)
            conn0.execute(
                "INSERT INTO refresh_tokens (user_id, jti, expires_at, created_at, family_id) "
                "VALUES (1, 'j-race', ?, ?, 'fam-race')",
                ((now + timedelta(days=1)).isoformat(), now.isoformat()),
            )
            conn0.commit()

            n = 8
            results = [None] * n
            barrier = threading.Barrier(n)

            def worker(idx):
                c = sqlite3.connect(path, timeout=30)
                c.row_factory = sqlite3.Row
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA busy_timeout=10000")
                try:
                    barrier.wait()
                    r = _atomic_consume_on_conn(c, "j-race", 1)
                    results[idx] = 0 if r is None else 1
                finally:
                    c.close()

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # 恰有一个成功，其余失败（None）
            assert sum(results) == 1
            checker = sqlite3.connect(path)
            left = checker.execute(
                "SELECT COUNT(*) FROM refresh_tokens WHERE jti='j-race'"
            ).fetchone()[0]
            checker.close()
            assert left == 0
        finally:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(path + suffix)
                except OSError:
                    pass

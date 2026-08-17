"""
测试数据库连接隔离 — contextvars vs threading.local

验证：
1. contextvar 在线程间隔离
2. asyncio.to_thread() 能访问 contextvar 中的连接
3. 替换 threading.local 后现有测试不回归
"""

import asyncio
import sqlite3
import threading
from contextvars import ContextVar

import pytest


# ── 测试用 contextvar ──────────────────────────────────────────

_test_conn_var: ContextVar[sqlite3.Connection | None] = ContextVar(
    "_test_conn_var", default=None
)


def _get_test_connection() -> sqlite3.Connection | None:
    """获取当前上下文中的测试连接"""
    return _test_conn_var.get()


def _set_test_connection(conn: sqlite3.Connection) -> None:
    """设置当前上下文中的测试连接"""
    _test_conn_var.set(conn)


# ── 测试用例 ──────────────────────────────────────────────────


class TestContextVarIsolation:
    """测试 contextvar 在线程间的隔离性"""

    def test_different_threads_have_different_connections(self):
        """两个线程各自设置不同连接，互不影响"""
        conn1 = sqlite3.connect(":memory:", check_same_thread=False)
        conn2 = sqlite3.connect(":memory:", check_same_thread=False)

        results = {}

        def worker(name: str, conn: sqlite3.Connection):
            _set_test_connection(conn)
            # 模拟一些工作
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.execute(f"INSERT INTO test VALUES (1)")
            conn.commit()
            # 读取连接
            results[name] = _get_test_connection()

        t1 = threading.Thread(target=worker, args=("thread1", conn1))
        t2 = threading.Thread(target=worker, args=("thread2", conn2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 验证每个线程访问到自己的连接
        assert results["thread1"] is conn1
        assert results["thread2"] is conn2

        # 验证数据隔离
        assert results["thread1"].execute("SELECT COUNT(*) FROM test").fetchone()[0] == 1
        assert results["thread2"].execute("SELECT COUNT(*) FROM test").fetchone()[0] == 1

        conn1.close()
        conn2.close()

    def test_main_thread_isolation(self):
        """主线程的连接不被子线程影响"""
        main_conn = sqlite3.connect(":memory:")
        main_conn.execute("CREATE TABLE main_test (id INTEGER)")
        _set_test_connection(main_conn)

        child_results = {}

        def child_worker():
            # 子线程不设置连接，应该获取到 None
            child_results["connection"] = _get_test_connection()

        t = threading.Thread(target=child_worker)
        t.start()
        t.join()

        # 子线程获取不到主线程的连接
        assert child_results["connection"] is None

        # 主线程仍然可以访问
        assert _get_test_connection() is main_conn

        main_conn.close()


class TestAsyncioToThreadPreservation:
    """测试 asyncio.to_thread() 能访问 contextvar 中的连接"""

    @pytest.mark.asyncio
    async def test_to_thread_accesses_contextvar(self):
        """asyncio.to_thread() 内部能访问到 contextvar 中的连接"""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("CREATE TABLE async_test (id INTEGER)")
        conn.execute("INSERT INTO async_test VALUES (42)")
        conn.commit()

        _set_test_connection(conn)

        def get_connection_in_thread():
            """在子线程中获取连接"""
            return _get_test_connection()

        result = await asyncio.to_thread(get_connection_in_thread)

        # asyncio.to_thread 应该能访问到主线程设置的 contextvar
        # 注意：这取决于 contextvars 是否在线程间传播
        # 标准库的 contextvars 在 asyncio.to_thread 中会复制当前上下文
        assert result is conn

        conn.close()

    @pytest.mark.asyncio
    async def test_to_thread_can_use_connection(self):
        """asyncio.to_thread() 内部能使用连接执行查询"""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("CREATE TABLE worker_test (id INTEGER, value TEXT)")
        conn.execute("INSERT INTO worker_test VALUES (1, 'hello')")
        conn.commit()

        _set_test_connection(conn)

        def query_in_thread():
            """在子线程中执行查询"""
            c = _get_test_connection()
            if c is None:
                return None
            # 使用 row_factory 确保返回 Row 对象
            c.row_factory = sqlite3.Row
            return c.execute("SELECT value FROM worker_test WHERE id = 1").fetchone()

        result = await asyncio.to_thread(query_in_thread)

        assert result is not None
        # sqlite3.Row 支持字典访问
        assert dict(result)["value"] == "hello"

        conn.close()


class TestBackwardCompatibility:
    """验证替换 threading.local 后现有测试不回归"""

    def test_get_db_connection_returns_same_connection(self):
        """多次调用 get_db_connection 返回同一个连接对象"""
        from app.db.connection import get_db_connection

        conn1 = get_db_connection()
        conn2 = get_db_connection()

        assert conn1 is conn2

    def test_get_db_connection_works_in_thread(self):
        """在子线程中调用 get_db_connection 也能工作"""
        from app.db.connection import get_db_connection

        results = {}

        def worker():
            try:
                conn = get_db_connection()
                results["connection"] = conn
                results["success"] = True
            except Exception as e:
                results["error"] = str(e)
                results["success"] = False

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # 子线程应该能获取到连接（可能是新连接，因为 threading.local）
        assert results.get("success", False) is True
        assert results.get("connection") is not None

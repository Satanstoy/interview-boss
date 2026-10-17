"""DB 隔离 fixture 的还原契约回归。

历史缺陷（2026-10-01 定位）：`client` / `app_db_isolation` 的 teardown 用
「当时的当前值」当还原目标。一旦某个模块残留了上一次 fixture 的测试闭包
（`...<locals>._test_get_db_connection`，闭包捕获了已关闭的内存连接），
那个闭包就会被当成 original 保存并在下次 teardown 再装回去——泄漏自我延续，
后续不使用 TestClient 的测试会拿到已关闭的连接，报
``sqlite3.ProgrammingError: Cannot operate on a closed database``。

修复：conftest 在打补丁前捕获真实实现（``_TRUE_GET_DB_CONNECTION``），
teardown 一律还原到它，并扫掉测试期间新导入的模块。

本文件顺序敏感：前两条先真实使用对应 fixture，最后一条断言还原结果。
"""

from __future__ import annotations

import sys

import app.db.connection as _db_module

# 在**收集期**捕获真实实现：此时任何 fixture 都还没打补丁。
# 不能用 `app.db.connection.get_db_connection` 现场取基准——泄漏同样会污染它，
# 那样断言会永远成立（空转）。
_TRUE_GET_DB_CONNECTION = _db_module.get_db_connection


def _stale_connection_factories() -> list[str]:
    """返回仍持有非真实 get_db_connection 的 app 模块名。"""

    offenders = []
    for name, mod in list(sys.modules.items()):
        if not name.startswith("app.") or mod is None:
            continue
        fn = getattr(mod, "get_db_connection", None)
        if fn is not None and fn is not _TRUE_GET_DB_CONNECTION:
            offenders.append(name)
    return offenders


def test_client_fixture_is_used_and_leaves_no_closed_connection(client):
    """真实走一次 TestClient 路径（会 patch 所有 app.* 模块）。"""

    response = client.get("/api/health")
    assert response.status_code in (200, 404)


def test_app_db_isolation_fixture_is_used(app_db_isolation):
    """真实使用 app_db_isolation（不使用 TestClient 的测试路径）。"""

    assert app_db_isolation is not None


def test_no_app_module_keeps_a_stale_get_db_connection():
    """teardown 之后所有 app.* 模块必须共用真实的 get_db_connection。"""

    assert _stale_connection_factories() == []


def test_stale_factory_would_be_detected():
    """自检：断言逻辑本身能识别出陈旧闭包（防止上面那条变成空转）。"""

    import app.db.operations as operations_module

    operations_module.get_db_connection = lambda: None
    try:
        assert "app.db.operations" in _stale_connection_factories()
    finally:
        operations_module.get_db_connection = _TRUE_GET_DB_CONNECTION

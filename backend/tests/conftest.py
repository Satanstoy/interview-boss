"""
pytest conftest — 测试基础设施

提供：
- DB 隔离：内存 SQLite，每个测试自动建表/清表
- Mock LLM：AsyncMock 替代真实 API
- Mock Redis：不依赖真实 Redis 服务
- Test Client：FastAPI TestClient + dependency_overrides
"""

import sys
import os
import sqlite3
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


# ── 代理清理（防止 socks5h 代理导致 httpx 初始化失败）────────────


@pytest.fixture(autouse=True, scope="session")
def _clear_socks_proxy():
    """清除 ALL_PROXY/all_proxy 环境变量，避免 httpx 不支持 socks5h 协议"""
    for key in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    yield


# 将 backend 目录添加到 Python 路径
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)


def pytest_collection_modifyitems(config, items):
    """Keep live LLM checks out of the default offline suite."""
    if os.environ.get("RUN_LIVE_LLM_TESTS") == "1":
        return

    kept = []
    deselected = []
    for item in items:
        if item.get_closest_marker("live_llm"):
            deselected.append(item)
        else:
            kept.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


# ── DB 隔离（核心）─────────────────────────────────────────────


@pytest.fixture
def test_db():
    """每个测试用内存 SQLite，自动建表/清表，绝不碰生产数据库"""
    from app.db.migrations import run_migrations

    # 确保 migration 012 (admin_seed) 能正常运行
    # 使用明显的测试值，不包含真实密码
    os.environ.setdefault("ADMIN_PASSWORD", "TEST_PASSWORD_PLACEHOLDER")

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    # jd 和 questions_detail 表在迁移系统建立前就存在，需要手动创建
    # 包含所有迁移系统可能引用的列
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            company TEXT,
            season TEXT DEFAULT '',
            owner_id INTEGER,
            status TEXT DEFAULT 'approved',
            url_signature TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            job_position TEXT DEFAULT '',
            deleted_at TIMESTAMP,
            tech_stack TEXT,
            source TEXT DEFAULT '',
            position TEXT DEFAULT '',
            salary TEXT DEFAULT '',
            job_title TEXT DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            interview_id INTEGER,
            question TEXT,
            cat1 TEXT,
            cat2 TEXT,
            tags TEXT,
            difficulty TEXT,
            diff_tag TEXT,
            answer TEXT,
            url TEXT,
            source TEXT DEFAULT '',
            owner_id INTEGER,
            status TEXT DEFAULT 'approved',
            deleted_at TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            company TEXT DEFAULT '',
            round TEXT DEFAULT '',
            job_position TEXT DEFAULT ''
        )
    """)

    run_migrations(conn)

    # 清理 seed 数据，让每个测试从干净状态开始
    conn.execute("DELETE FROM coding_submissions")
    conn.execute("DELETE FROM coding_problems")
    conn.commit()

    # 替换生产 DB 连接
    import app.db.connection as db_module

    # 使用 ContextVar 替代 threading.local
    original_token = db_module._db_conn_var.set(conn)

    yield conn

    conn.close()
    db_module._db_conn_var.reset(original_token)


# ── Mock LLM ─────────────────────────────────────────────────


@pytest.fixture
def mock_llm():
    """Mock AsyncOpenAI，禁止测试时调用真实 LLM API"""
    with patch("app.services.llm.AsyncOpenAI") as mock_cls:
        client = AsyncMock()
        mock_cls.return_value = client
        yield client


# ── Mock Redis ───────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    """Mock redis.Redis，不依赖真实 Redis 服务"""
    with patch("redis.Redis") as mock_cls:
        client = MagicMock()
        mock_cls.return_value = client
        yield client


# ── Test Client ──────────────────────────────────────────────


@pytest.fixture
def client(test_db):
    """FastAPI TestClient，已替换 DB 依赖"""
    from fastapi.testclient import TestClient
    import app.db.connection as db_module
    import app.core.config as config_module

    # 强制 run_db 在测试中同步执行（避免 asyncio.to_thread 的线程隔离问题）
    async def _sync_run_db(func):
        return func()

    db_module.run_db = _sync_run_db

    # 如果 asgi 模块还没导入，跳过其 init_db
    if "app.asgi" not in sys.modules:
        original_init = db_module.init_db
        db_module.init_db = lambda: None
        from app.asgi import app

        db_module.init_db = original_init
    else:
        from app.asgi import app

    # 强制连接指向 test_db
    db_module._db_conn_var.set(test_db)

    # 额外 patch 模块本身的 get_db_connection，兜底拦截 `app.db.connection.get_db_connection()`
    # 的直接调用（如 TestClient 线程内 _local.conn 为空时，会走到真实 DB_PATH 连接生产库）。
    # 注意：返回 test_db 连接对象本身（sqlite3.Connection 既是 context manager 也支持
    # 直接 .execute()），不能包一层 contextmanager，否则破坏 `conn = get_db_connection()` 用法。
    def _test_get_db_connection():
        return test_db

    _module_patches = []
    for mod_name in ("app.db.connection", "app.db.operations", "app.db.queries"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "get_db_connection"):
            _module_patches.append((mod, mod.get_db_connection))
            mod.get_db_connection = _test_get_db_connection

    # 路由模块用 `from app.db.connection import run_db, get_db_connection` 导入，
    # 拷贝了函数引用。修改 db_module 上的属性不会影响已导入的副本。
    # 必须在每个已导入模块上直接 patch。
    _patches = {}
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("app.") and mod:
            if hasattr(mod, "run_db") and mod.run_db is not _sync_run_db:
                _patches[f"{mod_name}.run_db"] = (mod, "run_db", mod.run_db)
                mod.run_db = _sync_run_db
            if hasattr(mod, "get_db_connection"):
                _patches[f"{mod_name}.get_db_connection"] = (
                    mod,
                    "get_db_connection",
                    mod.get_db_connection,
                )
                mod.get_db_connection = _test_get_db_connection

    c = TestClient(app)
    yield c
    c.close()

    # 恢复原始函数引用
    for _, (mod, attr, orig) in _patches.items():
        setattr(mod, attr, orig)
    for mod, orig in _module_patches:
        mod.get_db_connection = orig

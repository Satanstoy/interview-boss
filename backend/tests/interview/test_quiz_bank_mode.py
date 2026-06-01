"""
自动化测试 — 针对 BUG-001: bank_mode 未定义导致抽测 API 500
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
import sqlite3
import os
import sys
from unittest.mock import patch


TEST_USER = {
    "id": 1,
    "username": "testuser",
    "bank_mode": "public",
    "job_position": "agent开发/大模型应用开发/大模型开发",
}


def _make_test_db():
    """创建独立的跨线程 SQLite 测试库"""
    # 使用明显的测试值，不包含真实密码
    os.environ.setdefault("ADMIN_PASSWORD", "TEST_PASSWORD_PLACEHOLDER")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute('''
        CREATE TABLE IF NOT EXISTS jd (
            id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, company TEXT,
            season TEXT DEFAULT '', owner_id INTEGER, status TEXT DEFAULT 'approved',
            url_signature TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            job_position TEXT DEFAULT '', deleted_at TIMESTAMP, tech_stack TEXT,
            source TEXT DEFAULT '', position TEXT DEFAULT '', salary TEXT DEFAULT '',
            job_title TEXT DEFAULT ''
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS questions_detail (
            id INTEGER PRIMARY KEY AUTOINCREMENT, interview_id INTEGER, question TEXT,
            cat1 TEXT, cat2 TEXT, tags TEXT, difficulty TEXT, answer TEXT, url TEXT,
            source TEXT DEFAULT '', owner_id INTEGER, status TEXT DEFAULT 'approved',
            deleted_at TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            company TEXT DEFAULT '', round TEXT DEFAULT '', job_position TEXT DEFAULT ''
        )
    ''')
    from app.db.migrations import run_migrations
    run_migrations(conn)
    conn.execute(
        "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, ai_answer, owner_id, status, job_position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("什么是RESTful API？", "后端", "网络", "API", "简单", "参考答案", None, "approved",
         "agent开发/大模型应用开发/大模型开发"),
    )
    conn.commit()
    return conn


@pytest.fixture
def auth_client():
    """自包含的 TestClient：mock 所有 DB 依赖"""
    import app.db.connection as db_module
    from app.core.auth import get_current_user

    conn = _make_test_db()

    async def _sync_run_db(func):
        return func()

    original_run = db_module.run_db
    original_get = db_module.get_db_connection
    db_module.run_db = _sync_run_db
    db_module.get_db_connection = lambda: conn

    if 'app.asgi' not in sys.modules:
        orig_init = db_module.init_db
        db_module.init_db = lambda: None
        from app.asgi import app
        db_module.init_db = orig_init
    else:
        from app.asgi import app

    # 同时 mock 掉 practice 模块中导入的 get_db_connection
    with patch('app.routers.practice.get_db_connection', return_value=conn):
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        from fastapi.testclient import TestClient
        c = TestClient(app)
        yield c
        app.dependency_overrides.clear()
        c.close()

    db_module.run_db = original_run
    db_module.get_db_connection = original_get
    conn.close()


class TestBug001QuizBankModeUndefined:
    """BUG-001: bank_mode 变量未定义导致 GET /api/master-bank/random 返回 500"""

    def test_quiz_should_return_questions(self, auth_client):
        """修复后：抽测 API 应正常返回题目列表"""
        resp = auth_client.get("/api/master-bank/random?count=5")
        assert resp.status_code == 200, f"预期 200，实际 {resp.status_code}: {resp.text}"
        data = resp.json()
        assert len(data) >= 1, "应返回至少 1 道题目"
        assert "question" in data[0], "返回数据应包含 question 字段"

    def test_quiz_with_category_filter(self, auth_client):
        """修复后：带领域筛选的抽测应正常工作"""
        resp = auth_client.get("/api/master-bank/random?count=5&cat1=后端")
        assert resp.status_code == 200, f"status={resp.status_code}, text={resp.text}"
        data = resp.json()
        assert len(data) >= 1, f"应返回至少1道题目, 实际: {data}"

    def test_quiz_with_difficulty_filter(self, auth_client):
        """修复后：带难度筛选的抽测应正常工作"""
        resp = auth_client.get("/api/master-bank/random?count=5&difficulty=简单")
        assert resp.status_code == 200, f"status={resp.status_code}, text={resp.text}"
        data = resp.json()
        assert len(data) >= 1, f"应返回至少1道题目, 实际: {data}"

    def test_quiz_empty_when_no_match(self, auth_client):
        """修复后：无匹配条件时应返回空列表"""
        resp = auth_client.get("/api/master-bank/random?count=5&cat1=不存在的领域")
        assert resp.status_code == 200
        data = resp.json()
        assert data == [], "无匹配时应返回空列表"

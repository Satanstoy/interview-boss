"""
Coding module tests — 手撕代码模块测试
"""
import json
import pytest
from unittest.mock import AsyncMock, patch


# ── Helper ──

def _create_user(conn, username="testuser", password_hash="hashed"):
    """创建测试用户"""
    conn.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (username, password_hash)
    )
    conn.commit()
    return conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]


def _create_problem(conn, title="测试题目", difficulty="easy"):
    """创建测试题目"""
    conn.execute(
        "INSERT INTO coding_problems (title, description, difficulty, tags, expected_complexity) VALUES (?, ?, ?, ?, ?)",
        (title, "测试题目描述。", difficulty, '["数组","哈希表"]', "O(n)")
    )
    conn.commit()
    return conn.execute("SELECT id FROM coding_problems WHERE title = ?", (title,)).fetchone()["id"]


@pytest.fixture
def auth_client(client, test_db):
    """带认证的 TestClient"""
    from app.asgi import app
    from app.core.auth import get_current_user

    user_id = _create_user(test_db)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id, "username": "testuser", "is_admin": 0}

    yield client, user_id

    app.dependency_overrides.clear()


# ── 题目列表 ──

class TestCodingProblems:
    def test_get_problems_empty(self, auth_client):
        """无题目时返回空列表"""
        client, _ = auth_client
        resp = client.get("/api/coding/problems")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["problems"] == []

    def test_get_problems_with_data(self, auth_client, test_db):
        """有题目时返回列表"""
        client, _ = auth_client
        _create_problem(test_db, "题目A", "easy")
        _create_problem(test_db, "题目B", "medium")

        resp = client.get("/api/coding/problems")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["problems"]) == 2

    def test_get_problems_filter_difficulty(self, auth_client, test_db):
        """按难度筛选"""
        client, _ = auth_client
        _create_problem(test_db, "简单题", "easy")
        _create_problem(test_db, "中等题", "medium")

        resp = client.get("/api/coding/problems?difficulty=easy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["problems"][0]["title"] == "简单题"

    def test_get_problem_detail(self, auth_client, test_db):
        """获取单题详情"""
        client, _ = auth_client
        pid = _create_problem(test_db)

        resp = client.get(f"/api/coding/problems/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "测试题目"
        assert "description" in data
        assert isinstance(data["tags"], list)

    def test_get_problem_not_found(self, auth_client):
        """题目不存在返回 404"""
        client, _ = auth_client
        resp = client.get("/api/coding/problems/999")
        assert resp.status_code == 404


# ── 代码提交 ──

class TestCodingSubmit:
    def test_submit_success(self, auth_client, test_db, mock_llm):
        """正常提交代码（SSE 流式）"""
        client, _ = auth_client
        pid = _create_problem(test_db)

        # Mock 流式 LLM 返回
        review_json = json.dumps({
            "feedback": "代码逻辑正确，使用了哈希表，时间复杂度 O(n)。",
            "scores": {"syntax": 5, "logic": 5, "algorithm": 5, "complexity": 5, "style": 4},
            "reference_answer": "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target-n], i]\n        seen[n] = i",
            "error_categories": [],
            "complexity_analysis": "O(n)，符合预期"
        })

        async def fake_stream(*args, **kwargs):
            for chunk in [review_json[:50], review_json[50:]]:
                yield chunk

        import app.routers.coding as coding_mod
        original_stream = coding_mod.stream_llm_messages
        coding_mod.stream_llm_messages = fake_stream

        try:
            resp = client.post("/api/coding/submit", json={
                "problem_id": pid,
                "language": "python",
                "code": "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target-n], i]\n        seen[n] = i",
                "mode": "full_review"
            })
            assert resp.status_code == 200
            # 解析 SSE 事件
            events = []
            for line in resp.text.split('\n'):
                if line.startswith('data: '):
                    events.append(json.loads(line[6:]))

            done_events = [e for e in events if e.get('type') == 'done']
            assert len(done_events) == 1
            done = done_events[0]
            assert done['total_score'] == 96  # (5+5+5+5+4) * 4
            assert 'syntax' in done['scores']
            assert done['scores']['syntax'] == 5
        finally:
            coding_mod.stream_llm_messages = original_stream

    def test_submit_invalid_language(self, auth_client, test_db):
        """无效语言返回 400"""
        client, _ = auth_client
        pid = _create_problem(test_db)

        resp = client.post("/api/coding/submit", json={
            "problem_id": pid,
            "language": "javascript",
            "code": "console.log('hi')",
            "mode": "full_review"
        })
        assert resp.status_code == 400

    def test_submit_empty_code(self, auth_client, test_db):
        """空代码返回 400"""
        client, _ = auth_client
        pid = _create_problem(test_db)

        resp = client.post("/api/coding/submit", json={
            "problem_id": pid,
            "language": "python",
            "code": "",
            "mode": "full_review"
        })
        assert resp.status_code == 400

    def test_submit_problem_not_found(self, auth_client):
        """题目不存在返回 404"""
        client, _ = auth_client

        resp = client.post("/api/coding/submit", json={
            "problem_id": 999,
            "language": "python",
            "code": "pass",
            "mode": "full_review"
        })
        assert resp.status_code == 404


# ── 提交历史 ──

class TestCodingSubmissions:
    def test_get_submissions_empty(self, auth_client):
        """无提交历史"""
        client, _ = auth_client
        resp = client.get("/api/coding/submissions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    def test_get_submission_detail_not_found(self, auth_client):
        """提交记录不存在"""
        client, _ = auth_client
        resp = client.get("/api/coding/submissions/999")
        assert resp.status_code == 404


# ── 错误统计 ──

class TestCodingErrorStats:
    def test_error_stats_empty(self, auth_client):
        """无数据时返回空统计"""
        client, _ = auth_client
        resp = client.get("/api/coding/error-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_submissions"] == 0
        assert data["passed_submissions"] == 0
        assert data["error_stats"] == {}


# ── 数据库迁移 ──

class TestCodingMigration:
    def test_tables_created(self, test_db):
        """migration 030 创建了正确的表"""
        cursor = test_db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'coding%'")
        tables = {row["name"] for row in cursor.fetchall()}
        assert "coding_problems" in tables
        assert "coding_submissions" in tables

    def test_problems_schema_has_required_columns(self, test_db):
        """coding_problems 表包含必要列"""
        cursor = test_db.execute("PRAGMA table_info(coding_problems)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "title" in columns
        assert "description" in columns
        assert "difficulty" in columns
        assert "tags" in columns
        assert "expected_complexity" in columns

    def test_submissions_schema_has_required_columns(self, test_db):
        """coding_submissions 表包含必要列"""
        cursor = test_db.execute("PRAGMA table_info(coding_submissions)")
        columns = {row["name"] for row in cursor.fetchall()}
        assert "user_id" in columns
        assert "problem_id" in columns
        assert "language" in columns
        assert "code" in columns
        assert "ai_feedback" in columns
        assert "error_categories" in columns
        assert "is_passed" in columns

"""BUG-001: bank_mode 未定义导致 GET /api/master-bank/random 返回 500。

原 `auth_client` fixture 自己造内存库、只 patch `app.db.connection`：其它模块
（`routers/questions` 等）在 import 时已拷贝了 `get_db_connection` 引用，拿到的
是真实实现。这组用例长期"通过"其实是 conftest 的陈旧闭包泄漏让那些模块碰巧
指向了上一个测试的内存库——泄漏修掉后立即暴露（2026-10-01）。
现改用标准 `client` + `test_db` fixture（conftest 会 patch 所有 app.* 模块）。
"""

import pytest

TEST_USER = {
    "id": 1,
    "username": "testuser",
    "bank_mode": "public",
    "job_position": "agent开发/大模型应用开发/大模型开发",
}


@pytest.fixture
def auth_client(client, test_db):
    from app.asgi import app
    from app.core.auth import get_current_user

    test_db.execute(
        "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, ai_answer, "
        "owner_id, status, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "什么是RESTful API？",
            "后端",
            "网络",
            "API",
            "简单",
            "参考答案",
            None,
            "approved",
            "agent开发/大模型应用开发/大模型开发",
        ),
    )
    test_db.commit()

    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    yield client
    app.dependency_overrides.pop(get_current_user, None)


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

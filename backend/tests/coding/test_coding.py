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

    def test_problem_list_exposes_personal_state_and_favorite_scope(self, auth_client, test_db):
        """列表返回收藏/刷题状态，并支持只看收藏。"""
        client, user_id = auth_client
        pid = _create_problem(test_db, "收藏题", "easy")
        _create_problem(test_db, "未收藏题", "medium")
        test_db.execute(
            "INSERT INTO coding_submissions (user_id, problem_id, language, code, mode, is_passed) "
            "VALUES (?, ?, 'python', 'pass', 'full_review', 1)",
            (user_id, pid),
        )
        test_db.commit()

        toggle = client.post(f"/api/coding/problems/{pid}/favorite", json={})
        assert toggle.status_code == 200
        assert toggle.json()["is_favorite"] is True

        data = client.get("/api/coding/problems?scope=favorites").json()
        assert data["total"] == 1
        assert data["problems"][0]["id"] == pid
        assert data["problems"][0]["is_favorite"] is True
        assert data["problems"][0]["attempt_count"] == 1
        assert data["problems"][0]["is_solved"] is True

    def test_playlist_crud_and_problem_filter(self, auth_client, test_db):
        """用户可以创建题单、加入题目并按题单浏览。"""
        client, _ = auth_client
        pid = _create_problem(test_db, "题单题目", "medium")

        playlist = client.post(
            "/api/coding/playlists",
            json={"name": "二叉树面试高频", "description": "面试前集中复习"},
        )
        assert playlist.status_code == 200
        playlist_id = playlist.json()["id"]

        added = client.post(
            f"/api/coding/playlists/{playlist_id}/items",
            json={"problem_id": pid},
        )
        assert added.status_code == 200
        assert added.json()["added"] is True

        data = client.get(f"/api/coding/problems?playlist_id={playlist_id}").json()
        assert data["total"] == 1
        assert data["problems"][0]["id"] == pid
        assert client.get("/api/coding/playlists").json()[0]["problem_count"] == 1

    def test_import_markdown_with_prompt_uses_llm_and_persists_owned_problems(self, auth_client, test_db, mock_llm):
        """Prompt + Markdown 导入会调用统一 LLM 基建并落为当前用户题目。"""
        client, user_id = auth_client
        llm_result = json.dumps(
            {
                "problems": [
                    {
                        "title": "LRU 缓存",
                        "description": "请实现一个固定容量的 LRU Cache。",
                        "difficulty": "hard",
                        "tags": ["哈希表", "双向链表"],
                        "expected_complexity": "O(1)",
                    }
                ]
            },
            ensure_ascii=False,
        )

        call = AsyncMock(return_value=llm_result)
        with patch("app.routers.coding.raw_llm_call", call):
            resp = client.post(
                "/api/coding/import",
                json={
                    "prompt": "提取算法题，补全缺失的输入输出和复杂度要求",
                    "markdown": "# LRU Cache\n\n实现一个 LRU 缓存。",
                    "filename": "我的面试题.md",
                },
            )

        assert resp.status_code == 200
        assert resp.json()["created"][0]["title"] == "LRU 缓存"
        assert call.call_count == 1
        row = test_db.execute(
            "SELECT owner_id, source_type, source FROM coding_problems WHERE title = ?",
            ("LRU 缓存",),
        ).fetchone()
        assert row["owner_id"] == user_id
        assert row["source_type"] == "imported"
        assert row["source"] == "我的面试题.md"

    def test_import_markdown_adds_created_problems_to_selected_playlist(self, auth_client, test_db):
        """导入题目时指定当前题单，新增题目应立即归入该题单。"""
        client, _ = auth_client
        playlist = client.post(
            "/api/coding/playlists",
            json={"name": "当前练习题单", "description": "导入归档"},
        )
        assert playlist.status_code == 200
        playlist_id = playlist.json()["id"]
        llm_result = json.dumps(
            {
                "problems": [
                    {
                        "title": "二叉树层序遍历",
                        "description": "给定一棵二叉树，返回其层序遍历结果。",
                        "difficulty": "medium",
                        "tags": ["树"],
                    }
                ]
            },
            ensure_ascii=False,
        )

        with patch("app.routers.coding.raw_llm_call", AsyncMock(return_value=llm_result)):
            resp = client.post(
                "/api/coding/import",
                json={
                    "prompt": "提取树相关手撕题",
                    "markdown": "# 二叉树层序遍历",
                    "filename": "树题.md",
                    "playlist_id": playlist_id,
                },
            )

        assert resp.status_code == 200
        playlist_problems = client.get(
            f"/api/coding/problems?scope=playlist&playlist_id={playlist_id}"
        ).json()
        assert playlist_problems["total"] == 1
        assert playlist_problems["problems"][0]["title"] == "二叉树层序遍历"
        assert client.get("/api/coding/playlists").json()[0]["problem_count"] == 1


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

    def test_coding_ux_tables_and_problem_ownership_exist(self, test_db):
        """收藏、题单和个人导入题目的迁移存在。"""
        problem_columns = {row["name"] for row in test_db.execute("PRAGMA table_info(coding_problems)")}
        assert {"owner_id", "source_type"}.issubset(problem_columns)
        tables = {
            row["name"]
            for row in test_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'coding_%'"
            )
        }
        assert {"coding_problem_favorites", "coding_playlists", "coding_playlist_items"}.issubset(tables)

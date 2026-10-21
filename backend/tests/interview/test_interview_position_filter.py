"""
自动化测试 — 针对 BUG: 面经/JD 库不按用户岗位过滤
验证 data.py 的 get_data 端点使用 get_user_job_position 而非 get_current_job_position
"""

import pytest
import inspect


class TestInterviewFilteredByPosition:
    """面经/JD 库应按用户岗位过滤"""

    def test_get_data_uses_user_job_position(self, client, test_db):
        from app.core.auth import create_access_token

        position_id = test_db.execute(
            "INSERT INTO job_positions (name) VALUES ('CI 用户岗位')"
        ).lastrowid
        test_db.execute("UPDATE users SET current_position_id = ? WHERE id = 1", (position_id,))
        own_id = test_db.execute(
            "INSERT INTO interview (url, owner_id, job_position, questions_list) "
            "VALUES ('https://example.com/own-position', 1, 'CI 用户岗位', '用户岗位题目')"
        ).lastrowid
        test_db.execute(
            "INSERT INTO interview (url, owner_id, job_position, questions_list) "
            "VALUES ('https://example.com/other-position', 1, '其它岗位', '其它岗位题目')"
        )
        test_db.commit()
        token = create_access_token({"user_id": 1, "type": "access"})
        response = client.get(
            "/api/data/interview?scope=mine",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["items"]] == [own_id]

    def test_data_router_imports_get_user_job_position(self):
        """验证 data.py 导入了 get_user_job_position"""
        import app.routers.data as data_module

        source = inspect.getsource(data_module)
        assert "get_user_job_position" in source

    def test_questions_router_uses_user_job_position(self):
        """验证题库过滤（build_bank_where_clause）也使用 get_user_job_position（对照组）"""
        import app.db.queries as q_module

        source = inspect.getsource(q_module)
        assert "get_user_job_position" in source

    def test_interview_data_has_no_dirty_positions(self, test_db):
        """验证面经表中无 'backend' 等脏数据"""
        rows = test_db.execute(
            "SELECT id, job_position FROM interview WHERE job_position = 'backend'"
        ).fetchall()
        assert len(rows) == 0, f"发现 {len(rows)} 条脏数据: job_position='backend'"

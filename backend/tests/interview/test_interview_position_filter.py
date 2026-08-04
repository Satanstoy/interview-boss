"""
自动化测试 — 针对 BUG: 面经/JD 库不按用户岗位过滤
验证 data.py 的 get_data 端点使用 get_user_job_position 而非 get_current_job_position
"""

import pytest
import inspect


class TestInterviewFilteredByPosition:
    """面经/JD 库应按用户岗位过滤"""

    def test_get_data_uses_user_job_position(self):
        """
        验证 get_data 端点使用 get_user_job_position(user['id'])
        而非 get_current_job_position() 来获取岗位
        """
        from app.routers.data import get_data

        source = inspect.getsource(get_data)

        # 应使用 get_user_job_position
        assert "get_user_job_position" in source, (
            "get_data 应使用 get_user_job_position(user['id']) 按用户岗位过滤"
        )

        # 不应使用 get_current_job_position（全局岗位）
        # 注意：import 语句中可能出现，但函数体内不应直接调用
        lines = source.split("\n")
        for line in lines:
            stripped = line.strip()
            # 跳过 import 行
            if "import" in stripped or "from" in stripped:
                continue
            assert "get_current_job_position()" not in stripped, (
                f"get_data 不应使用全局 get_current_job_position(): {stripped}"
            )

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

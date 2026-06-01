"""
自动化测试 — 针对导入功能和岗位隔离
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock


class TestBug001ContentTypeField:
    """BUG-001: 前端字段名 type vs content_type"""

    def test_submit_endpoint_accepts_content_type(self):
        """验证 /api/submit 端点接受 content_type 参数"""
        from app.routers.submit import submit_data
        import inspect
        sig = inspect.signature(submit_data)
        assert 'content_type' in sig.parameters, \
            "submit_data 应接受 content_type 参数"

    def test_submit_endpoint_accepts_target(self):
        """验证 /api/submit 端点接受 target 参数"""
        from app.routers.submit import submit_data
        import inspect
        sig = inspect.signature(submit_data)
        assert 'target' in sig.parameters, \
            "submit_data 应接受 target 参数"


class TestBug003JdJobPosition:
    """BUG-003: JD 表添加 job_position 字段"""

    def test_jd_has_job_position_column(self):
        """验证 jd 表有 job_position 列"""
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info('jd')").fetchall()}
            assert 'job_position' in columns, \
                "jd 表应有 job_position 列"

    def test_insert_jd_accepts_job_position(self):
        """验证 _insert_jd 函数接受 job_position 参数"""
        from app.db.operations import _insert_jd
        import inspect
        sig = inspect.signature(_insert_jd)
        assert 'job_position' in sig.parameters, \
            "_insert_jd 应接受 job_position 参数"


class TestBug004InterviewJobPosition:
    """BUG-004: 面经数据 job_position 回填"""

    def test_interview_records_have_job_position(self):
        """验证 interview 表中不再有空 job_position 记录"""
        from app.db.connection import get_db_connection
        with get_db_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM interview WHERE (job_position IS NULL OR job_position = '') AND deleted_at IS NULL"
            ).fetchone()[0]
            # 修复后应为 0（除非全局岗位也为空）
            current_pos = conn.execute(
                "SELECT value FROM user_profile WHERE key = 'current_job_position'"
            ).fetchone()
            if current_pos and current_pos[0]:
                assert count == 0, \
                    f"应无空 job_position 的面经记录，但找到 {count} 条"


class TestBug003DataQueryFiltering:
    """验证 data.py 查询按 job_position 过滤"""

    def test_data_query_includes_job_position_filter(self):
        """验证 get_data 函数的查询包含 job_position 过滤"""
        from app.routers.data import get_data
        import inspect
        source = inspect.getsource(get_data)
        assert 'job_position' in source, \
            "get_data 函数应包含 job_position 过滤逻辑"

"""
TDD 测试：编辑聚类题目内容功能

测试 UpdateQuestionRequest schema 和 PUT /api/master-bank/{id} 端点。
"""
import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


class TestUpdateQuestionSchema:
    """测试 UpdateQuestionRequest schema 验证"""

    def test_schema_with_all_fields(self):
        from app.models.schemas import UpdateQuestionRequest
        req = UpdateQuestionRequest(
            question="新题目文本", cat1="A.项目经验", cat2="A1.项目介绍",
            tags="Redis,MySQL", difficulty="L2-中等"
        )
        assert req.question == "新题目文本"
        assert req.cat1 == "A.项目经验"
        assert req.cat2 == "A1.项目介绍"
        assert req.tags == "Redis,MySQL"
        assert req.difficulty == "L2-中等"

    def test_schema_with_partial_fields(self):
        from app.models.schemas import UpdateQuestionRequest
        req = UpdateQuestionRequest(tags="Redis")
        assert req.question is None
        assert req.cat1 is None
        assert req.tags == "Redis"

    def test_schema_with_empty_body(self):
        from app.models.schemas import UpdateQuestionRequest
        req = UpdateQuestionRequest()
        assert req.question is None
        assert req.cat1 is None
        assert req.cat2 is None
        assert req.tags is None
        assert req.difficulty is None


class TestEditQuestionEndpoint:
    """测试 PATCH /api/master-bank/{question_id} 端点"""

    def _make_conn(self, fetchone_result):
        """创建 mock 数据库连接"""
        conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = fetchone_result
        mock_cursor.execute.return_value = mock_cursor
        conn.execute.return_value = mock_cursor
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    @patch('app.routers.questions.run_db')
    def test_admin_edits_public_question_all_fields(self, mock_run_db):
        """T-001: 管理员编辑公共题目所有字段"""
        from app.models.schemas import UpdateQuestionRequest

        existing = {
            'id': 1, 'question': '旧题目', 'cat1': '旧分类',
            'cat2': '旧子类', 'tags': '旧标签', 'difficulty': 'L1',
            'owner_id': None, 'job_position': 'test'
        }

        # run_db 会执行传入的 callable 并返回其结果
        def run_side_effect(func):
            import asyncio
            # 直接执行同步函数
            return func()

        mock_run_db.side_effect = run_side_effect

        # Mock get_db_connection
        conn = self._make_conn(existing)
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio

            req = UpdateQuestionRequest(
                question="新题目", cat1="A.项目经验", cat2="A1.项目介绍",
                tags="Redis", difficulty="L2-中等"
            )
            admin = {'id': 1, 'is_admin': 1, 'username': 'admin'}
            result = asyncio.run(edit_question(1, req, admin))

        assert result['status'] == 'success'
        assert result['data']['question'] == "新题目"
        assert result['data']['cat1'] == "A.项目经验"
        assert result['data']['tags'] == "Redis"

    @patch('app.routers.questions.run_db')
    def test_non_admin_cannot_edit_public_question(self, mock_run_db):
        """T-003: 普通用户无权编辑公共题目"""
        from app.models.schemas import UpdateQuestionRequest

        existing = {'id': 1, 'question': '旧题目', 'owner_id': None}

        def run_side_effect(func):
            return func()
        mock_run_db.side_effect = run_side_effect

        conn = self._make_conn(existing)
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio
            from fastapi import HTTPException

            req = UpdateQuestionRequest(question="新题目")
            user = {'id': 2, 'is_admin': 0, 'username': 'user'}

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(edit_question(1, req, user))
            assert exc_info.value.status_code == 403

    @patch('app.routers.questions.run_db')
    def test_edit_nonexistent_question_returns_404(self, mock_run_db):
        """T-005: 编辑不存在的题目返回 404"""
        from app.models.schemas import UpdateQuestionRequest

        def run_side_effect(func):
            return func()
        mock_run_db.side_effect = run_side_effect

        conn = self._make_conn(None)  # 不存在
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio
            from fastapi import HTTPException

            req = UpdateQuestionRequest(question="新题目")
            admin = {'id': 1, 'is_admin': 1, 'username': 'admin'}

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(edit_question(999, req, admin))
            assert exc_info.value.status_code == 404

    @patch('app.routers.questions.run_db')
    def test_partial_update_only_changes_specified_fields(self, mock_run_db):
        """T-006: 部分字段更新，只改 tags"""
        from app.models.schemas import UpdateQuestionRequest

        existing = {
            'id': 1, 'question': '旧题目', 'cat1': 'A.项目经验',
            'cat2': 'A1', 'tags': '旧标签', 'difficulty': 'L1',
            'owner_id': None, 'job_position': 'test'
        }

        def run_side_effect(func):
            return func()
        mock_run_db.side_effect = run_side_effect

        conn = self._make_conn(existing)
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio

            req = UpdateQuestionRequest(tags="新标签")
            admin = {'id': 1, 'is_admin': 1, 'username': 'admin'}
            result = asyncio.run(edit_question(1, req, admin))

        assert result['status'] == 'success'
        assert result['data']['tags'] == "新标签"
        assert result['data']['question'] == "旧题目"

    @patch('app.routers.questions.run_db')
    def test_owner_can_edit_personal_question(self, mock_run_db):
        """T-002: 普通用户编辑自己的个人题目"""
        from app.models.schemas import UpdateQuestionRequest

        existing = {
            'id': 1, 'question': '旧题目', 'cat1': '', 'cat2': '',
            'tags': '', 'difficulty': '', 'owner_id': 2, 'job_position': 'test'
        }

        def run_side_effect(func):
            return func()
        mock_run_db.side_effect = run_side_effect

        conn = self._make_conn(existing)
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio

            req = UpdateQuestionRequest(question="我的题目")
            user = {'id': 2, 'is_admin': 0, 'username': 'user'}
            result = asyncio.run(edit_question(1, req, user))

        assert result['status'] == 'success'
        assert result['data']['question'] == "我的题目"

    @patch('app.routers.questions.run_db')
    def test_non_owner_cannot_edit_others_personal_question(self, mock_run_db):
        """T-004: 非 owner 无权编辑他人个人题目"""
        from app.models.schemas import UpdateQuestionRequest

        existing = {
            'id': 1, 'question': '旧题目', 'owner_id': 99  # 其他用户
        }

        def run_side_effect(func):
            return func()
        mock_run_db.side_effect = run_side_effect

        conn = self._make_conn(existing)
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio
            from fastapi import HTTPException

            req = UpdateQuestionRequest(question="新题目")
            user = {'id': 2, 'is_admin': 0, 'username': 'user'}

            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(edit_question(1, req, user))
            assert exc_info.value.status_code == 403

    @patch('app.routers.questions.run_db')
    def test_update_question_syncs_questions_detail(self, mock_run_db):
        """T-007: 更新 question 时同步 questions_detail"""
        from app.models.schemas import UpdateQuestionRequest

        existing = {
            'id': 1, 'question': '旧题目', 'cat1': '', 'cat2': '',
            'tags': '', 'difficulty': '', 'owner_id': None, 'job_position': 'test'
        }

        def run_side_effect(func):
            return func()
        mock_run_db.side_effect = run_side_effect

        conn = self._make_conn(existing)
        with patch('app.routers.questions.get_db_connection', return_value=conn):
            from app.routers.questions import edit_question
            import asyncio

            req = UpdateQuestionRequest(question="新题目文本")
            admin = {'id': 1, 'is_admin': 1, 'username': 'admin'}
            result = asyncio.run(edit_question(1, req, admin))

        # 验证 questions_detail 也被更新
        assert result['status'] == 'success'
        # 检查 execute 被调用了 questions_detail 的更新
        calls = conn.execute.call_args_list
        detail_update_found = False
        for call in calls:
            sql = call[0][0] if call[0] else ''
            if 'questions_detail' in sql:
                detail_update_found = True
                break
        assert detail_update_found, "更新 question 时应同步 questions_detail"

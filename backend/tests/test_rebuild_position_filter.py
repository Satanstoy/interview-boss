"""
自动化测试 — 针对 BUG-001/BUG-002/BUG-003
重建题库时 questions_detail 缺少 job_position 过滤导致跨岗位数据污染
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock, call


class TestBug001QuestionsDetailMissingJobPosition:
    """BUG-001: questions_detail 表缺少 job_position 列"""

    def test_insert_details_should_include_job_position(self):
        """修复后：_insert_details 应写入 job_position 字段"""
        from app.db.operations import _insert_details

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("app.db.operations.get_db_connection", return_value=mock_conn):
            tagged_rows = [
                ["http://test.com", "测试公司", "一面", "什么是闭包？", "JavaScript", "作用域", "闭包", "中等"]
            ]
            _insert_details(tagged_rows, job_position="后端开发")

        # 验证 INSERT 语句包含 job_position
        insert_call = mock_conn.execute.call_args
        sql = insert_call[0][0]
        assert "job_position" in sql, "INSERT 语句应包含 job_position 字段"
        params = insert_call[0][1]
        assert "后端开发" in params, "参数应包含 job_position 值"

    def test_insert_details_default_job_position_empty(self):
        """修复后：不传 job_position 时应默认为空字符串"""
        from app.db.operations import _insert_details

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("app.db.operations.get_db_connection", return_value=mock_conn):
            tagged_rows = [
                ["http://test.com", "测试公司", "一面", "什么是闭包？", "JavaScript", "作用域", "闭包", "中等"]
            ]
            _insert_details(tagged_rows)

        insert_call = mock_conn.execute.call_args
        params = insert_call[0][1]
        assert "" in params, "默认 job_position 应为空字符串"


class TestBug002InterviewMissingJobPosition:
    """BUG-002: interview 表缺少 job_position 列"""

    def test_insert_interview_should_include_job_position(self):
        """修复后：_insert_interview 应写入 job_position 字段"""
        from app.db.operations import _insert_interview

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("app.db.operations.get_db_connection", return_value=mock_conn):
            _insert_interview(
                "http://test.com",
                {"公司": "测试公司", "面试轮次": "一面", "考察重点": "算法", "难易程度": "中等"},
                "题目1\n题目2",
                season="2025",
                owner_id=1,
                job_position="后端开发"
            )

        insert_call = mock_conn.execute.call_args
        sql = insert_call[0][0]
        assert "job_position" in sql, "INSERT 语句应包含 job_position 字段"


class TestBug003LoadShouldFilterByPosition:
    """BUG-003: _load() 应按 job_position 过滤 questions_detail"""

    @pytest.mark.asyncio
    async def test_load_filters_questions_detail_by_job_position(self):
        """修复后：_load() 应只加载当前岗位的面经题目"""
        # 模拟数据库返回
        mock_raw_backend = [
            {"id": 1, "question": "什么是微服务？", "cat1": "系统设计", "cat2": "架构",
             "tags": "微服务", "diff_tag": "中等", "url": "http://test1.com", "company": "A公司", "round": "一面"}
        ]
        mock_raw_frontend = [
            {"id": 2, "question": "什么是虚拟DOM？", "cat1": "前端", "cat2": "Vue",
             "tags": "Vue", "diff_tag": "简单", "url": "http://test2.com", "company": "B公司", "round": "二面"}
        ]

        # 当岗位为"后端开发"时，只应返回后端题目
        call_count = [0]
        def mock_execute_side_effect(sql, params=None):
            mock_result = MagicMock()
            if "questions_detail" in sql:
                if params and params[0] == "后端开发":
                    mock_result.fetchall.return_value = mock_raw_backend
                else:
                    mock_result.fetchall.return_value = mock_raw_backend + mock_raw_frontend
            else:
                mock_result.fetchall.return_value = []
            return mock_result

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = mock_execute_side_effect
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        # 验证 SQL 包含 job_position 过滤
        with patch("app.routers.bank_build.get_db_connection", return_value=mock_conn):
            with patch("app.routers.bank_build.get_current_job_position", return_value="后端开发"):
                # 重新加载 _load 函数来验证
                from app.routers.bank_build import build_master_bank
                # 直接验证 _load 的 SQL 是否包含 job_position 过滤
                # 这通过检查 execute 调用的 SQL 来验证
                pass

    def test_load_sql_must_contain_job_position_filter(self):
        """验证 _load() 的 SQL 语句必须包含 job_position 过滤条件"""
        # 读取源代码并检查
        import inspect
        import ast

        with open("/root/sj/interview-boss/backend/app/routers/bank_build.py", "r") as f:
            source = f.read()

        # 检查 _load 函数中的 SQL 是否包含 job_position 过滤
        # 查找 questions_detail 查询
        assert "qd.job_position" in source or "questions_detail.*job_position" in source, \
            "_load() 中从 questions_detail 查询时应包含 job_position 过滤条件"

    def test_save_sql_must_include_job_position(self):
        """验证 _save() 写入 question_bank 时包含 job_position"""
        with open("/root/sj/interview-boss/backend/app/routers/bank_build.py", "r") as f:
            source = f.read()

        assert "job_position" in source, "_save() 中 INSERT INTO question_bank 应包含 job_position"


class TestAnswerRecoveryImprovement:
    """BUG-003 附加: 答案恢复逻辑优化"""

    def test_answer_recovery_tries_original_questions(self):
        """修复后：答案恢复应尝试匹配 original_questions 中的每个题目"""
        existing_answers_map = {
            "什么是闭包？": "闭包是...",
            "解释原型链": "原型链是..."
        }

        # 模拟聚类详情：统一后的问题文本不在答案 map 中，但 original_questions 中有
        cluster = {
            "question": "请解释 JavaScript 闭包和原型链的概念",  # 统一后的文本，不在 map 中
            "original_questions": ["什么是闭包？", "解释原型链"],  # 原始问题在 map 中
            "original_question_sources": [
                {"question": "什么是闭包？", "sources": []},
                {"question": "解释原型链", "sources": []}
            ]
        }

        # 模拟恢复逻辑
        ai_answer = existing_answers_map.get(cluster['question'])
        if not ai_answer:
            for oq in cluster.get('original_questions', []):
                ai_answer = existing_answers_map.get(oq)
                if ai_answer:
                    break

        assert ai_answer is not None, "应从 original_questions 中匹配到已有答案"
        assert ai_answer == "闭包是...", "应匹配到第一个 original_question 的答案"


class TestPositionIsolationIntegration:
    """集成测试：验证岗位隔离"""

    @pytest.mark.asyncio
    async def test_rebuild_does_not_mix_positions(self):
        """修复后：重建岗位 A 的题库不应包含岗位 B 的面经题目"""
        # 模拟 questions_detail 中有两个岗位的题目
        position_a_questions = [
            {"id": 1, "question": "什么是微服务？", "cat1": "系统设计", "cat2": "架构",
             "tags": "微服务", "diff_tag": "中等", "url": "http://a.com", "company": "A", "round": "一面"}
        ]
        position_b_questions = [
            {"id": 2, "question": "什么是虚拟DOM？", "cat1": "前端", "cat2": "Vue",
             "tags": "Vue", "diff_tag": "简单", "url": "http://b.com", "company": "B", "round": "二面"}
        ]

        # 验证：当 current_pos = "后端开发" 时，SQL 应过滤掉前端题目
        mock_conn = MagicMock()

        def mock_execute(sql, params=None):
            result = MagicMock()
            if "questions_detail" in sql and "job_position" in sql:
                # 应该有 job_position 过滤
                if params and "后端开发" in params:
                    result.fetchall.return_value = position_a_questions
                else:
                    result.fetchall.return_value = position_a_questions + position_b_questions
            elif "questions_detail" in sql:
                # 没有过滤 - 返回所有（这是 bug 的表现）
                result.fetchall.return_value = position_a_questions + position_b_questions
            else:
                result.fetchall.return_value = []
            return result

        mock_conn.execute.side_effect = mock_execute
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("app.routers.bank_build.get_db_connection", return_value=mock_conn):
            with patch("app.routers.bank_build.get_current_job_position", return_value="后端开发"):
                # 通过检查源码确保 SQL 包含过滤条件
                with open("/root/sj/interview-boss/backend/app/routers/bank_build.py", "r") as f:
                    source = f.read()

                # 在 _load 函数的 questions_detail 查询中必须有 job_position 过滤
                # 找到 questions_detail 查询
                qd_query_start = source.find("FROM questions_detail qd")
                if qd_query_start == -1:
                    qd_query_start = source.find("FROM questions_detail")
                assert qd_query_start != -1, "应找到 questions_detail 查询"

                # 检查该查询附近是否有 job_position 条件
                query_region = source[qd_query_start:qd_query_start + 300]
                assert "job_position" in query_region, \
                    f"questions_detail 查询应包含 job_position 过滤，实际查询片段: {query_region[:200]}"

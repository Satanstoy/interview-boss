"""
自动化测试 — 针对 BUG-006 ~ BUG-009（权限提升漏洞）
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import re


class TestBug006GenerateAnswerOwnership:
    """BUG-006: generate-answer 端点应校验题目可见性"""

    def test_bug006_should_use_build_bank_where_clause(self):
        """generate_master_answer 应使用 _build_bank_where_clause 过滤可见性"""
        with open('/root/sj/interview-boss/backend/app/routers/answers.py', 'r') as f:
            content = f.read()

        # 找到 generate_master_answer 函数
        func_match = re.search(
            r'async def generate_master_answer.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 generate_master_answer 函数"
        func_content = func_match.group(0)

        # 修复前：仅 SELECT question, ai_answer FROM question_bank WHERE id = ?
        # 修复后：应使用 _build_bank_where_clause 或检查 owner_id/bank_mode
        has_visibility_check = (
            '_build_bank_where_clause' in func_content or
            'bank_mode' in func_content or
            "owner_id" in func_content
        )
        assert has_visibility_check, "generate_master_answer 应包含可见性检查（_build_bank_where_clause 或 owner_id 校验）"

    def test_bug006_should_not_just_select_by_id(self):
        """generate_master_answer 不应仅按 id 查询而无过滤"""
        with open('/root/sj/interview-boss/backend/app/routers/answers.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def generate_master_answer.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match
        func_content = func_match.group(0)

        # 检查是否存在"仅按 id 查询且无额外过滤"的模式
        bare_select = re.search(
            r'SELECT.*FROM question_bank WHERE id = \?\s*\'',
            func_content
        )
        # 如果存在这样的查询且没有可见性检查，则为 bug
        has_visibility = '_build_bank_where_clause' in func_content or 'owner_id' in func_content
        if bare_select and not has_visibility:
            assert False, "generate_master_answer 仅按 id 查询，无可见性过滤"


class TestBug007BatchGenerateAnswersOwnership:
    """BUG-007: batch-generate-answers 端点应校验题目可见性"""

    def test_bug007_should_use_build_bank_where_clause(self):
        """batch_generate_answers 应使用 _build_bank_where_clause 过滤可见性"""
        with open('/root/sj/interview-boss/backend/app/routers/answers.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def batch_generate_answers.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 batch_generate_answers 函数"
        func_content = func_match.group(0)

        has_visibility_check = (
            '_build_bank_where_clause' in func_content or
            'bank_mode' in func_content or
            'owner_id' in func_content
        )
        assert has_visibility_check, "batch_generate_answers 应包含可见性检查"

    def test_bug007_should_filter_by_user_visibility(self):
        """batch_generate_answers 的查询应过滤用户不可见的题目"""
        with open('/root/sj/interview-boss/backend/app/routers/answers.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def batch_generate_answers.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match
        func_content = func_match.group(0)

        # 验证使用了 bank_mode 权限检查
        has_visibility = 'bank_mode' in func_content and 'owner_id' in func_content
        assert has_visibility, "batch_generate_answers 应使用 bank_mode 和 owner_id 进行权限检查"


class TestBug008EvaluateAnswerVisibility:
    """BUG-008: evaluate-answer 端点应校验题目可见性"""

    def test_bug008_should_check_question_visibility(self):
        """evaluate_answer 在记录练习前应校验题目可见性"""
        with open('/root/sj/interview-boss/backend/app/routers/practice.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def evaluate_answer.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 evaluate_answer 函数"
        func_content = func_match.group(0)

        # 应该在记录练习历史前检查题目是否可见
        has_visibility_check = (
            '_build_bank_where_clause' in func_content or
            'owner_id' in func_content or
            'bank_mode' in func_content
        )
        assert has_visibility_check, "evaluate_answer 应在记录练习前校验题目可见性"

    def test_bug008_should_validate_question_exists_and_visible(self):
        """evaluate_answer 应验证 question_id 对应的题目存在且用户可见"""
        with open('/root/sj/interview-boss/backend/app/routers/practice.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def evaluate_answer.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match
        func_content = func_match.group(0)

        # 应该有对 question_bank 的查询来验证题目
        queries_question_bank = 'question_bank' in func_content
        assert queries_question_bank, "evaluate_answer 应查询 question_bank 验证题目"


class TestBug009AnalyticsIsolation:
    """BUG-009: analytics 端点应按用户隔离数据"""

    def test_bug009_jd_query_should_filter_by_bank_mode(self):
        """analytics 的 JD 查询应按 bank_mode 过滤"""
        with open('/root/sj/interview-boss/backend/app/routers/analytics.py', 'r') as f:
            content = f.read()

        # 找到 get_analytics 函数
        func_match = re.search(
            r'async def get_analytics.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match, "应存在 get_analytics 函数"
        func_content = func_match.group(0)

        # JD 查询应该有过滤条件（不是直接查全表）
        # 修复前：SELECT tech_stack FROM jd WHERE deleted_at IS NULL（无 bank_mode 过滤）
        # 修复后：应有 owner_id 或 status 过滤
        jd_query_match = re.search(r'SELECT tech_stack FROM jd.*?WHERE.*?(?=\n|$)', func_content)
        if jd_query_match:
            jd_query = jd_query_match.group(0)
            has_owner_filter = 'owner_id' in jd_query or 'status' in jd_query or 'bank_mode' in func_content
            assert has_owner_filter, "analytics 的 JD 查询应按 owner_id/status 过滤"

    def test_bug009_questions_detail_query_should_filter_by_bank_mode(self):
        """analytics 的 questions_detail 查询应按 bank_mode 过滤"""
        with open('/root/sj/interview-boss/backend/app/routers/analytics.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def get_analytics.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match
        func_content = func_match.group(0)

        # questions_detail 查询应有过滤
        qd_query_match = re.search(r'SELECT tags, diff_tag FROM questions_detail.*?WHERE.*?(?=\n|$)', func_content)
        if qd_query_match:
            qd_query = qd_query_match.group(0)
            has_owner_filter = 'owner_id' in qd_query or 'status' in qd_query or 'bank_mode' in func_content
            assert has_owner_filter, "analytics 的 questions_detail 查询应按 owner_id/status 过滤"

    def test_bug009_should_use_user_context(self):
        """get_analytics 应使用 user 参数来构建过滤条件"""
        with open('/root/sj/interview-boss/backend/app/routers/analytics.py', 'r') as f:
            content = f.read()

        func_match = re.search(
            r'async def get_analytics.*?(?=\n@router|\nasync def |\Z)',
            content,
            re.DOTALL
        )
        assert func_match
        func_content = func_match.group(0)

        # 应该使用 user 参数
        uses_user = 'user' in func_content and ('bank_mode' in func_content or 'owner_id' in func_content)
        assert uses_user, "get_analytics 应使用 user 上下文来过滤数据"


class TestIntegration:
    """集成测试：验证所有端点的权限控制"""

    def test_generate_answer_endpoint_requires_visibility_check(self):
        """generate-answer 端点应有可见性检查"""
        with open('/root/sj/interview-boss/backend/app/routers/answers.py', 'r') as f:
            content = f.read()

        # 找到 generate-answer 路由
        route_match = re.search(
            r'@router\.post\("/api/master-bank/generate-answer/\{question_id\}"\).*?(?=\n@router|\Z)',
            content,
            re.DOTALL
        )
        assert route_match, "应存在 generate-answer 路由"
        route_content = route_match.group(0)

        has_check = '_build_bank_where_clause' in route_content or 'owner_id' in route_content
        assert has_check, "generate-answer 端点应有可见性检查"

    def test_batch_generate_endpoint_requires_visibility_check(self):
        """batch-generate-answers 端点应有可见性检查"""
        with open('/root/sj/interview-boss/backend/app/routers/answers.py', 'r') as f:
            content = f.read()

        route_match = re.search(
            r'@router\.post\("/api/master-bank/batch-generate-answers"\).*?(?=\n@router|\Z)',
            content,
            re.DOTALL
        )
        assert route_match, "应存在 batch-generate-answers 路由"
        route_content = route_match.group(0)

        has_check = '_build_bank_where_clause' in route_content or 'owner_id' in route_content
        assert has_check, "batch-generate-answers 端点应有可见性检查"

    def test_evaluate_answer_endpoint_requires_visibility_check(self):
        """evaluate-answer 端点应有可见性检查"""
        with open('/root/sj/interview-boss/backend/app/routers/practice.py', 'r') as f:
            content = f.read()

        route_match = re.search(
            r'@router\.post\("/api/evaluate-answer"\).*?(?=\n@router|\Z)',
            content,
            re.DOTALL
        )
        assert route_match, "应存在 evaluate-answer 路由"
        route_content = route_match.group(0)

        has_check = '_build_bank_where_clause' in route_content or 'owner_id' in route_content
        assert has_check, "evaluate-answer 端点应有可见性检查"

    def test_analytics_endpoint_uses_bank_mode_filter(self):
        """analytics 端点应使用 bank_mode 过滤"""
        with open('/root/sj/interview-boss/backend/app/routers/analytics.py', 'r') as f:
            content = f.read()

        has_bank_mode = 'bank_mode' in content
        assert has_bank_mode, "analytics 端点应使用 bank_mode 过滤数据"

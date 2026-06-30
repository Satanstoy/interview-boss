"""
自动化测试 — 针对前后端联动 BUG-001 ~ BUG-003
使用 pytest + unittest.mock，验证 API 端点和前端调用的一致性
"""
import pytest
import json
import os
import re
from unittest.mock import patch, MagicMock


# ── BUG-001: loadActiveSeason 调用管理员专属端点 ──

class TestBUG001LoadActiveSeason:
    """BUG-001: loadActiveSeason 使用了管理员专属的 GET /api/profile"""

    def test_load_active_season_uses_public_endpoint(self):
        """loadActiveSeason 应调用 fetchPublicProfile 而非 fetchProfile"""
        data_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/composables/useMasterBankData.js')
        with open(data_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 loadActiveSeason 函数
        match = re.search(r'const loadActiveSeason\s*=\s*async\s*\(\)\s*=>\s*\{', content)
        assert match is not None, "未找到 loadActiveSeason 函数"

        # 提取函数体（到下一个顶层 const 或函数结束）
        start = match.end()
        brace_count = 1
        pos = start
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        func_body = content[start:pos]

        # 修复后：应使用 fetchPublicProfile
        assert 'fetchPublicProfile' in func_body, \
            f"loadActiveSeason 应使用 fetchPublicProfile，当前代码: {func_body[:200]}"

    def test_public_profile_endpoint_exists(self):
        """后端应有 GET /api/profile/public 端点"""
        from app.routers.profile import get_public_profile
        assert callable(get_public_profile)

    def test_public_profile_returns_active_season(self):
        """GET /api/profile/public 应返回 active_season 字段"""
        from app.routers.profile import get_public_profile
        import inspect
        source = inspect.getsource(get_public_profile)
        assert 'active_season' in source, "get_public_profile 应返回 active_season"


# ── BUG-002: buildMasterBank 使用 post() 请求 SSE 端点 ──

class TestBUG002BuildMasterBank:
    """BUG-002: triggerBuildMasterBank 使用 post() 而非 postSSE()"""

    def test_trigger_build_uses_sse(self):
        """triggerBuildMasterBank 应提交 build 任务并监听 job SSE"""
        build_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/composables/useBuildTrigger.js')
        with open(build_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 triggerBuildMasterBank 函数
        match = re.search(r'const triggerBuildMasterBank\s*=\s*async\s*\(\)\s*=>\s*\{', content)
        assert match is not None, "未找到 triggerBuildMasterBank 函数"

        # 提取函数体
        start = match.end()
        brace_count = 1
        pos = start
        while pos < len(content) and brace_count > 0:
            if content[pos] == '{':
                brace_count += 1
            elif content[pos] == '}':
                brace_count -= 1
            pos += 1
        func_body = content[start:pos]

        assert 'api.buildMasterBank()' in func_body, "triggerBuildMasterBank 应先提交 build 任务"
        assert 'api.streamJobProgress' in func_body, "triggerBuildMasterBank 应监听 job SSE 进度"

    def test_build_endpoint_returns_sse(self):
        """后端 POST /api/master-bank/build 应返回 job_id，并通过 /api/jobs/{id}/stream 监听进度"""
        from app.routers.bank_build import build_master_bank
        import inspect
        source = inspect.getsource(build_master_bank)
        assert 'job_id' in source and 'status' in source, \
            "build_master_bank 应提交任务并返回 job_id/status"

        from app.routers.bank_build import stream_job_progress
        stream_source = inspect.getsource(stream_job_progress)
        assert 'StreamingResponse' in stream_source or 'event_stream' in stream_source, \
            "stream_job_progress 应返回 StreamingResponse (SSE)"

    def test_api_has_sse_function(self):
        """前端 api/index.js 应有 buildMasterBankSSE 函数"""
        api_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/api/index.js')
        with open(api_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'buildMasterBankSSE' in content, "api/index.js 应导出 buildMasterBankSSE"


# ── BUG-003: 前端缺少 fetchPublicProfile API 函数 ──

class TestBUG003FetchPublicProfile:
    """BUG-003: 前端缺少 fetchPublicProfile API 函数"""

    def test_fetch_public_profile_exists_in_api(self):
        """api/index.js 应导出 fetchPublicProfile 函数"""
        api_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/services/profileApi.js')
        with open(api_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'fetchPublicProfile' in content, "api/index.js 应导出 fetchPublicProfile"

    def test_fetch_public_profile_calls_correct_endpoint(self):
        """fetchPublicProfile 应调用 GET /api/profile/public"""
        api_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/services/profileApi.js')
        with open(api_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 找到 fetchPublicProfile 定义
        match = re.search(r'fetchPublicProfile\s*=\s*(?:\([^)]*\)|\w+)\s*=>\s*(.+)', content)
        assert match is not None, "未找到 fetchPublicProfile 定义"
        definition = match.group(1)
        # 模板字面量 ${API} 展开为 /api，检查 profile/public 路径
        assert 'profile/public' in definition, \
            f"fetchPublicProfile 应调用 /api/profile/public，当前: {definition}"

    def test_public_profile_endpoint_returns_settings(self):
        """GET /api/profile/public 应返回 settings 对象"""
        from app.routers.profile import get_public_profile
        import inspect
        source = inspect.getsource(get_public_profile)
        assert '"settings"' in source or "'settings'" in source, \
            "get_public_profile 应返回 settings 对象"


# ── 综合验证 ──

class TestIntegrationVerification:
    """综合验证前后端 API 一致性"""

    def test_api_index_has_all_required_functions(self):
        """api/index.js 应包含所有必要的 API 函数"""
        api_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/api/index.js')
        with open(api_path, 'r', encoding='utf-8') as f:
            content = f.read()
        required_functions = [
            'fetchProfile',
            'fetchPublicProfile',
            'buildMasterBank',
            'buildMasterBankSSE',
            'fetchPendingQuestions',
            'fetchRandomQuestions',
            'evaluateAnswer',
            'generateAnswer',
            'toggleStar',
            'retagQuestion',
        ]
        for func in required_functions:
            assert func in content, f"api/index.js 缺少 {func} 函数"

    def test_public_profile_endpoint_accessible(self):
        """GET /api/profile/public 应使用 get_current_user（非 get_admin_user）"""
        from app.routers.profile import get_public_profile
        import inspect
        source = inspect.getsource(get_public_profile)
        assert 'get_current_user' in source, "get_public_profile 应使用 get_current_user"
        assert 'get_admin_user' not in source, "get_public_profile 不应使用 get_admin_user"

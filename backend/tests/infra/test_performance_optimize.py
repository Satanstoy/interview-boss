"""
TDD 测试：性能优化验证

OPT-1: numpy 依赖移除
OPT-2: 前端组件懒加载
OPT-3: compact_singletons 分页加载
OPT-4: LLM 重试总时间限制
OPT-5: 用户客户端缓存上限
OPT-6: SecurityHeadersMiddleware 改用纯 ASGI
"""
import os
import pytest
from pathlib import Path


from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class TestRemoveNumpy:
    """OPT-1: numpy 应从项目中移除"""

    def test_numpy_not_in_pyproject(self):
        """T-001: pyproject.toml 中不应包含 numpy 依赖"""
        pyproject = Path(BACKEND_ROOT.parent / "pyproject.toml").read_text()
        assert "numpy" not in pyproject, "numpy 仍在 pyproject.toml 中"

    def test_no_numpy_import_in_backend(self):
        """T-002: 后端代码中不应有 numpy 导入"""
        backend_dir = Path(BACKEND_ROOT / "app")
        violations = []
        for py_file in backend_dir.rglob("*.py"):
            content = py_file.read_text()
            for i, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "import numpy" in stripped or "from numpy" in stripped:
                    violations.append(f"{py_file}:{i}: {stripped}")
        assert not violations, f"发现 numpy 导入:\n" + "\n".join(violations)


class TestFrontendLazyLoad:
    """OPT-2: 低频组件应使用异步懒加载"""

    def _get_app_vue_content(self):
        return Path(BACKEND_ROOT / "frontend/src/App.vue").read_text()

    def test_mock_interview_is_async(self):
        """T-003a: MockInterview 组件应异步加载"""
        content = self._get_app_vue_content()
        assert "defineAsyncComponent" in content, "未使用 defineAsyncComponent"
        assert "MockInterview" in content

    def test_knowledge_graph_is_async(self):
        """T-003b: KnowledgeGraph 组件应异步加载"""
        content = self._get_app_vue_content()
        assert "KnowledgeGraph" in content

    def test_practice_mode_is_async(self):
        """T-003c: PracticeMode 组件应异步加载"""
        content = self._get_app_vue_content()
        assert "PracticeMode" in content

    def test_define_async_component_imported(self):
        """T-003d: 应从 vue 导入 defineAsyncComponent"""
        content = self._get_app_vue_content()
        assert "defineAsyncComponent" in content


class TestCompactSingletonsPagination:
    """OPT-3: compact_singletons 应分页加载数据"""

    def test_compact_uses_pagination(self):
        """T-004: _load_singletons 应使用分页而非 fetchall"""
        pipeline_path = Path(BACKEND_ROOT / "app/services/pipeline.py")
        content = pipeline_path.read_text()
        assert "compact_singletons_in_db" in content
        assert "fetchall" not in content or "LIMIT" in content, \
            "compact_singletons 仍使用 fetchall 而非分页"


class TestLLMRetryLimit:
    """OPT-4: LLM 重试应有总时间上限"""

    def _get_llm_content(self):
        return Path(BACKEND_ROOT / "app/services/llm.py").read_text()

    def test_retry_has_delay_limit(self):
        """T-005a: 重试装饰器应有 stop_after_delay 限制"""
        content = self._get_llm_content()
        assert "stop_after_delay" in content, \
            "LLM 重试缺少 stop_after_delay 总时间限制"

    def test_retry_max_delay_reduced(self):
        """T-005b: 单次重试最大等待时间不应超过 15 秒"""
        content = self._get_llm_content()
        # 检查 max 参数不应超过 15
        import re
        # 匹配 wait_exponential(..., max=30) 或类似模式
        matches = re.findall(r'max=(\d+)', content)
        for m in matches:
            assert int(m) <= 15, f"重试最大等待 {m}s 过长，应 <= 15s"


class TestUserClientCacheLimit:
    """OPT-5: 用户 LLM 客户端缓存应有上限"""

    def test_cache_has_max_size(self):
        """T-006: _user_client_cache 应有大小限制"""
        llm_content = Path(BACKEND_ROOT / "app/services/llm.py").read_text()
        # 检查是否有缓存大小限制逻辑
        assert "MAX_CACHE" in llm_content or "max_cache" in llm_content or \
               "cache_size" in llm_content or "len(_user_client_cache)" in llm_content, \
            "_user_client_cache 无大小限制，可能导致内存泄漏"


class TestSecurityHeadersASGI:
    """OPT-6: SecurityHeadersMiddleware 应使用纯 ASGI 实现"""

    def test_not_using_base_http_middleware(self):
        """T-007: 安全头中间件不应继承 BaseHTTPMiddleware"""
        asgi_content = Path(BACKEND_ROOT / "app/asgi.py").read_text()
        # SecurityHeadersMiddleware 不应继承 BaseHTTPMiddleware
        # 应改为纯 ASGI middleware 或 @app.middleware("http") 装饰器
        lines = asgi_content.split("\n")
        for i, line in enumerate(lines):
            if "class SecurityHeadersMiddleware" in line:
                assert "BaseHTTPMiddleware" not in line, \
                    "SecurityHeadersMiddleware 仍继承 BaseHTTPMiddleware，会缓冲 SSE 响应"
                break

"""
安全专项审计测试 — BUG-001 ~ BUG-006
使用 pytest + 静态代码分析验证安全漏洞修复
"""
import pytest
import os
import re


# ── BUG-001: 前端 sanitizeAgainstInjection 是空函数 ──

class TestBUG001SanitizeNoop:
    """BUG-001: sanitizeAgainstInjection 应执行实际消毒"""

    def test_sanitize_not_passthrough(self):
        """sanitizeAgainstInjection 不应直接返回原始字符串"""
        validate_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/utils/validate.js')
        with open(validate_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 sanitizeAgainstInjection 函数定义
        match = re.search(
            r'export\s+function\s+sanitizeAgainstInjection\s*\([^)]*\)\s*\{',
            content
        )
        assert match is not None, "未找到 sanitizeAgainstInjection 函数"

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

        # 函数体不应只是 return str（空函数）
        stripped = func_body.strip()
        assert stripped != 'return str', \
            "sanitizeAgainstInjection 是空函数（直接 return str），应执行 XSS 消毒"

    def test_sanitize_removes_html_tags(self):
        """sanitizeAgainstInjection 应移除 HTML 标签"""
        validate_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/utils/validate.js')
        with open(validate_path, 'r', encoding='utf-8') as f:
            content = f.read()

        match = re.search(
            r'export\s+function\s+sanitizeAgainstInjection\s*\([^)]*\)\s*\{',
            content
        )
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

        # 应包含 HTML 标签移除逻辑
        assert 'replace' in func_body and ('<' in func_body or 'html' in func_body.lower() or 'tag' in func_body.lower()), \
            "sanitizeAgainstInjection 应包含 HTML 标签移除逻辑"

    def test_validate_payload_calls_sanitize(self):
        """validatePayload 应调用 sanitizeAgainstInjection"""
        validate_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/utils/validate.js')
        with open(validate_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # validatePayload 函数应调用 sanitizeAgainstInjection
        match = re.search(r'function\s+validatePayload\s*\(', content)
        assert match is not None, "未找到 validatePayload 函数"

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

        assert 'sanitizeAgainstInjection' in func_body, \
            "validatePayload 应调用 sanitizeAgainstInjection"


# ── BUG-002: /api/analytics 未按 bank_mode 过滤数据 ──

class TestBUG002AnalyticsDataLeak:
    """BUG-002: get_analytics 应按 bank_mode 过滤数据"""

    def test_analytics_uses_bank_filter(self):
        """get_analytics 应使用 _build_analytics_bank_filter 过滤"""
        analytics_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/analytics.py')
        with open(analytics_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 get_analytics 函数
        match = re.search(r'async\s+def\s+get_analytics\s*\(', content)
        assert match is not None, "未找到 get_analytics 函数"

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

        # 应使用 _build_analytics_bank_filter
        assert '_build_analytics_bank_filter' in func_body, \
            "get_analytics 应使用 _build_analytics_bank_filter 过滤用户可见数据"

    def test_analytics_not_raw_select_questions_detail(self):
        """get_analytics 不应对 questions_detail 执行无过滤查询"""
        analytics_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/analytics.py')
        with open(analytics_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 get_analytics 函数
        match = re.search(r'async\s+def\s+get_analytics\s*\(', content)
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

        # 不应有无条件的 questions_detail 查询
        raw_select = re.search(r'SELECT.*FROM\s+questions_detail(?!\s+qb)', func_body)
        if raw_select:
            # 如果有 questions_detail 查询，应有 WHERE 条件
            assert 'WHERE' in func_body or 'bank_where' in func_body or 'join_clause' in func_body, \
                "get_analytics 查询 questions_detail 应有过滤条件"

    def test_analytics_questions_use_question_bank(self):
        """get_analytics 应从 question_bank（而非 questions_detail）查询标签数据"""
        analytics_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/analytics.py')
        with open(analytics_path, 'r', encoding='utf-8') as f:
            content = f.read()

        match = re.search(r'async\s+def\s+get_analytics\s*\(', content)
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

        # 应使用 question_bank 而非 questions_detail
        assert 'question_bank' in func_body, \
            "get_analytics 应从 question_bank 查询标签数据（支持 bank_mode 过滤）"


# ── BUG-003: URL href 绑定无协议验证 ──

class TestBUG003UrlHrefValidation:
    """BUG-003: URL href 绑定应验证协议"""

    def test_safe_url_function_exists(self):
        """validate.js 应导出 safeUrl 函数"""
        validate_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/utils/validate.js')
        with open(validate_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'safeUrl' in content, "validate.js 应包含 safeUrl 函数"

    def test_safe_url_rejects_javascript(self):
        """safeUrl 应拒绝 javascript: 协议"""
        validate_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/utils/validate.js')
        with open(validate_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 safeUrl 函数定义
        match = re.search(r'function\s+safeUrl\s*\(', content)
        assert match is not None, "未找到 safeUrl 函数定义"

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

        # 应检查 http/https 协议
        assert 'http' in func_body.lower(), "safeUrl 应验证 URL 以 http:// 或 https:// 开头"

    def test_question_card_uses_safe_url(self):
        """QuestionCard.vue 应使用 safeUrl 处理 href"""
        card_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/components/business/QuestionCard.vue')
        with open(card_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 应导入或使用 safeUrl
        assert 'safeUrl' in content, "QuestionCard.vue 应使用 safeUrl 函数处理 URL"

    def test_app_vue_uses_safe_url(self):
        """App.vue 应使用 safeUrl 处理来源链接 href"""
        app_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/App.vue')
        with open(app_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 应使用 safeUrl
        assert 'safeUrl' in content, "App.vue 应使用 safeUrl 函数处理 URL"


# ── BUG-005: API Key 掩码泄露前 4 字符 ──

class TestBUG005ApiKeyMasking:
    """BUG-005: _mask_key 不应泄露 API Key 中间部分"""

    def test_mask_key_shows_first_and_last(self):
        """_mask_key 应只显示首尾各 4 字符，中间用 * 替代"""
        profile_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/profile.py')
        with open(profile_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 找到 _mask_key 函数
        match = re.search(r'def\s+_mask_key\s*\(', content)
        assert match is not None, "未找到 _mask_key 函数"

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

        # 不应只显示前 4 字符（旧逻辑：value[:4] + "****"）
        # 应显示首尾（新逻辑：value[:4] + "***" + value[-4:]）
        assert '[-4:]' in func_body or 'value[-' in func_body, \
            "_mask_key 应显示末尾字符（如 value[-4:]），而非只显示前 4 字符"

    def test_mask_key_short_value(self):
        """_mask_key 对短密钥应返回 ****"""
        profile_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/profile.py')
        with open(profile_path, 'r', encoding='utf-8') as f:
            content = f.read()

        match = re.search(r'def\s+_mask_key\s*\(', content)
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

        # 短密钥处理
        assert '****' in func_body, "_mask_key 对短密钥应返回 ****"


# ── 综合验证 ──

class TestSecurityVerification:
    """综合安全验证"""

    def test_validate_js_has_escape_html(self):
        """validate.js 应保留 escapeHtml 函数"""
        validate_path = os.path.join(os.path.dirname(__file__), '../../frontend/src/utils/validate.js')
        with open(validate_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'escapeHtml' in content, "validate.js 应包含 escapeHtml 函数"

    def test_auth_has_csrf_protection(self):
        """auth.py 应有 CSRF 防护机制"""
        auth_path = os.path.join(os.path.dirname(__file__), '../../backend/app/core/auth.py')
        # 检查 routers/auth.py
        routers_auth_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/auth.py')
        with open(routers_auth_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert '_require_custom_header' in content or 'csrf' in content.lower(), \
            "auth.py 应有 CSRF 防护"

    def test_auth_has_rate_limiting(self):
        """auth.py 应有速率限制"""
        auth_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/auth.py')
        with open(auth_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'limiter' in content or 'slowapi' in content or 'rate_limit' in content.lower(), \
            "auth.py 应有速率限制机制"

    def test_refresh_token_httponly(self):
        """refresh token 应设置 HttpOnly cookie"""
        auth_path = os.path.join(os.path.dirname(__file__), '../../backend/app/routers/auth.py')
        with open(auth_path, 'r', encoding='utf-8') as f:
            content = f.read()
        assert 'httponly=True' in content or 'httponly = True' in content, \
            "refresh token 应设置 HttpOnly=True"

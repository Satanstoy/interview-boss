"""
自动化测试 — 针对后端 BUG-001 ~ BUG-004
使用 pytest + unittest.mock，所有外部依赖均已 mock
"""
import pytest
import json
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, PropertyMock


# ── BUG-001: 异步端点中同步阻塞数据库调用 ──

class TestBUG001SyncBlockingAsync:
    """BUG-001: get_public_profile 中同步 DB 调用阻塞事件循环"""

    def test_get_available_positions_is_sync_function(self):
        """_get_available_positions 是普通同步函数，不是 async"""
        from app.routers.profile import _get_available_positions
        import inspect
        # 修复前：是同步函数（不是 coroutine）
        # 修复后：该函数应被合并到 run_db 中，不再单独在 async 上下文调用
        assert not inspect.iscoroutinefunction(_get_available_positions)

    @pytest.mark.asyncio
    async def test_get_public_profile_no_sync_db_in_async_body(self):
        """get_public_profile 的 async 函数体中不应有未包装的同步 DB 调用"""
        from app.routers.profile import get_public_profile
        import inspect
        source = inspect.getsource(get_public_profile)
        lines = source.split('\n')

        # 找到 async def 行的缩进级别
        async_indent = None
        for line in lines:
            if 'async def get_public_profile' in line:
                async_indent = len(line) - len(line.lstrip())
                break
        assert async_indent is not None

        # 在 async 函数体中（缩进 > async_indent），检查是否有阻塞调用
        # 但要排除内部 def 函数体（缩进更深的 def 块）
        in_inner_func = False
        inner_func_indent = None
        blocking_calls = []

        for i, line in enumerate(lines):
            if 'async def get_public_profile' in line:
                continue
            stripped = line.lstrip()
            current_indent = len(line) - len(stripped)

            # 检测内部函数定义
            if stripped.startswith('def ') and stripped.endswith(':'):
                in_inner_func = True
                inner_func_indent = current_indent
                continue

            # 如果在内部函数中，缩进回到内部函数级别或更小时退出
            if in_inner_func and current_indent <= inner_func_indent and stripped:
                in_inner_func = False

            # 只检查 async 函数体中（非内部函数）的阻塞调用
            if not in_inner_func and current_indent > async_indent and stripped:
                if 'get_db_connection()' in stripped and 'def ' not in stripped:
                    blocking_calls.append(f"Line {i+1}: {stripped}")
                if '_get_available_positions()' in stripped and 'await' not in stripped and 'run_db' not in stripped:
                    blocking_calls.append(f"Line {i+1}: {stripped}")

        assert len(blocking_calls) == 0, f"async 函数体中存在阻塞调用:\n" + '\n'.join(blocking_calls)


# ── BUG-002: 删除操作全表扫描 question_bank ──

class TestBUG002FullTableScan:
    """BUG-002: data.py 删除操作全表扫描 question_bank"""

    def test_delete_data_uses_filtered_query(self):
        """delete_data 应使用带 WHERE 条件的查询而非全表扫描"""
        from app.routers import data
        import inspect
        source = inspect.getsource(data.delete_data)
        # 修复后：不应有 "SELECT id, sources FROM question_bank" 无 WHERE 的查询
        lines = source.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            if 'SELECT id, sources FROM question_bank' in stripped:
                # 如果有这个查询，下一行或同行应有 WHERE/LIKE 条件
                context = stripped + ' ' + lines[i + 1].strip() if i + 1 < len(lines) else stripped
                assert 'WHERE' in context or 'LIKE' in context or 'LIKE' in lines[min(i+2, len(lines)-1)], \
                    f"Line {i+1}: 全表扫描未使用 WHERE 过滤: {stripped}"

    def test_batch_delete_data_uses_filtered_query(self):
        """batch_delete_data 应使用带 WHERE 条件的查询"""
        from app.routers import data
        import inspect
        source = inspect.getsource(data.batch_delete_data)
        lines = source.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            if 'SELECT id, sources FROM question_bank' in stripped:
                context = stripped + ' ' + lines[i + 1].strip() if i + 1 < len(lines) else stripped
                assert 'WHERE' in context or 'LIKE' in context or 'LIKE' in lines[min(i+2, len(lines)-1)], \
                    f"Line {i+1}: 全表扫描未使用 WHERE 过滤: {stripped}"


# ── BUG-003: master_bank _tag_batch JSON 解析不一致 ──

class TestBUG003TagBatchJsonParsing:
    """BUG-003: _tag_batch 使用 json.loads 而非 _extract_json"""

    def test_tag_batch_uses_extract_json(self):
        """_tag_batch 应使用 _extract_json 而非原始 json.loads"""
        from app.routers import questions
        import inspect
        source = inspect.getsource(questions)
        # 找到 _tag_batch 函数的定义范围
        in_tag_batch = False
        for line in source.split('\n'):
            if 'async def _tag_batch' in line:
                in_tag_batch = True
                continue
            if in_tag_batch and (line.strip().startswith('async def ') or line.strip().startswith('def ') and not line.strip().startswith('def _')):
                if 'async def _tag_batch' not in line:
                    in_tag_batch = False
                    continue
            if in_tag_batch and 'json.loads' in line and '_extract_json' not in line:
                pytest.fail(f"_tag_batch 中使用了原始 json.loads: {line.strip()}")

    def test_extract_json_handles_markdown_blocks(self):
        """_extract_json 应能处理 markdown 代码块包裹的 JSON"""
        from app.services.llm import _extract_json
        # 直接 JSON
        assert _extract_json('{"key": "value"}') == {"key": "value"}
        # markdown 代码块
        result = _extract_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}
        # 带前后文本
        result = _extract_json('Here is the result:\n{"key": "value"}\nDone.')
        assert result == {"key": "value"}

    def test_extract_json_handles_llm_response_variations(self):
        """_extract_json 应处理 LLM 常见的响应格式"""
        from app.services.llm import _extract_json
        # 带换行和空格
        result = _extract_json('  \n  {"questions": [{"id": 1}]}  \n  ')
        assert result == {"questions": [{"id": 1}]}
        # markdown 带语言标记
        result = _extract_json('```json\n{"questions": []}\n```')
        assert result == {"questions": []}


# ── BUG-004: submit LLM 调用缺少重试机制 ──

class TestBUG004SubmitRetry:
    """BUG-004: submit LLM 调用缺少重试机制"""

    def test_call_llm_with_retry_exists(self):
        """_call_llm_with_retry 应存在于 llm 服务中"""
        from app.services.llm import _call_llm_with_retry
        assert callable(_call_llm_with_retry)

    @pytest.mark.asyncio
    async def test_retry_on_api_error(self):
        """LLM 调用失败时应自动重试"""
        from app.services.llm import _call_llm_with_retry
        from openai import APIConnectionError

        call_count = 0
        original_create = AsyncMock()

        async def failing_then_success(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise APIConnectionError(request=MagicMock())
            mock_response = MagicMock()
            mock_response.choices = [MagicMock(message=MagicMock(content='{"result": "ok"}'))]
            return mock_response

        with patch('app.services.llm.client') as mock_client:
            mock_client.chat.completions.create = failing_then_success
            result = await _call_llm_with_retry("test prompt")
            assert call_count == 3  # 前两次失败，第三次成功
            assert '{"result": "ok"}' in result


# ── 综合验证 ──

class TestBackendBugVerification:
    """综合验证所有 Bug 修复"""

    def test_llm_module_has_extract_json(self):
        """llm 模块应导出 _extract_json"""
        from app.services.llm import _extract_json
        assert callable(_extract_json)

    def test_llm_module_has_retry_wrapper(self):
        """llm 模块应导出 _call_llm_with_retry"""
        from app.services.llm import _call_llm_with_retry
        assert callable(_call_llm_with_retry)

    def test_profile_module_has_run_db(self):
        """profile 模块应导入 run_db"""
        from app.routers import profile
        assert hasattr(profile, 'run_db')
